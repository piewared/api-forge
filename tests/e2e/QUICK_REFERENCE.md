# E2E Testing Quick Reference

## TL;DR

```bash
# Fast validation (1 minute)
./tests/e2e/run_e2e_tests.sh --fast

# With Docker Compose (5 minutes)
./tests/e2e/run_e2e_tests.sh --docker

# With Kubernetes (8 minutes)
./tests/e2e/run_e2e_tests.sh --k8s

# Everything (10 minutes)
./tests/e2e/run_e2e_tests.sh --all
```

## What Gets Tested

| ✅ Component | Test | What It Validates |
|-------------|------|-------------------|
| Template | Copier generation | Project structure, files created |
| Replacement | Unified src.* → pkg.* | 80+ files, all patterns replaced |
| Dependencies | uv sync | Installs correctly |
| CLI | --help commands | All commands available |
| Imports | Python imports | No ModuleNotFoundError |
| Secrets | PKI generation | Certs, passwords created |
| Docker | docker-compose up | All containers healthy |
| K8s | kubectl apply | All pods running, jobs passed |
| Stats | File counts | Expected coverage |

## Quick Pytest Commands

```bash
# All fast tests
pytest tests/e2e/ -v -m "not slow"

# Specific test
pytest tests/e2e/test_copier_to_deployment.py::TestCopierToDeployment::test_02_unified_replacement_validation -v -s

# Docker only
pytest tests/e2e/ -v -k "docker"

# K8s only
pytest tests/e2e/ -v -m "k8s"

# With coverage
pytest tests/e2e/ -v --cov=scripts --cov-report=html
```

## When to Run

| Situation | Command | Why |
|-----------|---------|-----|
| **Changing post_gen_setup.py** | `--fast` | Validates replacement logic |
| **Modifying Docker configs** | `--docker` | Tests Docker Compose deployment |
| **Changing K8s manifests** | `--k8s` | Tests Kubernetes deployment |
| **Before committing** | `--all` | Full validation |
| **CI/CD** | GitHub Actions | Automatic on push/PR |

## Expected Results

### Fast Tests (6 tests, ~50 seconds)
```
✅ test_01_copier_generation
✅ test_02_unified_replacement_validation  
✅ test_03_python_dependencies_install
✅ test_04_cli_functional
✅ test_05_python_imports
✅ test_06_secrets_generation
✅ test_09_file_replacement_statistics
```

### Docker Test (+1 test, ~2 minutes)
```
✅ test_07_docker_compose_prod_deployment
   ✓ 5 containers running (app, worker, postgres, redis, temporal)
   ✓ Health check passes
```

### K8s Test (+1 test, ~3 minutes)
```
✅ test_08_kubernetes_deployment
   ✓ 7 deployments (app, worker, postgres, redis, temporal, temporal-web, temporal-admin-tools)
   ✓ 3 jobs completed (postgres-verifier, temporal-schema-setup, temporal-namespace-init)
   ✓ Worker using correct module: {package_name}.worker.main
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `copier not found` | `pip install copier` |
| `Docker daemon not running` | `sudo systemctl start docker` |
| `kubectl not found` | `brew install kubectl` (Mac) or apt/yum |
| `Cluster not accessible` | `kubectl cluster-info` to verify |
| `Port already in use` | Check: `netstat -tlnp \| grep -E '5432\|6379\|8000'` |
| Tests hang | Check Docker/K8s resources, review logs |

## CI/CD Status

GitHub Actions runs 3 jobs in parallel:
- **e2e-fast**: ~5-10 minutes
- **e2e-docker**: ~15-20 minutes  
- **e2e-kubernetes**: ~20-30 minutes

Check status: `.github/workflows/e2e-tests.yml`

## Files

```
tests/e2e/
├── test_copier_to_deployment.py    # 560+ lines of tests
├── run_e2e_tests.sh                # Bash runner script
└── README.md                        # Full documentation

.github/workflows/
└── e2e-tests.yml                    # CI/CD workflow

docs/
└── E2E_TESTING_SUMMARY.md           # Complete summary
```

## Test Output Example

```
================================================================================
TEST 2: Unified Replacement Validation
================================================================================

✅ e2e_test_project/app/worker/registry.py: All src.* replaced with e2e_test_project.*
✅ k8s/base/deployments/worker.yaml: All src.* replaced with e2e_test_project.*
✅ docker-compose.prod.yml: All src.* replaced with e2e_test_project.*
✅ Dockerfile: All src.* replaced with e2e_test_project.*

✅ All critical files validated
```

## Need More Info?

- Full docs: `tests/e2e/README.md`
- Complete summary: `docs/E2E_TESTING_SUMMARY.md`
- Test code: `tests/e2e/test_copier_to_deployment.py`
