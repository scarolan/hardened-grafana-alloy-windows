"""Tier 1 tests: Docker-based validation of Alloy relabeling pipeline for Windows.

These tests validate:
  - Allow-list correctness (Layer 1)
  - Service cardinality filter (Layer 2)
  - Pattern block rules (Layer 3)
  - Label validation tagging (Layer 4)
  - Label value limits (Layer 5)
  - Standard label presence (instance, job)

NOTE: The Windows exporter cannot run on Linux, so these tests use synthetic
metrics served by a fixture server. Real Windows exporter testing is in Tier 2.

Run via: docker compose run test-runner
"""

import os
import sys
import pytest

# Add shared test utilities to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))

from shared.assertions import (
    query_prometheus,
    get_all_metric_names,
    assert_metric_exists,
    assert_metric_absent,
    assert_label_present,
    assert_label_value,
    assert_no_label,
    assert_series_count_in_range,
    wait_for_metric,
)
from shared.metrics_allowlist import ALLOWLIST

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def wait_for_scrape():
    """Wait until Alloy has scraped and pushed at least one cycle of data."""
    print(f"\nWaiting for metrics to appear in Prometheus at {PROMETHEUS_URL}...")
    # Wait for a metric we know the fixture server produces
    wait_for_metric(PROMETHEUS_URL, "windows_system_processes", timeout=180, interval=5)
    # Also wait for clean CPU metrics
    wait_for_metric(PROMETHEUS_URL, "windows_cpu_time_total", timeout=60, interval=5)
    print("Metrics available, running tests.")


# ---------------------------------------------------------------------------
# Layer 1: Allow-list
# ---------------------------------------------------------------------------

class TestAllowList:
    """Verify the allow-list keeps required metrics and drops everything else."""

    @pytest.mark.parametrize("metric", [
        "up",
        "windows_cpu_time_total",
        "windows_cpu_core_frequency_mhz",
        "windows_memory_physical_total_bytes",
        "windows_memory_physical_free_bytes",
        "windows_memory_available_bytes",
        "windows_memory_commit_limit",
        "windows_logical_disk_size_bytes",
        "windows_logical_disk_free_bytes",
        "windows_net_bytes_received_total",
        "windows_net_bytes_sent_total",
        "windows_net_current_bandwidth_bytes",
        "windows_system_processes",
        "windows_system_threads",
        "windows_system_context_switches_total",
        "windows_system_system_up_time",
        "windows_os_info",
        "windows_os_visible_memory_bytes",
    ])
    def test_core_metrics_present(self, metric):
        """Core metrics required by dashboard 24390 must be present."""
        assert_metric_exists(PROMETHEUS_URL, metric)

    @pytest.mark.parametrize("metric", [
        "windows_process_cpu_time_total",
        "windows_process_private_bytes",
        "some_random_custom_metric",
        "another_unknown_metric",
    ])
    def test_non_allowlisted_metrics_absent(self, metric):
        """Metrics not on the allow-list must be dropped (Layer 1)."""
        assert_metric_absent(PROMETHEUS_URL, metric)

    def test_all_metrics_are_allowlisted(self):
        """Every metric name in Prometheus should be in the allow-list."""
        present = get_all_metric_names(PROMETHEUS_URL)
        unexpected = present - ALLOWLIST
        assert not unexpected, (
            f"Found {len(unexpected)} metrics not in allow-list: {sorted(unexpected)}"
        )


# ---------------------------------------------------------------------------
# Layer 2: Service cardinality filter
# ---------------------------------------------------------------------------

class TestServiceCardinalityFilter:
    """Verify service metrics are filtered to monitored services + desired states."""

    def test_monitored_service_running_kept(self):
        """Monitored services with running state must be kept."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_service_state{name="windefend",state="running"}',
        )
        assert len(results) > 0, "windefend running should be kept"

    def test_monitored_service_stopped_kept(self):
        """Monitored services with stopped state must be kept."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_service_state{name="windefend",state="stopped"}',
        )
        assert len(results) > 0, "windefend stopped should be kept"

    def test_non_monitored_service_dropped(self):
        """Non-monitored services must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_service_state{name="spooler"}',
        )
        assert len(results) == 0, (
            f"Non-monitored service 'spooler' should be dropped, found: "
            f"{[r['metric'] for r in results]}"
        )

    def test_non_monitored_service_wbiosrvc_dropped(self):
        """Another non-monitored service must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_service_state{name="wbiosrvc"}',
        )
        assert len(results) == 0, "Non-monitored service 'wbiosrvc' should be dropped"

    def test_non_desired_state_dropped(self):
        """Monitored services with non-desired states must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_service_state{name="windefend",state="start_pending"}',
        )
        assert len(results) == 0, "start_pending state should be dropped"

    def test_alloy_service_kept(self):
        """The alloy service itself should be monitored."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_service_state{name="alloy",state="running"}',
        )
        assert len(results) > 0, "alloy service running should be kept"

    def test_multiple_monitored_services(self):
        """Multiple monitored services should be present."""
        for svc in ["windefend", "alloy", "winrm", "w32time"]:
            results = query_prometheus(
                PROMETHEUS_URL,
                f'windows_service_state{{name="{svc}"}}',
            )
            assert len(results) > 0, f"Monitored service '{svc}' should be present"


# ---------------------------------------------------------------------------
# Layer 3: Cardinality protection (pattern block)
# ---------------------------------------------------------------------------

class TestCardinalityProtection:
    """Verify high-churn patterns are dropped."""

    def test_virtual_nics_dropped(self):
        """isatap, Teredo, vEthernet, 6to4, WFP interfaces must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_net_bytes_received_total{nic=~".*(isatap|Teredo|vEthernet|6to4|WFP).*"}',
        )
        assert len(results) == 0, (
            f"Virtual NIC metrics should be dropped, found: "
            f"{[r['metric'].get('nic') for r in results]}"
        )

    def test_hidden_volumes_dropped(self):
        """HarddiskVolume metrics must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_logical_disk_size_bytes{volume=~".*HarddiskVolume.*"}',
        )
        assert len(results) == 0, (
            f"HarddiskVolume metrics should be dropped, found: "
            f"{[r['metric'].get('volume') for r in results]}"
        )

    def test_guid_volume_dropped(self):
        """Metrics with GUID patterns in volume label must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            '{volume=~".*[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}.*"}',
        )
        assert len(results) == 0, (
            f"GUID-volume metrics should be dropped, found: "
            f"{[r['metric'].get('volume') for r in results]}"
        )

    def test_total_disk_pseudo_instance_dropped(self):
        """_Total pseudo-instance for logical disk must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_logical_disk_size_bytes{volume="_Total"}',
        )
        assert len(results) == 0, "_Total disk pseudo-instance should be dropped"

    def test_total_net_pseudo_instance_dropped(self):
        """_Total pseudo-instance for network must be dropped."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_net_bytes_received_total{nic="_Total"}',
        )
        assert len(results) == 0, "_Total network pseudo-instance should be dropped"


# ---------------------------------------------------------------------------
# Layer 4: Label validation (quality_warning tagging)
# ---------------------------------------------------------------------------

class TestLabelValidation:
    """Verify metrics missing required labels are TAGGED, not dropped."""

    def test_disk_missing_volume_tagged(self):
        """Logical disk metrics without volume get quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_logical_disk_size_bytes{quality_warning="missing_required_labels"}',
        )
        assert len(results) > 0, (
            "Expected logical disk metrics missing volume to be tagged"
        )

    def test_network_missing_nic_tagged(self):
        """Network metrics without nic get quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_net_bytes_received_total{quality_warning="missing_required_labels"}',
        )
        assert len(results) > 0, (
            "Expected network metrics missing nic to be tagged"
        )

    def test_cpu_missing_core_tagged(self):
        """CPU metrics without core label get quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_cpu_time_total{quality_warning="missing_required_labels"}',
        )
        assert len(results) > 0, (
            "Expected CPU metrics missing core label to be tagged"
        )

    def test_clean_metrics_not_tagged(self):
        """Properly-labeled metrics should NOT have quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_logical_disk_size_bytes{volume="C:"}',
        )
        for r in results:
            assert "quality_warning" not in r["metric"], (
                f"Clean metric should not be tagged: {r['metric']}"
            )

    def test_clean_cpu_not_tagged(self):
        """CPU metrics with core label should NOT have quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_cpu_time_total{core="0"}',
        )
        assert len(results) > 0, "Expected core=0 metrics from fixtures"
        for r in results:
            assert "quality_warning" not in r["metric"], (
                f"Clean CPU metric should not be tagged: {r['metric']}"
            )

    def test_clean_network_not_tagged(self):
        """Network metrics with nic label should NOT have quality_warning."""
        results = query_prometheus(
            PROMETHEUS_URL,
            'windows_net_bytes_received_total{nic="Intel(R) Ethernet Connection"}',
        )
        assert len(results) > 0, "Expected real NIC metrics from fixtures"
        for r in results:
            assert "quality_warning" not in r["metric"], (
                f"Clean network metric should not be tagged: {r['metric']}"
            )


# ---------------------------------------------------------------------------
# Standard labels
# ---------------------------------------------------------------------------

class TestStandardLabels:
    """Verify instance and job labels are applied consistently."""

    def test_job_label(self):
        """All metrics should have job='integrations/windows_exporter'."""
        assert_label_value(
            PROMETHEUS_URL, "windows_system_processes", "job", "integrations/windows_exporter"
        )

    def test_instance_label(self):
        """All metrics should have an instance label."""
        assert_label_present(PROMETHEUS_URL, "windows_system_processes", "instance")

    def test_no_empty_instance(self):
        """Instance label should not be empty."""
        results = query_prometheus(PROMETHEUS_URL, 'windows_system_processes{instance=""}')
        assert len(results) == 0, "Instance label should not be empty"


# ---------------------------------------------------------------------------
# Metric budget sanity check
# ---------------------------------------------------------------------------

class TestMetricBudget:
    """Verify total series count is within expected bounds."""

    def test_total_series_count(self):
        """Total series should be within reasonable bounds for synthetic data.

        Synthetic fixture data produces fewer series than a real Windows host.
        Lower bound is intentionally low. Upper bound catches cardinality explosions.
        """
        assert_series_count_in_range(
            PROMETHEUS_URL, "integrations/windows_exporter", 10, 2000
        )

    def test_allowlist_parse_sanity(self):
        """The parsed allow-list should have a reasonable number of metrics."""
        assert len(ALLOWLIST) >= 70, (
            f"Allow-list only has {len(ALLOWLIST)} metrics, expected >= 70"
        )
        assert len(ALLOWLIST) <= 120, (
            f"Allow-list has {len(ALLOWLIST)} metrics, expected <= 120 (check for bloat)"
        )
