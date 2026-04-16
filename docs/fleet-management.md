# Path 2 — Grafana Fleet Management (Windows)

Each Windows host runs a minimal bootstrap config (`fleet-config.alloy`) that connects to Grafana Cloud Fleet Management and polls for pipeline updates. You build and push the actual collection pipelines from the Fleet Management UI, so config changes don't require touching hosts.

> Prefer having the full config on each host? See **[Path 1 — Direct Deployment](direct-deployment.md)**.

## What You Need

### Create an Access Policy and Token

1. Visit your org's access policies page: `https://grafana.com/orgs/<your-org-slug>/access-policies` — replace `<your-org-slug>` with the slug from your Grafana Cloud org URL (the part after `/orgs/`)
2. Click **Create access policy**
3. Give it a descriptive name (e.g. "Fleet Management")
4. Under **Realms**, select the stack(s) this policy applies to
5. **Ignore the individual scope checkboxes.** Instead, use the **Add scope** dropdown at the bottom and pick `set:alloy-data-write`
6. Click **Create**

![Create access policy](create_access_policy.png)

7. On the newly created policy, click **Add token**

![Add token button](add_token.png)

8. Name the token and set an expiration (90 days is typical for a pilot)
9. Click **Create**

![Create token](create_token.png)

**Copy the token value immediately — it's shown exactly once.** This is your `GCLOUD_RW_API_KEY`.

### Gather Your Endpoints

From grafana.com > My Account > your stack:

| Value | Example | Where to Find |
|-------|---------|---------------|
| Metrics URL | `https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push` | Prometheus > Details |
| Metrics Username | `000000` | Prometheus > Details |
| Logs URL | `https://logs-prod-006.grafana.net/loki/api/v1/push` | Loki > Details |
| Logs Username | `000000` | Loki > Details |
| Fleet Management URL | `https://fleet-management-prod-008.grafana.net` | Fleet Management > Collector configuration |
| Fleet Management Username | `654321` | Fleet Management > Collector configuration |

## Step 1: Install Alloy

Download the Windows installer zip from [Grafana Alloy releases](https://github.com/grafana/alloy/releases). The installer registers Alloy at `C:\Program Files\GrafanaLabs\Alloy\` and creates a Windows service named **Alloy**.

Silent install:

```powershell
Expand-Archive -Path alloy-installer-windows-amd64.exe.zip -DestinationPath .\alloy-installer
.\alloy-installer\alloy-installer-windows-amd64.exe /S
```

## Step 2: Deploy `fleet-config.alloy`

Grab the bootstrap config from this repo and replace the default `config.alloy` the installer dropped. Most users do this without cloning — pull the raw file, or copy-paste from the browser:

```powershell
# Download directly from the repo
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-windows/main/fleet-config.alloy" `
  -OutFile "C:\Program Files\GrafanaLabs\Alloy\config.alloy"
```

Or open the [raw file on GitHub](https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-windows/main/fleet-config.alloy), copy the contents, and paste into `C:\Program Files\GrafanaLabs\Alloy\config.alloy`.

### Two lines to edit

Open the config (`notepad "C:\Program Files\GrafanaLabs\Alloy\config.alloy"`) and find the `remotecfg` block at the top — it's the block that connects Alloy to Fleet Management. Edit two placeholders:

```alloy
remotecfg {
  url            = "https://fleet-management-prod-008.grafana.net"  // ← your regional FM URL
  id             = constants.hostname
  poll_frequency = "60s"
  attributes     = encoding.from_json(coalesce(`{"env":"pov","team":"ops"}`, `{}`))

  basic_auth {
    username = "<fleet-management-username>"   // ← your FM instance ID (6-digit number)
    password = sys.env("GCLOUD_RW_API_KEY")
  }
}
```

Both values come from the Fleet Management UI: **Grafana Cloud → Fleet Management → Collector configuration** shows the URL and username for your stack.

The `attributes` map is how you group collectors in FM. The default `env:pov` / `team:ops` are placeholders — adjust to match however you want to target collectors (by team, environment, role, etc.). We'll use these attributes as matchers in Step 5.

This config is deliberately tiny — it only connects to Fleet Management. The real pipelines come down over the wire.

## Step 3: Set Environment Variables

Set all five as **Machine-level** environment variables on each host:

```powershell
[System.Environment]::SetEnvironmentVariable("GCLOUD_RW_API_KEY", "glc_xxxxxxxxxxxxx", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_METRICS_URL", "https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_METRICS_USERNAME", "000000", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_LOGS_URL", "https://logs-prod-006.grafana.net/loki/api/v1/push", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_LOGS_USERNAME", "000000", "Machine")
```

For scale-out via GPO: Computer Configuration > Preferences > Windows Settings > Environment. Create one entry per variable with Action "Replace" and target "Machine".

Full reference (including service-scoped registry option for better isolation and verification commands): see [env-vars.md](env-vars.md).

**Why all five, not just the API key?** See [Why env vars instead of hardcoding values into pipelines?](#why-env-vars-instead-of-hardcoding-values-into-pipelines) below.

## Step 4: Start the Service

```powershell
Restart-Service Alloy
Get-Service Alloy  # should be "Running"
```

Check that Alloy connected to Fleet Management — in the FM UI the collector should appear under Collectors within 60 seconds.

## Step 5: Prove the Plumbing Works with a Minimal Pipeline

Before deploying the hardened config via FM, send a tiny test pipeline to confirm the whole loop works: **host → FM → pipeline pulled → data landing in your stack.**

In Grafana Cloud → Fleet Management → Pipelines:

1. Click **Add pipeline**
2. Name it something like `fm-smoke-test`
3. Under **Matchers**, target this collector. Two common options:
   - **By attribute** (recommended): match the `env` attribute you set in `fleet-config.alloy`. If you kept the default, that's `env=pov`. This makes the pipeline reusable across all dev/trial collectors.
   - **By collector ID**: match the specific hostname of this collector (the `id` field in `fleet-config.alloy` is set to `constants.hostname`, so it's literally your host's hostname).
4. Paste the pipeline below in the config editor
5. **Save** and **Apply**

```alloy
// Smoke-test pipeline — proves FM can push config to the host and that
// remote_write credentials work. Replace this with the hardened config
// after you confirm data arrives.

prometheus.remote_write "smoke_test" {
  endpoint {
    url = sys.env("GRAFANA_METRICS_URL")
    basic_auth {
      username = sys.env("GRAFANA_METRICS_USERNAME")
      password = sys.env("GCLOUD_RW_API_KEY")
    }
  }
}

prometheus.exporter.self "alloy_self" { }

discovery.relabel "alloy_self" {
  targets = prometheus.exporter.self.alloy_self.targets

  rule {
    target_label = "instance"
    replacement  = constants.hostname
  }

  rule {
    target_label = "job"
    replacement  = "fm_smoke_test"
  }
}

prometheus.scrape "alloy_self" {
  targets         = discovery.relabel.alloy_self.output
  forward_to      = [prometheus.remote_write.smoke_test.receiver]
  scrape_interval = "30s"
}
```

Within ~60 seconds Alloy polls FM, pulls this pipeline, and starts scraping its own internal metrics. Verify in **Explore → Prometheus**:

```promql
# Should return one series per collector running the smoke-test pipeline
alloy_build_info{job="fm_smoke_test"}
```

If that returns nothing after two minutes:

- Check the host's Windows Event Log for Alloy errors (`Get-WinEvent -LogName Application -ProviderName Alloy -MaxEvents 20`)
- In FM UI, open the collector and confirm the pipeline shows up as "Applied"
- Verify env vars are set: see [env-vars.md](env-vars.md)

> **⚠️ Critical gotcha: remote_write endpoints are not shared**
>
> The `prometheus.remote_write` and `loki.write` blocks in `fleet-config.alloy` are **not reachable** from pipelines you push via Fleet Management. Each FM pipeline is wrapped in a sealed `declare` module — components inside can't reference components in the parent scope.
>
> **Every FM pipeline that ships metrics or logs must include its own `prometheus.remote_write` and/or `loki.write` block.** Use `sys.env()` for credentials so you don't duplicate secrets across pipelines.

## Step 6: Deploy the Hardened Pipeline

Once the smoke test works, edit the pipeline in FM and replace its contents with your real collection config. For Windows host monitoring, start from the hardened [`config.alloy`](https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-windows/main/config.alloy) in this repo. For custom collection (blackbox probes, app scrapes), see [`examples/blackbox.alloy`](../examples/blackbox.alloy) as a template.

Any pipeline you paste must include its own `prometheus.remote_write` / `loki.write` block (see the gotcha above).

Save and apply. Within ~60 seconds the host swaps the smoke-test pipeline for the real one.

## Step 7: Verify and Import the Dashboard

### Quick PromQL smoke test

Confirm data is flowing *before* importing the dashboard. Go to **Explore → Prometheus** and run:

```promql
# 1. Is this host's Alloy alive and scraping?
up{instance="<your-hostname>"}
# Expected: 1

# 2. How many distinct series is this host shipping?
count(count by (__name__) ({instance="<your-hostname>"}))
# Expected: ~135 for a typical 2-vCPU host, ~150-250 on larger servers

# 3. Any metrics missing required labels? (should be empty in production)
count({quality_warning="missing_required_labels", instance="<your-hostname>"})
```

If query 1 is `0` or empty, check the service and logs:

```powershell
Get-Service Alloy
Get-WinEvent -LogName Application -ProviderName Alloy -MaxEvents 20 | Format-List
```

### Import the dashboard

Once the smoke tests pass, import [**Dashboard ID 24390**](https://grafana.com/grafana/dashboards/24390-windows-exporter-dashboard-2025/) (Windows Exporter Dashboard 2025). All panels should populate.

## Why env vars instead of hardcoding values into pipelines?

Two reasons, neither adds meaningful operational burden:

1. **Secrets don't belong in the Fleet Management UI.** Pipelines pushed via FM are stored in Grafana Cloud's config store and visible to anyone with FM access. Hardcoding the API key there means it lives in every pipeline export, backup, and screenshot. Keeping it in `sys.env()` means the secret lives on the host — rotated through your existing secret management, never echoed back in the UI.

2. **You already have to set `GCLOUD_RW_API_KEY` on the host.** Alloy can't connect to Fleet Management without it. Since you're already setting one env var, adding four more (URLs + usernames) is ~30 seconds of extra work via the same registry key or `[Environment]::SetEnvironmentVariable(..., 'Machine')` call. It's not "yet another file to manage" — it's four more lines in the mechanism you already use.

URLs and usernames aren't secret, but keeping them next to the password means rotations and stack migrations are atomic: change host env, restart Alloy, done. No re-editing N pipelines in the FM UI.

## Summary

| Step | What | How (at scale) |
|------|------|----------------|
| 1 | Install Alloy | GPO startup script / SCCM / Intune |
| 2 | Deploy fleet-config.alloy | File copy via GPO Preferences / SCCM package |
| 3 | Set env vars (all 5) | GPO Preferences > Environment Variables |
| 4 | Restart service | Startup script or scheduled task |
| 5 | Smoke-test pipeline in FM | Validates host → FM → stack loop |
| 6 | Deploy hardened pipeline in FM | Replace smoke-test with real config |
| 7 | Verify + import dashboard | PromQL checks, then dashboard 24390 |

Config changes after Step 6 happen entirely in the FM UI — no touching hosts.
