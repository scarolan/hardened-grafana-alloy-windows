# Environment Variables Reference

Single canonical reference for every environment variable either `config.alloy` or `fleet-config.alloy` reads. Both deployment paths point here.

## The Five Required Variables

| Variable | What it is | Where to find the value | Required by |
|----------|------------|-------------------------|-------------|
| `GCLOUD_RW_API_KEY` | Access policy token with `set:alloy-data-write` scope. Shared password for Prometheus, Loki, and Fleet Management. | Access Policies → your policy → Add token. Copy immediately — shown once. | Path 1, Path 2 |
| `GRAFANA_METRICS_URL` | Prometheus remote_write URL | My Account → stack → Prometheus → Details | Path 1, Path 2 |
| `GRAFANA_METRICS_USERNAME` | Prometheus stack ID (6-digit number) | My Account → stack → Prometheus → Details | Path 1, Path 2 |
| `GRAFANA_LOGS_URL` | Loki push URL | My Account → stack → Loki → Details | Path 1, Path 2 |
| `GRAFANA_LOGS_USERNAME` | Loki stack ID (6-digit number) | My Account → stack → Loki → Details | Path 1, Path 2 |

**Path 2 users:** you still need all five. The bootstrap `fleet-config.alloy` uses `GCLOUD_RW_API_KEY` directly, and every Fleet Management pipeline you push needs the other four (because FM pipelines live in sealed modules that can't share the bootstrap's endpoints). See [fleet-management.md](fleet-management.md) for the rationale.

## How to Set Them

Windows services don't inherit your user environment. You have two practical options — **Machine-scope system variables** (easiest, visible in the Control Panel UI) or **service-scoped variables via the registry** (cleaner isolation, not visible to other processes).

### Option A — Machine-scope system variables (recommended for most deployments)

Visible to every service and every new shell. Set once, inherited by Alloy on restart.

**PowerShell (one host):**

```powershell
[System.Environment]::SetEnvironmentVariable("GCLOUD_RW_API_KEY", "glc_xxxxxxxxxxxxx", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_METRICS_URL", "https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_METRICS_USERNAME", "000000", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_LOGS_URL", "https://logs-prod-006.grafana.net/loki/api/v1/push", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_LOGS_USERNAME", "000000", "Machine")

Restart-Service Alloy
```

**UI (one host):** Start → "Edit the system environment variables" → Environment Variables... → **System variables** → New.

**GPO (fleet-wide):** Computer Configuration → Preferences → Windows Settings → Environment. Create one entry per variable, Action = Replace, target = Machine.

### Option B — Service-scoped registry key (isolates Alloy's env from other services)

Values live under the Alloy service and are only visible to the Alloy process. Slightly more effort; no leakage into new shells.

```powershell
# Create or overwrite the service-specific environment
Set-ItemProperty `
  -Path "HKLM:\SYSTEM\CurrentControlSet\Services\Alloy" `
  -Name Environment `
  -Type MultiString `
  -Value @(
    "GCLOUD_RW_API_KEY=glc_xxxxxxxxxxxxx",
    "GRAFANA_METRICS_URL=https://prometheus-prod-13-prod-us-east-0.grafana.net/api/prom/push",
    "GRAFANA_METRICS_USERNAME=000000",
    "GRAFANA_LOGS_URL=https://logs-prod-006.grafana.net/loki/api/v1/push",
    "GRAFANA_LOGS_USERNAME=000000"
  )

Restart-Service Alloy
```

Notes:
- The `Environment` value is a `REG_MULTI_SZ` — one `KEY=value` per array element.
- Service-scope wins over machine-scope if both are set.

## Verify the Service Sees Them

**Check your current shell (only useful for Option A):**

```powershell
Get-ChildItem env: | Where-Object Name -like "GRAFANA*"
Get-ChildItem env: | Where-Object Name -eq "GCLOUD_RW_API_KEY"
```

**Check what the service will pick up on next start (works for Option B, or Option A via refresh):**

```powershell
# Option A — machine-scope, what the next service start will inherit:
[System.Environment]::GetEnvironmentVariables("Machine").Keys |
  Where-Object { $_ -like "GRAFANA_*" -or $_ -eq "GCLOUD_RW_API_KEY" }

# Option B — what's in the service's registry:
(Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\Alloy" -ErrorAction SilentlyContinue).Environment
```

**Check the running Alloy process:** the process environment is fixed at start time, so if you changed values after starting Alloy, `Restart-Service Alloy` first.

## Rotating Credentials

1. Create a new access policy token (don't delete the old one yet).
2. Update `GCLOUD_RW_API_KEY` (same mechanism you used to set it) and `Restart-Service Alloy`.
3. Confirm data is still flowing (see the smoke tests in the deployment guides).
4. Delete the old token.

For URL / username changes (e.g. stack migration), update all four endpoint vars together and restart. Because the values live on the host, the change is atomic per host — no re-editing pipelines in the Fleet Management UI.

## Secret Hygiene

- Prefer Option B (service-scoped) on hosts where other services run as the same user and you don't want them to read the API key via `Get-ChildItem env:`.
- Don't paste the API key into Fleet Management pipeline YAML. Reference it via `sys.env("GCLOUD_RW_API_KEY")` so it stays on the host.
- If you use GPO to distribute values, confirm your GPO store isn't exposing them broadly — anyone with read access to the GPO can see the values.
