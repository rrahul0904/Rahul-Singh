# Final Verification Guide

## Goal
Use this guide to confirm that the current product shell is not only present in the repo, but also behaves coherently.

## API verification
1. Run the integrated shell:
   - `uvicorn apps.api.app.main_integrated:app --host 0.0.0.0 --port 8001`
2. Run the stateful shell:
   - `uvicorn apps.api.app.main_stateful_phase2:app --host 0.0.0.0 --port 8003`
3. Run automated tests:
   - `pytest apps/api/tests`

## Browser verification
1. Open `/product-home`
2. Open `/operating-center`
3. Walk through `/project-control-plane`, `/discovery`, `/conversion`, `/validation`, `/workspace`
4. Open `/stateful-lab`
5. Open `/stateful-actions`
6. Open `/demo-readiness`

## Persistence verification
1. Create a project through the stateful API or stateful actions page.
2. Save a query through the stateful API or stateful actions page.
3. Re-check list routes and confirm the new records are present.

## Current conclusion
The product shell is now broad, navigable, and verifiable. The main remaining work is incremental polish rather than missing major modules.
