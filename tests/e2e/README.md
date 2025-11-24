# End-to-End Tests

Comprehensive E2E tests that validate the complete workflow from Copier template generation to production deployment.

## Test Coverage

### `test_copier_to_deployment.py`

Full end-to-end workflow testing:

1. **test_01_copier_generation** - Generate project from Copier template
2. **test_02_unified_replacement_validation** - Verify all `src.*` references replaced with project name
3. **test_03_python_dependencies_install** - Install dependencies with `uv sync`
4. **test_04_cli_functional** - Verify CLI commands work
5. **test_05_python_imports** - Test Python imports use correct module names
6. **test_06_secrets_generation** - Generate secrets including PKI certificates
7. **test_07_docker_compose_prod_deployment** - Deploy to Docker Compose production
8. **test_08_kubernetes_deployment** - Deploy to Kubernetes (requires cluster)
9. **test_09_file_replacement_statistics** - Verify unified replacement processed all files

## Running Tests

### Quick Start

```bash
# Run all E2E tests (excludes slow deployment tests)
pytest tests/e2e/ -v

# Run specific test
pytest tests/e2e/test_copier_to_deployment.py::TestCopierToDeployment::test_01_copier_generation -v -s

# Run with deployment tests (slow)
pytest tests/e2e/ -v -s --run-slow

# Run Kubernetes tests (requires cluster)
pytest tests/e2e/ -v -s --run-slow -m k8s
```

### Using the Helper Script

```bash
# Run all tests with verbose output
./tests/e2e/run_e2e_tests.sh

# Run only fast tests (skip deployments)
./tests/e2e/run_e2e_tests.sh --fast

# Run with Docker Compose deployment
./tests/e2e/run_e2e_tests.sh --docker

# Run with Kubernetes deployment
./tests/e2e/run_e2e_tests.sh --k8s

# Run everything including deployments
./tests/e2e/run_e2e_tests.sh --all
```

## Prerequisites

### Required
- Python 3.13+
- `uv` package manager
- `copier` CLI tool
- `pytest`

### Optional (for deployment tests)
- Docker and Docker Compose (for test_07)
- Kubernetes cluster + `kubectl` (for test_08)

## Test Markers

Tests are marked with pytest markers for selective execution:

- `@pytest.mark.slow` - Tests that take >30 seconds (deployments)
- `@pytest.mark.k8s` - Tests that require Kubernetes cluster

## Configuration

### pytest.ini

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "k8s: marks tests that require Kubernetes cluster",
]
addopts = "-v --tb=short"
```

### Environment Variables

None required - tests use temporary directories and clean up after themselves.

### Secrets Handling in Tests

Tests handle OIDC secrets securely without requiring interactive prompts:

**Production Pattern (Manual Setup)**:
- Users run `uv run api-forge-cli secrets generate --pki`
- Script prompts for OIDC client secrets interactively
- Secrets stored in `infra/secrets/keys/oidc_*_client_secret.txt`

**Test Pattern (Automated)**:
- Tests provide OIDC secrets via CLI flags to avoid prompts
- Example: `--oidc-google-secret test-google-secret-e2e`
- This ensures tests run non-interactively in CI/CD
- Test secrets are clearly marked with `-e2e` suffix

**Why Not .env Files?**:
- `.env.example` no longer contains OIDC secret placeholders
- This forces users to consciously provide real credentials
- Prevents accidental deployment with insecure defaults
- Tests use CLI flags instead of environment variables for explicit control

## Test Output

Tests include verbose output showing:
- Commands being executed
- Working directories
- Command output (first 500 chars)
- Progress indicators
- Validation results

Example output:
```
================================================================================
TEST 1: Copier Generation
================================================================================

🔧 Running: copier copy --force --answers-file - /path/to/template /tmp/e2e_test_xyz/e2e_test_project
   Working directory: /tmp/e2e_test_xyz
📤 stdout:
Copying...
✅ Project generated at: /tmp/e2e_test_xyz/e2e_test_project

================================================================================
TEST 2: Unified Replacement Validation
================================================================================

✅ e2e_test_project/app/worker/registry.py: All src.* replaced with e2e_test_project.*
✅ k8s/base/deployments/worker.yaml: All src.* replaced with e2e_test_project.*
✅ docker-compose.prod.yml: All src.* replaced with e2e_test_project.*
✅ Dockerfile: All src.* replaced with e2e_test_project.*

✅ All critical files validated
```

## Troubleshooting

### Copier generation fails
- Ensure `copier` is installed: `pip install copier`
- Check template directory path is correct

### Docker Compose deployment fails
- Ensure Docker is running: `docker info`
- Check ports are available (5432, 6379, 7233, 8000)
- Verify secrets were generated in test_06

### Kubernetes deployment fails
- Verify cluster is accessible: `kubectl cluster-info`
- Ensure namespace doesn't already exist: `kubectl get namespace api-forge-prod`
- Check you have permissions to create resources

### Tests hang or timeout
- Increase timeout values in test code
- Check for port conflicts
- Review container logs: `docker ps` / `kubectl logs`

## CI/CD Integration

### GitHub Actions Example

```yaml
name: E2E Tests

on: [push, pull_request]

jobs:
  e2e-fast:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v1
      - name: Install dependencies
        run: |
          pip install copier pytest
          uv sync --dev
      - name: Run fast E2E tests
        run: pytest tests/e2e/ -v -m "not slow"

  e2e-docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v1
      - name: Install dependencies
        run: |
          pip install copier pytest
          uv sync --dev
      - name: Run Docker Compose E2E tests
        run: pytest tests/e2e/ -v -m "slow and not k8s"

  e2e-k8s:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v1
      - name: Setup Minikube
        uses: medyagh/setup-minikube@latest
      - name: Install dependencies
        run: |
          pip install copier pytest
          uv sync --dev
      - name: Run Kubernetes E2E tests
        run: pytest tests/e2e/ -v -m "k8s"
```

## Test Cleanup

Tests automatically clean up after themselves:
- Temporary project directories are deleted
- Docker containers are stopped and removed (`--volumes`)
- Kubernetes namespace is deleted

If tests are interrupted, manual cleanup may be needed:
```bash
# Clean up Docker
docker-compose -f /tmp/e2e_test_*/*/docker-compose.prod.yml down -v

# Clean up Kubernetes
kubectl delete namespace api-forge-prod --wait=true
```

## Contributing

When adding new E2E tests:

1. Follow the numbered test naming convention (`test_01_`, `test_02_`, etc.)
2. Add descriptive docstrings
3. Use `@pytest.mark.slow` for tests >30 seconds
4. Use `@pytest.mark.k8s` for Kubernetes-specific tests
5. Include verbose output with print statements
6. Clean up resources in `finally` blocks
7. Update this README with new test descriptions
