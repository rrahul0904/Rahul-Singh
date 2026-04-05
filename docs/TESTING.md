# Testing Notes

## Automated API tests

Run from the repository root:

```bash
pytest apps/api/tests
```

## Covered shells
- `apps/api/app/main_integrated.py`
- `apps/api/app/main_stateful_phase2.py`

## Current scope
The current tests verify that the key integrated and stateful API routes respond successfully and return JSON payloads.

## Next expansion
- add tests for POST routes
- add persistence assertions for stateful records
- add frontend-level tests later
