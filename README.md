# Hardened Grafana Alloy for Windows

A default Grafana Alloy install on Windows ships around **2,900 series per host**, driven mostly by the service collector exploding into thousands of idle rows. This repo is a prebuilt, production-ready Alloy config that ships exactly what the [Windows Exporter Dashboard 2025 (ID 24390)](https://grafana.com/grafana/dashboards/24390-windows-exporter-dashboard-2025/) needs and nothing else. Five layers of cardinality protection keep a typical host around **135 series**, scaling to **150–250** on bigger servers — predictable cost, no dashboard regressions.

## Pick Your Deployment Path

| Path | When to use | Guide |
|------|-------------|-------|
| **Direct Deployment** | The hardened `config.alloy` lives on each host. You manage config updates via your existing tooling (GPO, SCCM, Intune, manual). | [docs/direct-deployment.md](docs/direct-deployment.md) |
| **Fleet Management** | A minimal bootstrap config (`fleet-config.alloy`) lives on each host. You build and push the real collection pipelines centrally via Grafana Cloud Fleet Management. | [docs/fleet-management.md](docs/fleet-management.md) |

Both paths need the same five environment variables. See **[docs/env-vars.md](docs/env-vars.md)** for the canonical reference and how to set them (Machine scope, service-scoped registry, GPO).

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

Benchmarked on Windows Server 2022 (2 vCPUs, 8 GB RAM, 1 disk, 1 NIC, 200 services):

| Configuration | Active Series | Description |
|---|---|---|
| Bare minimum (4 collectors) | **16** | CPU, memory, disk, network only |
| **Hardened (this config)** | **135** | Full Dashboard 24390 coverage |
| Unfiltered (same 10 collectors, no filtering) | **2,909** | Service collector explodes to 2,672 series |

The hardened config scales with hardware — approximately +5 series per CPU core, +13 per disk volume, +10 per NIC. Production deployments on larger servers typically land around **150–250 series per host**.

See [docs/windows-metrics-benchmark.md](docs/windows-metrics-benchmark.md) for the full breakdown and methodology.

## Log Collection

Windows Event Logs (Application, System, Security) are shipped to Loki. Optional cost controls:
- **Filter by level**: Only ship warnings and above
- **Filter by source**: Only ship specific providers
- **Rate limit**: Cap throughput per stream

See the commented examples in `config.alloy`.

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
