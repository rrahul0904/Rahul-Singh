# Stateful UI Runbook

## Purpose
This runbook covers the browser-facing routes that sit on top of the persistence-backed API shell.

## Key routes
- `/operating-center`
- `/stateful-lab`
- `/workspace`
- `/project-control-plane`
- `/discovery`
- `/conversion`
- `/validation`

## Environment hint
Set `NEXT_PUBLIC_STATEFUL_API_BASE_URL` to the stateful API host when wiring browser-side write actions to the persistent endpoints.

Example:

```bash
NEXT_PUBLIC_STATEFUL_API_BASE_URL=http://localhost:8003
```

## Current scope
The stateful lab page documents the persistent routes and pairs with `apps/web/lib/statefulClient.ts` for richer write-action wiring.
