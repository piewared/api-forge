#!/usr/bin/env bash
#
# End-to-End Test Runner
#
# Usage:
#   ./tests/e2e/run_e2e_tests.sh [OPTIONS]
#
# Options:
#   --fast         Run only fast tests (skip deployments)
#   --docker       Run tests including Docker Compose deployment
#   --k8s          Run tests including Kubernetes deployment
#   --all          Run all tests including all deployments
#   --help         Show this help message
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default options
RUN_FAST_ONLY=false
RUN_DOCKER=false
RUN_K8S=false
RUN_ALL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --fast)
            RUN_FAST_ONLY=true
            shift
            ;;
        --docker)
            RUN_DOCKER=true
            shift
            ;;
        --k8s)
            RUN_K8S=true
            shift
            ;;
        --all)
            RUN_ALL=true
            shift
            ;;
        --help|-h)
            echo "End-to-End Test Runner"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --fast         Run only fast tests (skip deployments)"
            echo "  --docker       Run tests including Docker Compose deployment"
            echo "  --k8s          Run tests including Kubernetes deployment"
            echo "  --all          Run all tests including all deployments"
            echo "  --help         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --fast                # Quick validation tests"
            echo "  $0 --docker              # Include Docker Compose deployment"
            echo "  $0 --k8s                 # Include Kubernetes deployment"
            echo "  $0 --all                 # Run everything"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# If no options specified, default to fast tests
if [[ "$RUN_FAST_ONLY" == false && "$RUN_DOCKER" == false && "$RUN_K8S" == false && "$RUN_ALL" == false ]]; then
    RUN_FAST_ONLY=true
fi

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         FastAPI Template - End-to-End Test Suite              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Check Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}❌ Python not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python: $(python --version)${NC}"

# Check uv
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ uv not found - install with: pip install uv${NC}"
    exit 1
fi
echo -e "${GREEN}✅ uv: $(uv --version)${NC}"

# Check copier
if ! command -v copier &> /dev/null; then
    echo -e "${RED}❌ copier not found - install with: pip install copier${NC}"
    exit 1
fi
echo -e "${GREEN}✅ copier: $(copier --version)${NC}"

# Check pytest
if ! python -c "import pytest" 2>/dev/null; then
    echo -e "${RED}❌ pytest not found - install with: pip install pytest${NC}"
    exit 1
fi
echo -e "${GREEN}✅ pytest: $(python -c 'import pytest; print(pytest.__version__)')${NC}"

# Check Docker (if needed)
if [[ "$RUN_DOCKER" == true || "$RUN_ALL" == true ]]; then
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker not found (required for --docker)${NC}"
        exit 1
    fi
    if ! docker info &> /dev/null; then
        echo -e "${RED}❌ Docker daemon not running${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Docker: $(docker --version)${NC}"
fi

# Check kubectl (if needed)
if [[ "$RUN_K8S" == true || "$RUN_ALL" == true ]]; then
    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}❌ kubectl not found (required for --k8s)${NC}"
        exit 1
    fi
    if ! kubectl cluster-info &> /dev/null; then
        echo -e "${YELLOW}⚠️  Kubernetes cluster not accessible - K8s tests will be skipped${NC}"
    else
        echo -e "${GREEN}✅ kubectl: $(kubectl version --client --short)${NC}"
    fi
fi

echo ""

# Build pytest command
cd "$PROJECT_ROOT"

PYTEST_CMD="pytest tests/e2e/test_copier_to_deployment.py -v -s --tb=short"

if [[ "$RUN_FAST_ONLY" == true ]]; then
    echo -e "${BLUE}Running fast tests only (no deployments)...${NC}"
    PYTEST_CMD="$PYTEST_CMD -m 'not slow'"
elif [[ "$RUN_DOCKER" == true ]]; then
    echo -e "${BLUE}Running tests with Docker Compose deployment...${NC}"
    PYTEST_CMD="$PYTEST_CMD -m 'not k8s'"
elif [[ "$RUN_K8S" == true ]]; then
    echo -e "${BLUE}Running tests with Kubernetes deployment...${NC}"
    # Run all tests including K8s
    :
elif [[ "$RUN_ALL" == true ]]; then
    echo -e "${BLUE}Running all tests (including all deployments)...${NC}"
    # Run everything - no marker filtering
    :
fi

echo ""
echo -e "${YELLOW}Test command: $PYTEST_CMD${NC}"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Run tests
set +e
$PYTEST_CMD
TEST_EXIT_CODE=$?
set -e

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Report results
if [[ $TEST_EXIT_CODE -eq 0 ]]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Tests failed with exit code: $TEST_EXIT_CODE${NC}"
    echo ""
    echo -e "${YELLOW}Troubleshooting tips:${NC}"
    echo "  • Check test output above for specific failures"
    echo "  • Ensure all prerequisites are installed"
    echo "  • For deployment tests, check Docker/K8s are running"
    echo "  • Review tests/e2e/README.md for more information"
    echo ""
    exit $TEST_EXIT_CODE
fi
