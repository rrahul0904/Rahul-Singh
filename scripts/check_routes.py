from __future__ import annotations

import sys
import urllib.request

INTEGRATED = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
STATEFUL = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8003"

CHECKS = {
    "integrated": [
        f"{INTEGRATED}/health",
        f"{INTEGRATED}/api/v1/projects",
        f"{INTEGRATED}/api/v1/discovery/runs",
        f"{INTEGRATED}/api/v1/conversion/items",
        f"{INTEGRATED}/api/v1/validation/runs",
        f"{INTEGRATED}/api/v1/workspace/queries",
    ],
    "stateful": [
        f"{STATEFUL}/health",
        f"{STATEFUL}/api/stateful/v1/projects",
        f"{STATEFUL}/api/stateful/v1/discovery/runs",
        f"{STATEFUL}/api/stateful/v1/conversion/items",
        f"{STATEFUL}/api/stateful/v1/validation/runs",
        f"{STATEFUL}/api/stateful/v1/workspace/queries",
    ],
}

for group, urls in CHECKS.items():
    print(f"\n## {group}")
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                print(f"PASS {url} -> {response.status}")
        except Exception as exc:
            print(f"FAIL {url} -> {exc}")
