# State Tools

## Reset local stateful data

```bash
python3 scripts/reset_stateful_data.py
```

This clears the JSON-backed state files under `apps/api/data` so a local demo can start fresh.

## Export local stateful data

```bash
python3 scripts/export_stateful_data.py
```

This writes a combined `stateful-data-export.json` snapshot at the repository root.

## When to use these
- before a fresh demo run
- after smoke tests that created temporary records
- when you want to inspect the current JSON-backed state quickly
