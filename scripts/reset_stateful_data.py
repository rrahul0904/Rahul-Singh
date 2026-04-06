from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / 'apps' / 'api' / 'data'
FILES = [
    'projects.json',
    'inventory.json',
    'workspace_queries.json',
    'discovery_runs.json',
    'discovery_results.json',
    'conversion_items.json',
    'validation_runs.json',
    'validation_results.json',
]


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = DATA_DIR / name
        path.write_text('[]', encoding='utf-8')
        print(f'Reset {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
