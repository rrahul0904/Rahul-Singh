# Smoke Test Playbook

## Integrated API shell
Run:

```bash
uvicorn apps.api.app.main_integrated:app --host 0.0.0.0 --port 8001
```

Check:

```bash
curl http://localhost:8001/health
curl http://localhost:8001/api/v1/projects
curl http://localhost:8001/api/v1/discovery/runs
curl http://localhost:8001/api/v1/conversion/items
curl http://localhost:8001/api/v1/validation/runs
curl http://localhost:8001/api/v1/workspace/queries
```

## Stateful API shell
Run:

```bash
uvicorn apps.api.app.main_stateful_phase2:app --host 0.0.0.0 --port 8003
```

Check:

```bash
curl http://localhost:8003/health
curl http://localhost:8003/api/stateful/v1/projects
curl http://localhost:8003/api/stateful/v1/discovery/runs
curl http://localhost:8003/api/stateful/v1/conversion/items
curl http://localhost:8003/api/stateful/v1/validation/runs
curl http://localhost:8003/api/stateful/v1/workspace/queries
```

## Stateful write checks

```bash
curl -X POST http://localhost:8003/api/stateful/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke Test Project","description":"Created from smoke test","source_platform":"Oracle","target_platform":"Snowflake","owner":"Rahul"}'

curl -X POST http://localhost:8003/api/stateful/v1/workspace/queries \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke_test_query","sql_text":"SELECT region, occupancy_rate FROM mart_occupancy","owner":"Rahul"}'
```
