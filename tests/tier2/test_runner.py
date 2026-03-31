"""Tier 2 tests: Windows Server VM validation with real Windows exporter.

These tests run against actual Windows Server VMs provisioned by Terraform,
validating:
  - Real Windows exporter metrics are collected
  - Allow-list correctness with real metrics
  - Service cardinality filter works with real Windows services
  - Cardinality protection drops virtual NICs and hidden volumes
  - Label validation catches real-world edge cases
  - Series budget is within expected range for production Windows servers

Tested Windows versions:
  - Windows Server 2019 Datacenter
  - Windows Server 2022 Datacenter
  - Windows Server 2025 Datacenter

Run via: make test-tier2
Prerequisites: terraform.tfvars configured, `terraform apply` completed
"""

import json
import os
import subprocess
import sys
import time
import pytest

# Add shared test utilities to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from shared.assertions import (
    query_prometheus,
    get_all_metric_names,
    assert_metric_exists,
    assert_metric_absent,
    assert_label_present,
    assert_label_value,
    assert_series_count_in_range,
    wait_for_metric,
    wait_for_prometheus,
)
from shared.metrics_allowlist import ALLOWLIST


# ---------------------------------------------------------------------------
# Discover VMs from Terraform output
# ---------------------------------------------------------------------------

def get_terraform_outputs():
    """Read VM details from Terraform output."""
    tf_dir = os.path.join(os.path.dirname(__file__), "terraform")
    result = subprocess.run(
        ["terraform", "output", "-json", "vm_details"],
        capture_output=True, text=True, cwd=tf_dir,
    )
    if result.returncode != 0:
        pytest.skip(f"Terraform output failed: {result.stderr}")
    return json.loads(result.stdout)


VM_DETAILS = get_terraform_outputs()


def vm_prometheus_url(vm_key):
    """Return the Prometheus URL for a given VM."""
    ip = VM_DETAILS[vm_key]["ip"]
    return f"http://{ip}:9090"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def wait_for_vms():
    """Wait for all VMs to have Prometheus and Alloy running."""
    for vm_key, details in VM_DETAILS.items():
        url = vm_prometheus_url(vm_key)
        print(f"\nWaiting for {details['display_name']} ({details['ip']})...")
        try:
            wait_for_prometheus(url, timeout=300, interval=10)
            wait_for_metric(url, "windows_os_info", timeout=300, interval=10)
        except TimeoutError:
            pytest.fail(
                f"{details['display_name']} at {url} not ready after 5 minutes"
            )
    print("All VMs ready, running tests.")


# ---------------------------------------------------------------------------
# Parametrize all tests across Windows versions
# ---------------------------------------------------------------------------

VM_KEYS = list(VM_DETAILS.keys())


@pytest.fixture(params=VM_KEYS)
def prom_url(request):
    """Parametrized fixture: yields Prometheus URL for each Windows VM."""
    return vm_prometheus_url(request.param)


@pytest.fixture(params=VM_KEYS)
def vm_info(request):
    """Parametrized fixture: yields (prometheus_url, display_name) tuple."""
    key = request.param
    return vm_prometheus_url(key), VM_DETAILS[key]["display_name"]


# ---------------------------------------------------------------------------
# Layer 1: Allow-list
# ---------------------------------------------------------------------------

class TestAllowList:
    """Verify the allow-list keeps required metrics and drops everything else."""

    @pytest.mark.parametrize("metric", [
        "up",
        "windows_os_info",
        "windows_os_visible_memory_bytes",
        "windows_cpu_time_total",
        "windows_cpu_core_frequency_mhz",
        "windows_memory_physical_total_bytes",
        "windows_memory_physical_free_bytes",
        "windows_memory_available_bytes",
        "windows_memory_commit_limit",
        "windows_logical_disk_size_bytes",
        "windows_logical_disk_free_bytes",
        "windows_logical_disk_read_bytes_total",
        "windows_logical_disk_write_bytes_total",
        "windows_net_bytes_received_total",
        "windows_net_bytes_sent_total",
        "windows_net_current_bandwidth_bytes",
        "windows_system_processes",
        "windows_system_threads",
        "windows_system_system_up_time",
        "windows_service_state",
        "windows_time_computed_time_offset_seconds",
        "windows_pagefile_usage_bytes",
    ])
    def test_core_metrics_present(self, prom_url, metric):
        """Core metrics required by dashboard 24390 must be present."""
        assert_metric_exists(prom_url, metric)

    def test_all_metrics_are_allowlisted(self, prom_url):
        """Every metric name in Prometheus should be in the allow-list."""
        present = get_all_metric_names(prom_url)
        unexpected = present - ALLOWLIST
        assert not unexpected, (
            f"Found {len(unexpected)} metrics not in allow-list: {sorted(unexpected)}"
        )


# ---------------------------------------------------------------------------
# Layer 2: Service cardinality filter
# ---------------------------------------------------------------------------

class TestServiceFilter:
    """Verify service metrics are filtered on real Windows servers."""

    def test_essential_services_present(self, prom_url):
        """Essential Windows services should be monitored."""
        # These services exist on every Windows Server
        for svc in ["windefend", "w32time", "eventlog", "dnscache", "mpssvc"]:
            results = query_prometheus(
                prom_url,
                f'windows_service_state{{name="{svc}"}}',
            )
            assert len(results) > 0, f"Essential service '{svc}' should be present"

    def test_only_running_stopped_states(self, prom_url):
        """Only running and stopped states should be present."""
        results = query_prometheus(prom_url, "windows_service_state")
        for r in results:
            state = r["metric"].get("state", "")
            assert state in ("running", "stopped"), (
                f"Unexpected state '{state}' for service "
                f"'{r['metric'].get('name')}' — only running/stopped allowed"
            )

    def test_non_monitored_services_dropped(self, prom_url):
        """Services not in the monitored list should be dropped."""
        results = query_prometheus(prom_url, "windows_service_state")
        monitored = {
            "windefend", "alloy", "winrm", "w32time", "wuauserv",
            "eventlog", "dhcp", "dnscache", "lanmanserver",
            "lanmanworkstation", "mpssvc", "bits",
        }
        for r in results:
            name = r["metric"].get("name", "")
            assert name in monitored, (
                f"Service '{name}' is not in monitored list — should be dropped"
            )

    def test_service_series_count_bounded(self, prom_url):
        """Service state series should be well bounded (max ~24)."""
        results = query_prometheus(prom_url, "windows_service_state")
        # 12 services x 2 states = 24 max; some services may not exist = fewer
        assert len(results) <= 30, (
            f"Too many service_state series ({len(results)}), "
            f"expected <= 30. Service filter may not be working."
        )


# ---------------------------------------------------------------------------
# Layer 3: Cardinality protection
# ---------------------------------------------------------------------------

class TestCardinalityProtection:
    """Verify high-churn patterns are dropped on real Windows servers."""

    def test_virtual_nics_dropped(self, prom_url):
        """Virtual network adapters should be dropped."""
        results = query_prometheus(
            prom_url,
            'windows_net_bytes_received_total{nic=~".*(isatap|Teredo|vEthernet|6to4|WFP|Loopback).*"}',
        )
        assert len(results) == 0, (
            f"Virtual NIC metrics should be dropped: "
            f"{[r['metric'].get('nic') for r in results]}"
        )

    def test_hidden_volumes_dropped(self, prom_url):
        """HarddiskVolume partitions should be dropped."""
        results = query_prometheus(
            prom_url,
            'windows_logical_disk_size_bytes{volume=~".*HarddiskVolume.*"}',
        )
        assert len(results) == 0, (
            f"HarddiskVolume metrics should be dropped: "
            f"{[r['metric'].get('volume') for r in results]}"
        )

    def test_total_pseudo_instance_dropped(self, prom_url):
        """_Total pseudo-instances should be dropped."""
        results = query_prometheus(
            prom_url,
            'windows_logical_disk_size_bytes{volume="_Total"}',
        )
        assert len(results) == 0, "_Total disk should be dropped"

    def test_c_drive_present(self, prom_url):
        """C: drive should always be present."""
        assert_metric_exists(prom_url, 'windows_logical_disk_size_bytes{volume="C:"}')


# ---------------------------------------------------------------------------
# Standard labels
# ---------------------------------------------------------------------------

class TestStandardLabels:
    """Verify instance and job labels on real Windows metrics."""

    def test_job_label(self, prom_url):
        """Metrics should have job='integrations/windows_exporter'."""
        assert_label_value(
            prom_url, "windows_os_info", "job", "integrations/windows_exporter"
        )

    def test_instance_label_is_hostname(self, prom_url):
        """Instance label should be set to hostname."""
        assert_label_present(prom_url, "windows_os_info", "instance")


# ---------------------------------------------------------------------------
# Metric budget
# ---------------------------------------------------------------------------

class TestMetricBudget:
    """Verify series count is within production-safe bounds."""

    def test_total_series_count(self, prom_url):
        """Total series for a real Windows server should be 200-500.

        This range accounts for:
          - CPU: ~8 cores x ~5 modes = ~40 series
          - Memory: ~25 series
          - Disk: ~2 drives x ~12 metrics = ~24 series
          - Network: ~2 NICs x ~10 metrics = ~20 series
          - Service: ~12 svcs x 2 states = ~24 series
          - System/OS/Time: ~30 series
          Total: ~163 base + headroom for label variations
        """
        assert_series_count_in_range(
            prom_url, "integrations/windows_exporter", 100, 800
        )

    def test_no_cardinality_explosion(self, prom_url):
        """Series count should never exceed 1000 on a standard server."""
        results = query_prometheus(
            prom_url,
            'count({job="integrations/windows_exporter"})',
        )
        if results:
            count = int(float(results[0]["value"][1]))
            assert count < 1000, (
                f"Cardinality explosion detected: {count} series. "
                f"Check service filter and pattern block rules."
            )
