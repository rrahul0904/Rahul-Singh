# Demo Deployment Runbook

## Local Docker

Build the image:

```bash
docker build -f docker/Dockerfile -t unified-migration-accelerator:demo .
```

Run the image:

```bash
docker run --rm -p 8000:8000 \
  -e APP_TITLE="Unified Data Migration Accelerator" \
  -e APP_ENV="docker-demo" \
  -e APP_VERSION="0.1.0" \
  unified-migration-accelerator:demo
```

Or use Compose:

```bash
docker compose -f docker-compose.demo.yml up --build
```

Open `http://localhost:8000`.

## Kubernetes

Build and push your image first, then update the image in `k8s/deployment.yaml` if required.

Apply manifests:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
```

Check rollout:

```bash
kubectl -n unified-migration-accelerator rollout status deployment/unified-migration-accelerator
```

Port-forward for quick demo access:

```bash
kubectl -n unified-migration-accelerator port-forward svc/unified-migration-accelerator 8000:80
```

Open `http://localhost:8000`.

## Demo endpoints

- `/`
- `/health`
- `/api/summary`
- `/api/projects`
- `/api/inventory`
- `/api/conversions`
- `/api/validation`
- `/api/generate-sql`
- `/api/query`
