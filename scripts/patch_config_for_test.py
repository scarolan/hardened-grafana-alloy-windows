#!/usr/bin/env python3
"""Patch config.alloy for test environments.

Rewrites the production config to:
- Remove the Windows exporter block (can't run on Linux)
- Remove the discovery.relabel and prometheus.scrape that reference it
- Point remote_write at a local Prometheus
- Remove auth requirements
- Remove Windows Event Log collection (can't run on Linux)
- Inject a synthetic metrics scrape job that feeds through the relabeling pipeline
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "config.alloy"
DST = REPO_ROOT / "tests" / "tier1" / "config.alloy.test"


def patch():
    config = SRC.read_text()

    # --- Replace Prometheus remote_write endpoint ---
    config = config.replace(
        'url = sys.env("GRAFANA_METRICS_URL")',
        'url = "http://prometheus:9090/api/v1/write"',
    )

    # Remove metrics auth block
    config = re.sub(
        r'(endpoint\s*\{[^}]*url\s*=\s*"http://prometheus:9090/api/v1/write"\s*\n)'
        r'\s*basic_auth\s*\{[^}]*\}\s*\n',
        r'\1',
        config,
    )

    # --- Replace Loki endpoint with a blackhole ---
    config = config.replace(
        'url = sys.env("GRAFANA_LOGS_URL")',
        'url = "http://localhost:3100/loki/api/v1/push"',
    )
    # Remove Loki auth
    config = re.sub(
        r'(url\s*=\s*"http://localhost:3100/loki/api/v1/push"\s*\n)'
        r'\s*basic_auth\s*\{[^}]*\}\s*\n',
        r'\1',
        config,
    )

    # --- Remove Windows-specific blocks that can't run on Linux ---
    # Use a helper to remove blocks with nested braces
    def remove_section(text, header_pattern, block_start_pattern):
        """Remove a section starting with a header comment and a block with nested braces."""
        pattern = header_pattern + block_start_pattern
        match = re.search(pattern, text)
        if not match:
            return text
        start = match.start()
        # Find the end of the block by counting braces
        brace_start = text.index('{', match.end() - 1)
        depth = 0
        i = brace_start
        while i < len(text):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    # Skip trailing newlines
                    end = i + 1
                    while end < len(text) and text[end] == '\n':
                        end += 1
                    return text[:start] + text[end:]
            i += 1
        return text

    # Remove discovery.relabel block (references windows exporter)
    config = remove_section(
        config,
        r'// -{60,}\n// TARGET DISCOVERY\n// -{60,}\n',
        r'discovery\.relabel',
    )

    # Remove prometheus.exporter.windows block
    config = remove_section(
        config,
        r'// -{60,}\n// WINDOWS EXPORTER\n// -{60,}\n',
        r'prometheus\.exporter\.windows',
    )

    # Remove prometheus.scrape block (references windows exporter targets)
    config = remove_section(
        config,
        r'// -{60,}\n// SCRAPE\n// -{60,}\n',
        r'prometheus\.scrape',
    )

    # Remove Windows Event Log collection (everything after LOG COLLECTION header)
    config = re.sub(
        r'// -{60,}\n// LOG COLLECTION \(Windows Event Log\)\n// -{60,}\n.*',
        '',
        config,
        flags=re.DOTALL,
    )

    # --- Add synthetic metrics scrape job ---
    synthetic_block = '''
// ---------------------------------------------------------------------------
// TEST ONLY: Synthetic metrics scrape for relabeling rule validation
// ---------------------------------------------------------------------------
discovery.relabel "synthetic_test" {
\ttargets = [{
\t\t__address__ = "fixture-server:9999",
\t}]
\trule {
\t\ttarget_label = "instance"
\t\treplacement  = constants.hostname
\t}
\trule {
\t\ttarget_label = "job"
\t\treplacement  = "integrations/windows_exporter"
\t}
}

prometheus.scrape "synthetic_test" {
\ttargets         = discovery.relabel.synthetic_test.output
\tforward_to      = [prometheus.relabel.integrations_windows_exporter.receiver]
\tscrape_interval = "15s"
}
'''
    config += "\n" + synthetic_block

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(config)
    print(f"Patched config written to {DST}")


if __name__ == "__main__":
    patch()
