#!/bin/bash
# Build all Docker images for Kubernetes deployment
# This script handles the correct build contexts for each Dockerfile

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_header() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Check if running from project root
if [ ! -f "pyproject.toml" ]; then
    print_error "Must be run from project root directory"
    exit 1
fi

# Detect if we're in Minikube, kind, or k3d
DOCKER_ENV=""
if command -v minikube &> /dev/null && minikube status &> /dev/null; then
    print_info "Detected Minikube - switching to Minikube Docker daemon"
    eval $(minikube docker-env)
    DOCKER_ENV="minikube"
elif docker context show 2>/dev/null | grep -q "kind"; then
    print_info "Detected kind context"
    DOCKER_ENV="kind"
elif command -v k3d &> /dev/null && k3d cluster list 2>/dev/null | grep -q "api-forge"; then
    print_info "Detected k3d cluster"
    DOCKER_ENV="k3d"
else
    print_info "Building images for local Docker daemon"
    DOCKER_ENV="local"
fi

print_header "Building Docker Images for Kubernetes"

# Build PostgreSQL image
print_info "Building PostgreSQL image..."
cd infra/docker/prod
docker build \
    -f postgres/Dockerfile \
    -t app_data_postgres_image:latest \
    . 2>&1 | grep -E "(Step|Successfully|Error)" || true
BUILD_STATUS=${PIPESTATUS[0]}
cd ../../..

if [ $BUILD_STATUS -eq 0 ]; then
    print_success "PostgreSQL image built successfully"
else
    print_error "Failed to build PostgreSQL image"
    exit 1
fi

# Build Redis image
print_info "Building Redis image..."
cd infra/docker/prod/redis
docker build \
    -f Dockerfile \
    -t app_data_redis_image:latest \
    . 2>&1 | grep -E "(Step|Successfully|Error)" || true
BUILD_STATUS=${PIPESTATUS[0]}
cd ../../../..

if [ $BUILD_STATUS -eq 0 ]; then
    print_success "Redis image built successfully"
else
    print_error "Failed to build Redis image"
    exit 1
fi

# Build Temporal image
print_info "Building Temporal image..."
cd infra/docker/prod/temporal
docker build \
    -f Dockerfile \
    -t my-temporal-server:1.29.0 \
    . 2>&1 | grep -E "(Step|Successfully|Error)" || true
BUILD_STATUS=${PIPESTATUS[0]}
cd ../../../..

if [ $BUILD_STATUS -eq 0 ]; then
    print_success "Temporal image built successfully"
else
    print_error "Failed to build Temporal image"
    exit 1
fi

# Build FastAPI application image
print_info "Building FastAPI application image..."
docker build \
    -f Dockerfile \
    -t api-forge-app:latest \
    . 2>&1 | grep -E "(Step|Successfully|Error)" || true
BUILD_STATUS=${PIPESTATUS[0]}

if [ $BUILD_STATUS -eq 0 ]; then
    print_success "FastAPI application image built successfully"
else
    print_error "Failed to build FastAPI application image"
    exit 1
fi

print_header "Build Summary"

# List built images
print_info "Verifying images..."
echo ""

IMAGES=(
    "app_data_postgres_image:latest"
    "app_data_redis_image:latest"
    "my-temporal-server:1.29.0"
    "api-forge-app:latest"
)

ALL_FOUND=true
for IMAGE in "${IMAGES[@]}"; do
    if docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${IMAGE}$"; then
        print_success "$IMAGE"
    else
        print_error "$IMAGE not found"
        ALL_FOUND=false
    fi
done

echo ""

if [ "$ALL_FOUND" = true ]; then
    print_success "All images built successfully!"
    
    # Load images into kind/k3d if needed
    if [ "$DOCKER_ENV" = "kind" ]; then
        print_header "Loading images into kind cluster"
        CLUSTER_NAME="api-forge"
        for IMAGE in "${IMAGES[@]}"; do
            print_info "Loading $IMAGE..."
            kind load docker-image "$IMAGE" --name "$CLUSTER_NAME" 2>&1 | grep -v "Image.*already present" || true
        done
        print_success "Images loaded into kind cluster"
    elif [ "$DOCKER_ENV" = "k3d" ]; then
        print_header "Loading images into k3d cluster"
        CLUSTER_NAME="api-forge"
        for IMAGE in "${IMAGES[@]}"; do
            print_info "Loading $IMAGE..."
            k3d image import "$IMAGE" -c "$CLUSTER_NAME" 2>&1 | grep -v "already exists" || true
        done
        print_success "Images loaded into k3d cluster"
    elif [ "$DOCKER_ENV" = "minikube" ]; then
        print_info "Images already available in Minikube's Docker daemon"
    fi
    
    echo ""
    print_header "Next Steps"
    echo "1. Generate secrets (if not already done):"
    echo "   cd infra/secrets && ./generate_secrets.sh && cd ../.."
    echo ""
    echo "2. Apply Kubernetes secrets (after filling infra/secrets/user-provided.env):"
    echo "   ./k8s/scripts/apply-secrets.sh"
    echo ""
    echo "3. Deploy to Kubernetes (choose one):"
    echo ""
    echo "   Option A - Full automated deployment (recommended):"
    echo "   ./k8s/scripts/deploy-resources.sh"
    echo "   (Syncs configs, deploys all resources, waits for health checks)"
    echo ""
    echo "   Option B - Manual step-by-step:"
    echo "   ./k8s/scripts/deploy-config.sh    # Sync configs and deploy ConfigMaps"
    echo "   kubectl apply -k k8s/base/        # Deploy remaining resources"
    echo "   kubectl get pods,jobs -n api-forge-prod -w"
    echo ""
    echo "4. Verify application health:"
    echo "   kubectl port-forward -n api-forge-prod svc/app 8000:8000 &"
    echo "   curl http://localhost:8000/health/ready | jq"
    echo ""
else
    print_error "Some images failed to build. Check errors above."
    exit 1
fi
