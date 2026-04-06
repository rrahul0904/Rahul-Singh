from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / 'apps' / 'api' / 'data'
OUTPUT = Path(__file__).resolve().parents[1] / 'stateful-data-export.json'


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bundle: dict[str, object] = {}
    for path in sorted(DATA_DIR.glob('*.json')):
        raw = path.read_text(encoding='utf-8').strip() or '[]'
        try:
            bundle[path.name] = json.loads(raw)
        except json.JSONDecodeError:
            bundle[path.name] = raw
    OUTPUT.write_text(json.dumps(bundle, indent=2), encoding='utf-8')
    print(f'Wrote {OUTPUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
