# Windows Metrics Benchmark: Active Series by Configuration

How many active series does it take to monitor a Windows server? We benchmarked several Alloy configurations on a Windows Server 2022 Datacenter VM (2 vCPUs, 8 GB RAM, 1 disk, 1 NIC, 200 Windows services) to find out.

## Results

| Configuration | Active Series | Unique Metric Names | Description |
|---|---|---|---|
| Bare minimum | **16** | 7 | CPU, memory, disk, network only. Just enough to answer "is this host alive?" |
| Hardened (Dashboard 24390) | **135** | ~70 | Full dashboard coverage with 5-layer cardinality protection |
| Default (10 collectors, no filtering) | **2,909** | ~110 | Same collectors as the hardened config but with zero filtering |

### Comparison with Linux

For reference, equivalent benchmarks on a Linux t3.micro (1 vCPU):

| Configuration | Windows (2 vCPU) | Linux (1 vCPU) |
|---|---|---|
| Bare minimum (CPU/Disk/Mem/Net) | 16 | 11 |
| Dashboard-optimized | 135 | 50 |
| Unfiltered (all default metrics) | 2,909 | 337 |

Windows produces roughly 2-3x more series than Linux for equivalent dashboard coverage, driven by per-core CPU metrics and the service collector.

## Why Windows produces more series

### The service collector

The service collector is by far the largest source of cardinality on Windows. On a standard Windows Server 2022 with 200 services:

| Metric | Unfiltered Series | With Hardened Filter |
|---|---|---|
| `windows_service_state` | 1,400 (200 services x 7 states) | 6 (3 services x 2 states) |
| `windows_service_start_mode` | 1,000 (200 services x 5 modes) | 15 |
| `windows_service_info` | 200 | 3 |
| `windows_service_process` | 72 | 0 (not in allowlist) |
| **Total service series** | **2,672** | **24** |

Service metrics account for **92% of unfiltered series** (2,672 of 2,909). The hardened config's Layer 2 filter reduces this to 24 series by monitoring only essential services in running/stopped states.

### Per-core CPU scaling

CPU metrics scale linearly with core count. On a 2-core VM, `windows_cpu_time_total` produces 10 series (2 cores x 5 modes). On a 16-core server, that becomes 80 series from this one metric alone.

### Disk and network scaling

Each disk volume adds ~13 series (logical disk metrics). Each physical NIC adds ~10 series (network metrics). The hardened config's Layer 3 filter removes virtual NICs, hidden volumes, and pseudo-instances to keep this predictable.

## Bare minimum breakdown (16 series)

The absolute minimum configuration uses 4 collectors (cpu, logical_disk, memory, net) with a tight allowlist:

| Metric | Series | Notes |
|---|---|---|
| `up` | 1 | Scrape target health |
| `windows_cpu_time_total` | 10 | 2 cores x 5 modes (idle, user, privileged, interrupt, dpc) |
| `windows_memory_available_bytes` | 1 | |
| `windows_logical_disk_free_bytes` | 1 | C: drive only (after filtering) |
| `windows_logical_disk_size_bytes` | 1 | C: drive only |
| `windows_net_bytes_received_total` | 1 | 1 physical NIC |
| `windows_net_bytes_sent_total` | 1 | 1 physical NIC |
| **Total** | **16** | |

## Hardened config breakdown (135 series)

The hardened config uses 10 collectors with the 5-layer filtering pipeline. Approximate breakdown by category:

| Category | Series | Key metrics |
|---|---|---|
| CPU | ~24 | time_total, interrupts, dpcs, frequency, performance, utility (per core) |
| Memory | ~19 | available, physical, cache, pool, standby, swap, page faults |
| Logical disk | ~13 | free, size, reads, writes, latency, idle, split_ios, queued |
| Network | ~10 | bytes in/out, packets, errors, discards, bandwidth |
| Service | ~24 | 12 services x 2 states (running/stopped) + start_mode + info |
| System | ~7 | context switches, exceptions, processes, threads, queue length, system calls |
| Disk drive | ~13 | info, status, size |
| OS | ~2 | info, hostname |
| Pagefile | ~1 | limit_bytes |
| Time | ~2 | NTP offset, round trip delay |
| Exporter | ~21 | build_info, collector_duration (x10), collector_success (x10) |
| Up | 1 | Scrape target health |
| **Total** | **~135** | |

## How series scale with hardware

The hardened config's series count scales predictably with hardware:

| Hardware Profile | Expected Series | Notes |
|---|---|---|
| Small cloud VM (2 vCPU, 1 disk, 1 NIC) | 130-150 | Benchmark baseline |
| Mid-range server (8 vCPU, 2 disks, 1 NIC) | 175-225 | +40 CPU, +13 disk |
| Large server (16 vCPU, 4 disks, 2 NICs) | 250-325 | +70 CPU, +39 disk, +10 net |
| Domain controller (8 vCPU, 2 disks, 3 NICs) | 200-275 | More NICs, more services if customized |

A real-world production deployment (larger servers) validated at approximately **190 active series per host**, consistent with these estimates.

## Methodology

- **Platform**: GCP n2-standard-2, Windows Server 2022 Datacenter (Build 20348)
- **Alloy version**: Latest release (embeds windows_exporter v0.31.3)
- **Measurement**: Active series counted via Grafana Cloud Prometheus API using `count({instance="...", job="integrations/windows_exporter"})`
- **Staleness**: Each configuration ran for 7+ minutes (longer than the 5-minute Prometheus staleness window) to ensure clean per-configuration counts
- **Scrape interval**: 60 seconds (default)
- **Date**: April 2026

## Key takeaways

1. **Service filtering is essential on Windows.** Without it, the service collector alone generates 2,672 series on a standard server. The hardened config reduces this to 24.

2. **The hardened config provides full dashboard coverage at ~135 series.** Every metric powers a panel in Dashboard 24390. No wasted series.

3. **Series scale linearly with cores, disks, and NICs.** Budget approximately +5 series per additional CPU core, +13 per disk volume, and +10 per physical NIC.

4. **Windows needs 2-3x more series than Linux** for equivalent monitoring coverage, primarily due to service monitoring and richer CPU/memory metrics.
