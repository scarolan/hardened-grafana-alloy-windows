# Path 2 — Grafana Fleet Management (Windows)

Each Windows host runs a minimal bootstrap config (`fleet-config.alloy`) that connects to Grafana Cloud Fleet Management and polls for pipeline updates. You build and push the actual collection pipelines from the Fleet Management UI, so config changes don't require touching hosts.

> Prefer having the full config on each host? See **[Path 1 — Direct Deployment](direct-deployment.md)**.

## What You Need

### Create an Access Policy and Token

1. Visit your org's access policies page: `https://grafana.com/orgs/YOURORG/access-policies`
2. Click **Create access policy**
3. Give it a descriptive name (e.g. "Grafana Alloy POV")
4. Under **Realms**, select the stack(s) this policy applies to
5. Skip the scopes checkboxes. Use the **Add scope** dropdown and select **set:alloy-data-write**
6. Click **Create**

![Create access policy](create_access_policy.png)

7. On the newly created policy, click **Add token**

![Add token button](add_token.png)

8. Name the token and set an expiration (e.g. 90 days for a POV)
9. Click **Create**

![Create token](create_token.png)

**Copy the token immediately.** You only get one chance. This is your `GCLOUD_RW_API_KEY`.

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

# Edit the remotecfg URL and username to match your stack
notepad "C:\Program Files\GrafanaLabs\Alloy\config.alloy"
```

Or open the [raw file on GitHub](https://raw.githubusercontent.com/scarolan/hardened-grafana-alloy-windows/main/fleet-config.alloy), copy the contents, and paste into `C:\Program Files\GrafanaLabs\Alloy\config.alloy`.

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

**Why all five, not just the API key?** See [Why env vars instead of hardcoding values into pipelines?](#why-env-vars-instead-of-hardcoding-values-into-pipelines) below.

## Step 4: Start the Service

```powershell
Restart-Service Alloy
Get-Service Alloy  # should be "Running"
```

Check that Alloy connected to Fleet Management — in the FM UI the collector should appear under Collectors within 60 seconds.

## Step 5: Build Your First Pipeline

In Grafana Cloud > Fleet Management > Pipelines:

1. Click **Add pipeline**
2. Give it a name and set matchers (e.g. `env=prod`) so it targets this collector
3. Paste your pipeline config — **must include its own `prometheus.remote_write` and/or `loki.write` block**. See [`examples/blackbox.alloy`](../examples/blackbox.alloy) for a complete self-contained pattern. Copy the hardened `config.alloy` from this repo as a starting point for Windows host monitoring.
4. Save and apply

Within ~60 seconds, Alloy on the host polls Fleet Management, pulls the new pipeline, and starts collecting.

> **⚠️ Critical gotcha: remote_write endpoints are not shared**
>
> The `prometheus.remote_write` and `loki.write` blocks in `fleet-config.alloy` are **not reachable** from pipelines you push via Fleet Management. Each FM pipeline is wrapped in a sealed `declare` module — components inside can't reference components in the parent scope.
>
> **Every FM pipeline that ships metrics or logs must include its own `prometheus.remote_write` and/or `loki.write` block.** Use `sys.env()` for credentials so you don't duplicate secrets across pipelines.

## Step 6: Verify and Import the Dashboard

After the pipeline is applied, metrics should appear in your Grafana Cloud stack. Import [**Dashboard ID 24390**](https://grafana.com/grafana/dashboards/24390-windows-exporter-dashboard-2025/) (Windows Exporter Dashboard 2025).

Troubleshooting from the host:

```powershell
Get-Service Alloy
Get-WinEvent -LogName Application -ProviderName Alloy -MaxEvents 20
```

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
| 5 | Build pipelines | One-time, in Fleet Management UI |
| 6 | Import dashboard | One-time, in Grafana Cloud UI |

Config changes after Step 5 happen entirely in the FM UI — no touching hosts.
