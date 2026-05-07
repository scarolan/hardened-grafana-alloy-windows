# Default Windows Config: Metric Allow-List Audit

The Grafana Cloud onboarding wizard generates a default Alloy configuration for
Windows hosts. This document compares the metric names in that config's
`prometheus.relabel` keep rule against what the Windows exporter actually emits
as of Alloy v1.16.1 (which bundles windows_exporter v0.31.3).

**Audit date:** 2026-05-07
**Method:** Installed the wizard-generated config on a Windows Server 2022 VM
and queried every metric name in the keep regex against a local Prometheus
instance.

## Summary

The wizard's keep regex contains **42 metric names**. Of those, **9 (21%) do
not match any metric emitted by the bundled exporter** and silently produce no
data. Most are metric names that were valid in older exporter versions but have
since been renamed or removed.

## Missing metrics

| Wizard keep-list name | Status | Likely replacement |
|---|---|---|
| `windows_cs_logical_processors` | Renamed | `windows_cpu_logical_processor` |
| `windows_cs_physical_memory_bytes` | Renamed | `windows_memory_physical_total_bytes` |
| `windows_disk_drive_status` | Changed | Metric name differs in current exporter |
| `windows_os_paging_limit_bytes` | Renamed | `windows_pagefile_limit_bytes` |
| `windows_os_physical_memory_free_bytes` | Renamed | `windows_memory_physical_free_bytes` |
| `windows_os_timezone` | Renamed | `windows_time_timezone` |
| `windows_service_status` | Removed in v0.29.0 | `windows_service_state` |
| `windows_system_boot_time_timestamp_seconds` | Renamed | `windows_system_boot_time_timestamp` |
| `windows_system_system_up_time` | Renamed | `windows_system_up_time` |

## Impact

For most of these, the wizard's keep regex also contains the correct
replacement name, so the data still arrives — the old name is dead weight but
harmless. The notable exception is **`windows_service_status`**:

- `windows_service_status` was a WMI-specific metric (values: ok, degraded,
  error) that was **removed** in windows_exporter v0.29.0 ([PR #1584],
  August 2024).
- The metric needed for service monitoring is `windows_service_state`, which
  reports whether a service is running, stopped, paused, etc.
- `windows_service_state` is **not present** in the wizard's keep regex.
- This means the default config produces **zero service-state data**, and any
  dashboard panel that relies on `windows_service_state` (such as
  [Dashboard 24390]) will show no results.

## How to reproduce

1. Run the Grafana Cloud onboarding wizard for a Windows host.
2. Apply the generated config to a Windows Server VM running Alloy v1.16+.
3. Query Prometheus for each metric name in the keep regex.
4. Observe that the 9 names listed above return no results.

```bash
# Quick check for the service metric
curl -s "http://<prometheus>:9090/api/v1/query?query=windows_service_status"
# Returns empty — metric does not exist in the exporter

curl -s "http://<prometheus>:9090/api/v1/query?query=windows_service_state"
# Also empty — not in the keep regex, so it's dropped even though the exporter emits it
```

## Context

The windows_exporter project has renamed a number of metrics over the past
several release cycles as it migrated from WMI-based collectors to native
Windows API calls. The breaking changes are documented in the exporter's
release notes. The wizard's allow-list appears to have been authored against an
older exporter version and has not been updated to reflect these renames.

The hardened config in this repository uses the current metric names and has
been validated against Windows Server 2019, 2022, and 2025 in the Tier 2 test
suite.

[PR #1584]: https://github.com/prometheus-community/windows_exporter/pull/1584
[Dashboard 24390]: https://grafana.com/grafana/dashboards/24390-windows-exporter-dashboard-2025/
