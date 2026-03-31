# Hardened Grafana Alloy for Windows

Production-ready Grafana Alloy configuration for Windows Server monitoring with defense-in-depth cardinality protection. Optimized for the [Windows Exporter Dashboard 2025](https://grafana.com/grafana/dashboards/24390-windows-exporter-dashboard-2025/) (ID 24390).

## Quick Start

### 1. Install Grafana Alloy on Windows

Download and install the latest [Grafana Alloy for Windows](https://grafana.com/docs/alloy/latest/set-up/install/windows/).

### 2. Deploy the config

```powershell
# Copy config to Alloy's config directory
Copy-Item config.alloy "C:\Program Files\GrafanaLabs\Alloy\config.alloy"
```

### 3. Set environment variables

```powershell
# Set credentials (get these from grafana.com → My Account → your stack)
[System.Environment]::SetEnvironmentVariable("GCLOUD_RW_API_KEY", "glc_xxx", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_METRICS_URL", "https://prometheus-prod-xx.grafana.net/api/prom/push", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_METRICS_USERNAME", "000000", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_LOGS_URL", "https://logs-prod-xxx.grafana.net/loki/api/v1/push", "Machine")
[System.Environment]::SetEnvironmentVariable("GRAFANA_LOGS_USERNAME", "000000", "Machine")
```

### 4. Restart Alloy

```powershell
Restart-Service Alloy
```

### 5. Import the dashboard

Import [Dashboard 24390](https://grafana.com/grafana/dashboards/24390-windows-exporter-dashboard-2025/) in your Grafana instance.

## Protection Layers

### Layer 1: Allow-list (~90 metric names)

Only metrics required by Dashboard 24390 (plus essential OS/system metrics) pass through. Everything else is dropped. This is the primary cost control.

### Layer 2: Service Cardinality Filter

The biggest source of cardinality explosion on Windows. Without filtering:
- ~150 services × 8 states = **~1,200 series**

With this config:
- 12 monitored services × 2 states (running/stopped) = **~24 series**

Default monitored services:
| Service | Description |
|---------|-------------|
| `windefend` | Windows Defender |
| `alloy` | Grafana Alloy |
| `winrm` | Windows Remote Management |
| `w32time` | Windows Time |
| `wuauserv` | Windows Update |
| `eventlog` | Windows Event Log |
| `dhcp` | DHCP Client |
| `dnscache` | DNS Client |
| `lanmanserver` | Server (SMB) |
| `lanmanworkstation` | Workstation (SMB Client) |
| `mpssvc` | Windows Firewall |
| `bits` | Background Intelligent Transfer |

**To customize:** Edit the service name regex in `config.alloy` Layer 2 rules:
```
regex = "windows_service_state@(windefend|alloy|winrm|w32time|...|my_custom_svc)"
```

### Layer 3: Pattern Block

Drops high-churn metrics from:
- **Virtual NICs**: isatap, Teredo, vEthernet (Hyper-V), 6to4, WFP
- **Hidden volumes**: HarddiskVolume partitions
- **GUID volumes**: Volume{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
- **_Total pseudo-instances**: Aggregate instances for disk and network

### Layer 4: Label Validation

Metrics missing required labels (volume for disk, nic for network, core for CPU) are tagged with `quality_warning="missing_required_labels"` instead of silently dropped. Query `{quality_warning=~".+"}` to find misconfigured sources.

### Layer 5: Value Limits

Volume labels exceeding 100 characters are truncated with `_TRUNCATED` suffix.

## Series Budget

| Environment | Expected Series | Notes |
|---|---|---|
| Typical Windows Server | 200-500 | Depends on CPU cores, disks, NICs |
| Domain Controller | 300-600 | More services, more NICs |
| Hyper-V Host | 250-500 | Virtual NICs filtered out |

Compare this to the **unfiltered default**: 1,500-3,000+ series per host.

## Log Collection

Windows Event Logs (Application, System, Security) are shipped to Loki. Optional cost controls:
- **Filter by level**: Only ship warnings and above
- **Filter by source**: Only ship specific providers
- **Rate limit**: Cap throughput per stream

See the commented examples in `config.alloy`.

## Self-Monitoring (Fleet Management)

Disabled by default. Uncomment the `remotecfg` block to enable Grafana Cloud fleet management (~216 additional series). Only enable if your cardinality budget allows it.

## Testing

### Prerequisites

- Docker and Docker Compose (for Tier 1)
- Python 3.12+ (for Tier 1)
- GCP project with Terraform (for Tier 2)

### Tier 1: Relabeling Pipeline (Docker, any OS)

Tests the 5-layer relabeling pipeline using synthetic Windows-style metrics. The Windows exporter itself doesn't run (it requires Windows), but all relabeling rules are validated.

```bash
make test          # lint + Tier 1
make test-tier1    # Tier 1 only
make lint          # syntax check only
```

### Tier 2: Real Windows Server VMs (GCP)

Tests against actual Windows Server 2019, 2022, and 2025 VMs on GCP with the real Windows exporter running.

```bash
cd tests/tier2/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your GCP project

cd ../../..
make test-tier2
```

This provisions 3 Windows Server VMs, installs Alloy + Prometheus, runs 55+ tests, then tears everything down.

## Windows Compatibility

| OS Version | Status |
|---|---|
| Windows Server 2019 Datacenter | Tested (Tier 2) |
| Windows Server 2022 Datacenter | Tested (Tier 2) |
| Windows Server 2025 Datacenter | Tested (Tier 2) |
| Windows 10/11 (desktop) | Expected to work |

## Customization

### Adding metrics to the allow-list

Add metric names to the `join([...], "|")` block in Layer 1 of `config.alloy`.

### Adding monitored services

Add service names to the regex in Layer 2:
```
regex = "windows_service_state@(windefend|alloy|...|your_service)"
```
Remember to update all three Layer 2 rule groups (service_state, start_mode/status/info).

### Changing the scrape interval

Modify `scrape_interval` in the `prometheus.scrape` block. Default is 60s. Lower intervals increase series volume proportionally.

### Enabling additional collectors

Add collector names to `enabled_collectors` in the `prometheus.exporter.windows` block, then add the new metric names to the Layer 1 allow-list.

## License

MIT — see [LICENSE](LICENSE).
