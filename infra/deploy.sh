#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# UMA Platform — Cloud Deployment Scripts
# AWS EKS · Azure AKS · GCP GKE · Air-gapped
# ═══════════════════════════════════════════════════════════════

set -e

REGISTRY="${REGISTRY:-your-registry}"
VERSION="${VERSION:-latest}"

# ─── Build & Push Images ──────────────────────────────────────
build_images() {
  echo "Building UMA images..."
  docker build -t ${REGISTRY}/uma-api:${VERSION} ./backend
  docker build -t ${REGISTRY}/uma-frontend:${VERSION} ./frontend
  docker push ${REGISTRY}/uma-api:${VERSION}
  docker push ${REGISTRY}/uma-frontend:${VERSION}
  echo "✅ Images pushed"
}

# ══════════════════════════════════════════════════════════════
# AWS EKS Deployment
# ══════════════════════════════════════════════════════════════
deploy_eks() {
  CLUSTER_NAME="${1:-uma-prod}"
  REGION="${2:-us-east-1}"

  echo "Deploying to EKS: ${CLUSTER_NAME} in ${REGION}"

  # Update kubeconfig
  aws eks update-kubeconfig --name ${CLUSTER_NAME} --region ${REGION}

  # Create ECR repos if needed
  aws ecr describe-repositories --repository-names uma-api 2>/dev/null || \
    aws ecr create-repository --repository-name uma-api --region ${REGION}
  aws ecr describe-repositories --repository-names uma-frontend 2>/dev/null || \
    aws ecr create-repository --repository-name uma-frontend --region ${REGION}

  ECR_REGISTRY=$(aws ecr get-login-password --region ${REGION} | \
    docker login --username AWS --password-stdin \
    $(aws sts get-caller-identity --query Account --output text).dkr.ecr.${REGION}.amazonaws.com && \
    echo $(aws sts get-caller-identity --query Account --output text).dkr.ecr.${REGION}.amazonaws.com)

  REGISTRY=${ECR_REGISTRY} build_images

  # Apply manifests
  sed -i "s|your-registry|${ECR_REGISTRY}|g" infra/k8s/base/deployment.yaml
  kubectl apply -f infra/k8s/base/deployment.yaml

  # EKS-specific: ALB Ingress Controller
  kubectl apply -f infra/k8s/overlays/aws/alb-ingress.yaml 2>/dev/null || true

  # Create EBS StorageClass for Postgres
  kubectl apply -f - <<EOF
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: uma-ebs
  namespace: uma
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
reclaimPolicy: Retain
allowVolumeExpansion: true
EOF

  echo "✅ EKS deployment complete"
  kubectl get pods -n uma
}

# ══════════════════════════════════════════════════════════════
# Azure AKS Deployment
# ══════════════════════════════════════════════════════════════
deploy_aks() {
  RESOURCE_GROUP="${1:-uma-rg}"
  CLUSTER_NAME="${2:-uma-aks}"
  ACR_NAME="${3:-umacr}"

  echo "Deploying to AKS: ${CLUSTER_NAME}"

  # Login and get credentials
  az aks get-credentials --resource-group ${RESOURCE_GROUP} --name ${CLUSTER_NAME}
  az acr login --name ${ACR_NAME}

  ACR_SERVER="${ACR_NAME}.azurecr.io"
  REGISTRY=${ACR_SERVER} build_images

  # Attach ACR to AKS
  az aks update -n ${CLUSTER_NAME} -g ${RESOURCE_GROUP} \
    --attach-acr ${ACR_NAME} 2>/dev/null || true

  sed -i "s|your-registry|${ACR_SERVER}|g" infra/k8s/base/deployment.yaml
  kubectl apply -f infra/k8s/base/deployment.yaml

  # AKS-specific: Azure Disk StorageClass
  kubectl apply -f - <<EOF
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: uma-azure-disk
  namespace: uma
provisioner: disk.csi.azure.com
parameters:
  skuName: Premium_LRS
  kind: Managed
reclaimPolicy: Retain
allowVolumeExpansion: true
EOF

  echo "✅ AKS deployment complete"
  kubectl get pods -n uma
}

# ══════════════════════════════════════════════════════════════
# GCP GKE Deployment
# ══════════════════════════════════════════════════════════════
deploy_gke() {
  PROJECT_ID="${1:-your-project}"
  CLUSTER_NAME="${2:-uma-gke}"
  ZONE="${3:-us-central1-a}"

  echo "Deploying to GKE: ${CLUSTER_NAME}"

  gcloud container clusters get-credentials ${CLUSTER_NAME} \
    --zone ${ZONE} --project ${PROJECT_ID}

  GCR_REGISTRY="gcr.io/${PROJECT_ID}"
  gcloud auth configure-docker gcr.io
  REGISTRY=${GCR_REGISTRY} build_images

  sed -i "s|your-registry|${GCR_REGISTRY}|g" infra/k8s/base/deployment.yaml
  kubectl apply -f infra/k8s/base/deployment.yaml

  # GKE-specific: Persistent disk
  kubectl apply -f - <<EOF
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: uma-ssd
  namespace: uma
provisioner: pd.csi.storage.gke.io
parameters:
  type: pd-ssd
reclaimPolicy: Retain
allowVolumeExpansion: true
EOF

  echo "✅ GKE deployment complete"
  kubectl get pods -n uma
}

# ══════════════════════════════════════════════════════════════
# Air-gapped / Restricted Enterprise Mode
# ══════════════════════════════════════════════════════════════
deploy_airgapped() {
  PRIVATE_REGISTRY="${1:-your-private-registry.company.com}"
  echo "Deploying in air-gapped mode..."

  # Override external AI calls — use internal LLM endpoint
  kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: uma-airgapped-config
  namespace: uma
data:
  AIRGAPPED_MODE: "true"
  ANTHROPIC_API_KEY: ""
  INTERNAL_LLM_ENDPOINT: "http://internal-llm-service:8080/v1/messages"
  INTERNAL_LLM_MODEL: "internal-model"
  # Disable external dependencies
  DISABLE_EXTERNAL_AI: "true"
  DISABLE_TELEMETRY: "true"
EOF

  # Use private registry
  sed -i "s|your-registry|${PRIVATE_REGISTRY}|g" infra/k8s/base/deployment.yaml

  # Network policy — block external egress except to known endpoints
  kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: uma-network-policy
  namespace: uma
spec:
  podSelector: {}
  policyTypes:
  - Egress
  - Ingress
  egress:
  # Allow internal cluster communication
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: uma
  # Allow DNS
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
  # Allow Snowflake (configure your Snowflake account CIDR)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0  # Restrict to Snowflake IPs in production
    ports:
    - port: 443
      protocol: TCP
  ingress:
  - from:
    - namespaceSelector: {}
EOF

  kubectl apply -f infra/k8s/base/deployment.yaml
  echo "✅ Air-gapped deployment complete"
}

# ══════════════════════════════════════════════════════════════
# Usage
# ══════════════════════════════════════════════════════════════
case "${1}" in
  eks)       deploy_eks "${2}" "${3}" ;;
  aks)       deploy_aks "${2}" "${3}" "${4}" ;;
  gke)       deploy_gke "${2}" "${3}" "${4}" ;;
  airgapped) deploy_airgapped "${2}" ;;
  build)     build_images ;;
  *)
    echo "UMA Platform Deployment Tool"
    echo ""
    echo "Usage:"
    echo "  ./deploy.sh eks      <cluster-name> <region>           # AWS EKS"
    echo "  ./deploy.sh aks      <resource-group> <cluster> <acr>  # Azure AKS"
    echo "  ./deploy.sh gke      <project-id> <cluster> <zone>     # GCP GKE"
    echo "  ./deploy.sh airgapped <private-registry>               # Air-gapped"
    echo "  ./deploy.sh build                                       # Build images only"
    ;;
esac
