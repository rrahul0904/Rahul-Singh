# Demo Readiness Checklist

## Objective
Use this checklist to get the Unified Migration Accelerator into a coherent demo state quickly.

## API entrypoints
- [ ] Integrated API shell: `apps/api/app/main_integrated.py`
- [ ] Stateful API shell: `apps/api/app/main_stateful_phase2.py`
- [ ] Health endpoint responds successfully

## Frontend routes
- [ ] `/operating-center`
- [ ] `/project-control-plane`
- [ ] `/project-control-plane/new`
- [ ] `/project-control-plane/[projectId]`
- [ ] `/discovery`
- [ ] `/conversion`
- [ ] `/validation`
- [ ] `/workspace`
- [ ] `/stateful-lab`

## Demo story flow
- [ ] Open Operating Center
- [ ] Navigate to Project Control Plane
- [ ] Show project detail and inventory
- [ ] Navigate to Discovery dashboard
- [ ] Navigate to Conversion Workbench
- [ ] Navigate to Validation
- [ ] Navigate to Workspace
- [ ] Show stateful lab and persistent API examples

## Persistence checks
- [ ] Create project through stateful route
- [ ] Save query through stateful route
- [ ] Restart service and confirm records remain in JSON files

## Remaining polish
- [ ] Replace more placeholder seeded flows
- [ ] Add richer frontend forms against stateful routes
- [ ] Run integrated smoke test
