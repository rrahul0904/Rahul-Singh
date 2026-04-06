# Operations

## Running both API shells with Docker Compose

```bash
docker compose -f docker-compose.shells.yml up
```

This brings up:
- integrated API shell on `http://localhost:8001`
- stateful API shell on `http://localhost:8003`

## Recommended local flow
1. Start the shells with compose or the Makefile.
2. Run `make test-api`.
3. Run `make check-routes`.
4. Open `/product-home` and `/operating-center` in the web app.

## Notes
- The compose file is aimed at quick local verification rather than optimized production deployment.
- The stateful shell writes JSON-backed records for its persistent module areas.
