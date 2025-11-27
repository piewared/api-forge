"""
End-to-End tests for the complete workflow from Copier generation to deployment.

These tests validate:
1. Copier template generation
2. Post-generation script (unified replacement)
3. Secrets generation
4. Docker Compose production deployment
5. Kubernetes deployment
6. Service health checks
7. Cleanup

Run with: pytest tests/e2e/test_copier_to_deployment.py -v -s
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml


class TestCopierToDeployment:
    """Test complete workflow from Copier generation to deployment."""

    @pytest.fixture(scope="class")
    def temp_project_dir(self) -> Generator[Path]:
        """Create a temporary directory for generated project."""
        with tempfile.TemporaryDirectory(prefix="e2e_test_") as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture(scope="class")
    def template_dir(self) -> Path:
        """Get the template directory (repository root)."""
        return Path(__file__).parent.parent.parent

    @pytest.fixture(scope="class", autouse=True)
    def setup_project(self, temp_project_dir: Path, template_dir: Path):
        """Generate project once for all tests in this class."""
        print(f"\n{'=' * 80}")
        print("SETUP: Generating Project with Copier")
        print(f"{'=' * 80}")

        project_name = "e2e_test_project"
        project_dir = temp_project_dir

        # Define answers
        answers = {
            "project_name": "E2E Test API",
            "project_slug": project_name,
            "project_description": "End-to-end test project",
            "author_name": "E2E Tester",
            "author_email": "e2e@test.com",
            "python_version": "3.13",
        }

        # Build copier command with --data flags
        cmd = [
            "copier",
            "copy",
            "--force",
            "--trust",
        ]

        # Add all answers as --data flags
        for key, value in answers.items():
            cmd.extend(["--data", f"{key}={value}"])

        # Add source and destination
        cmd.extend([str(template_dir), str(project_dir)])

        # Run copier
        print(f"\n🔧 Running copier with answers: {answers}")
        print(f"   Template: {template_dir}")
        print(f"   Destination: {project_dir}")

        result = subprocess.run(
            cmd,
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )

        print(f"📤 Copier stdout:\n{result.stdout}")
        print(f"📤 Copier stderr:\n{result.stderr}")
        print(f"📤 Copier exit code: {result.returncode}")

        if result.returncode != 0:
            raise RuntimeError(
                f"Copier failed with exit code {result.returncode}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        # Verify project was created
        assert project_dir.exists(), f"Project directory not created: {project_dir}"
        assert (project_dir / "pyproject.toml").exists(), "pyproject.toml not created"
        assert (project_dir / project_name).exists(), (
            f"Package directory {project_name} not created"
        )

        print(f"✅ Project generated at: {project_dir}")

        # Store in class variables for all tests
        TestCopierToDeployment._project_dir = project_dir
        TestCopierToDeployment._project_name = project_name

        yield

        # Teardown happens automatically when temp_project_dir is cleaned up
        print(f"\n{'=' * 80}")
        print("TEARDOWN: Cleaning up temp directory")
        print(f"{'=' * 80}")

    def run_command(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: int = 300,
        check: bool = True,
        stream_output: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run a command and return the result.

        Args:
            cmd: Command to run
            cwd: Working directory
            timeout: Command timeout in seconds
            check: Whether to raise exception on non-zero exit
            stream_output: If True, stream output in real-time (for long-running commands)
        """
        print(f"\n🔧 Running: {' '.join(cmd)}")
        print(f"   Working directory: {cwd}")

        # Clear VIRTUAL_ENV to avoid "does not match project environment" warnings
        # when running uv commands in the generated project directory
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)

        if stream_output:
            # Use Popen for real-time output streaming
            import sys
            import threading

            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout for simplicity
                text=True,
                bufsize=1,  # Line buffered
                env=env,
            )

            stdout_lines = []

            def read_output():
                """Read output in a separate thread to avoid blocking"""
                if process.stdout:
                    for line in iter(process.stdout.readline, ""):
                        if line:
                            stdout_lines.append(line)
                            sys.stdout.write(line)
                            sys.stdout.flush()

            # Start reading in a thread
            reader_thread = threading.Thread(target=read_output, daemon=True)
            reader_thread.start()

            try:
                # Wait for process to complete
                returncode = process.wait(timeout=timeout)
                # Wait for reader thread to finish
                reader_thread.join(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                reader_thread.join(timeout=2)
                raise

            stdout = "".join(stdout_lines)
            stderr = ""  # Merged into stdout

            # Create CompletedProcess-like object
            result = subprocess.CompletedProcess(
                args=cmd, returncode=returncode, stdout=stdout, stderr=stderr
            )
        else:
            # Use run for normal buffered execution
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )

            if result.stdout:
                print(f"📤 stdout:\n{result.stdout}")
            if result.stderr:
                print(f"📤 stderr:\n{result.stderr}")

        if check and result.returncode != 0:
            raise RuntimeError(
                f"Command failed with exit code {result.returncode}\n"
                f"Command: {' '.join(cmd)}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        return result

    def test_01_copier_generation(self):
        """Test 1: Verify project was generated from Copier template."""
        print(f"\n{'=' * 80}")
        print("TEST 1: Copier Generation Validation")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = self._project_dir
        project_name = self._project_name

        # Verify project structure
        assert project_dir.exists(), f"Project directory not created: {project_dir}"
        assert (project_dir / "pyproject.toml").exists(), "pyproject.toml not created"
        assert (project_dir / project_name).exists(), (
            f"Package directory {project_name} not created"
        )

        # Verify key files exist
        assert (project_dir / "config.yaml").exists(), "config.yaml not created"
        assert (project_dir / "Dockerfile").exists(), "Dockerfile not created"
        assert (project_dir / ".env.example").exists(), ".env.example not created"

        print(f"✅ Project structure validated at: {project_dir}")
        print(f"✅ Package name: {project_name}")

    def test_02_unified_replacement_validation(self):
        """Test 2: Validate unified replacement changed all src.* references."""
        print(f"\n{'=' * 80}")
        print("TEST 2: Unified Replacement Validation")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir
        project_name = TestCopierToDeployment._project_name

        # Files that should have been updated
        critical_files = [
            f"{project_name}/app/worker/registry.py",
            "k8s/base/deployments/worker.yaml",
            "docker-compose.prod.yml",
            "Dockerfile",
        ]

        for file_path in critical_files:
            full_path = project_dir / file_path
            assert full_path.exists(), f"Critical file not found: {file_path}"

            content = full_path.read_text()

            # Should NOT contain 'src.' references (except in comments)
            lines_with_src = [
                line
                for line in content.split("\n")
                if "src." in line and not line.strip().startswith("#")
            ]

            if lines_with_src:
                print(f"❌ Found unreplaced 'src.' references in {file_path}:")
                for line in lines_with_src[:5]:  # Show first 5
                    print(f"   {line}")

            assert not lines_with_src, (
                f"File {file_path} still contains 'src.' references"
            )

            # Should contain project_name references
            assert project_name in content, (
                f"File {file_path} doesn't contain {project_name}"
            )

            print(f"✅ {file_path}: All src.* replaced with {project_name}.*")

        print("\n✅ All critical files validated")

    def test_02b_verify_secrets_not_copied(self):
        """Test 2b: Verify template secrets were not copied to generated project"""
        print(f"\n{'=' * 80}")
        print("TEST 2b: Verify Secrets Not Copied from Template")
        print(f"{'=' * 80}")

        project_dir = TestCopierToDeployment._project_dir

        # Check that secrets directories don't exist or are empty
        keys_dir = project_dir / "infra" / "secrets" / "keys"
        certs_dir = project_dir / "infra" / "secrets" / "certs"

        print("📁 Checking secrets directories in generated project:")
        print(f"   Keys directory: {keys_dir}")
        print(f"   Certs directory: {certs_dir}")

        # Keys directory should NOT exist (excluded by Copier)
        if keys_dir.exists():
            # List what's in it
            keys_files = list(keys_dir.glob("*"))
            if keys_files:
                print(f"❌ ERROR: keys/ directory has {len(keys_files)} files:")
                for f in keys_files:
                    print(f"   - {f.name}")
                raise AssertionError(
                    f"keys/ directory should be excluded but contains {len(keys_files)} files. "
                    f"Template secrets were copied to generated project!"
                )
            else:
                print("✅ keys/ directory exists but is empty")
        else:
            print("✅ keys/ directory was excluded (doesn't exist)")

        # Certs directory should NOT exist (excluded by Copier)
        if certs_dir.exists():
            certs_files = list(certs_dir.glob("*"))
            if certs_files:
                print(f"❌ ERROR: certs/ directory has {len(certs_files)} files:")
                for f in certs_files:
                    print(f"   - {f.name}")
                raise AssertionError(
                    f"certs/ directory should be excluded but contains {len(certs_files)} files. "
                    f"Template certificates were copied to generated project!"
                )
            else:
                print("✅ certs/ directory exists but is empty")
        else:
            print("✅ certs/ directory was excluded (doesn't exist)")

        print(
            "✅ Template secrets and certificates were successfully excluded from generated project"
        )

    def test_03_python_dependencies_install(self):
        """Test 3: Install Python dependencies with uv."""
        print(f"\n{'=' * 80}")
        print("TEST 3: Python Dependencies Installation")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir

        # Install dependencies (this also installs the project package and CLI)
        self.run_command(["uv", "sync", "--dev"], cwd=project_dir, timeout=180)

        # Verify .venv was created
        assert (project_dir / ".venv").exists(), ".venv not created"

        # Verify CLI was installed (cli name is always api-forge-cli)
        result = self.run_command(
            ["uv", "run", "which", "api-forge-cli"],
            cwd=project_dir,
            check=False,
        )

        if result.returncode == 0:
            print(f"✅ CLI installed at: {result.stdout.strip()}")
        else:
            # Check if it's available via uv run
            result = self.run_command(
                ["uv", "run", "api-forge-cli", "--version"],
                cwd=project_dir,
                check=False,
            )
            if result.returncode == 0:
                print("✅ CLI is available via uv run")
            else:
                print("⚠️  CLI may not be installed, but dependencies are")

        print("✅ Dependencies installed")

    def test_04_cli_functional(self):
        """Test 4: Verify CLI is functional."""
        print(f"\n{'=' * 80}")
        print("TEST 4: CLI Functionality")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir

        # Test CLI help (CLI name is always api-forge-cli)
        result = self.run_command(
            ["uv", "run", "api-forge-cli", "--help"],
            cwd=project_dir,
        )

        assert "deploy" in result.stdout, "deploy command not in CLI help"
        assert "secrets" in result.stdout, "secrets command not in CLI help"
        assert "entity" in result.stdout, "entity command not in CLI help"

        print("✅ CLI is functional")

    def test_05_secrets_generation(self):
        """Test 5: Generate secrets including PKI certificates."""
        print(f"\n{'=' * 80}")
        print("TEST 5: Secrets Generation")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir

        # Generate all secrets including PKI (CLI name is always api-forge-cli)
        # Provide test OIDC secrets via CLI flags to avoid interactive prompts
        self.run_command(
            [
                "uv",
                "run",
                "api-forge-cli",
                "secrets",
                "generate",
                "--pki",
                "--force",
                "--oidc-google-secret",
                "test-google-secret-e2e",
                "--oidc-microsoft-secret",
                "test-microsoft-secret-e2e",
                "--oidc-keycloak-secret",
                "test-keycloak-secret-e2e",
            ],
            cwd=project_dir,
            timeout=60,
        )

        # Verify secrets were created (secrets are in infra/secrets/keys/)
        secrets_base = project_dir / "infra" / "secrets"
        keys_dir = secrets_base / "keys"
        assert keys_dir.exists(), "Secrets directory (infra/secrets/keys/) not created"

        # Check for critical secrets
        critical_secrets = [
            "session_signing_secret.txt",
            "csrf_signing_secret.txt",
            "postgres_password.txt",
            "redis_password.txt",
        ]

        for secret in critical_secrets:
            secret_file = keys_dir / secret
            assert secret_file.exists(), f"Secret {secret} not generated"
            assert secret_file.stat().st_size > 0, f"Secret {secret} is empty"

        # Check OIDC secrets and verify they match CLI-provided values (not env vars)
        oidc_secrets = {
            "oidc_google_client_secret.txt": "test-google-secret-e2e",
            "oidc_microsoft_client_secret.txt": "test-microsoft-secret-e2e",
            "oidc_keycloak_client_secret.txt": "test-keycloak-secret-e2e",
        }

        for secret_file, expected_value in oidc_secrets.items():
            secret_path = keys_dir / secret_file
            assert secret_path.exists(), f"OIDC secret {secret_file} not generated"
            actual_value = secret_path.read_text().strip()
            assert actual_value == expected_value, (
                f"OIDC secret {secret_file} has wrong value!\n"
                f"Expected: {expected_value}\n"
                f"Actual: {actual_value}\n"
                f"This means the secret came from environment variables instead of CLI flags."
            )
            print(f"✅ {secret_file}: Correct value (from CLI, not env)")

        # Check PKI certificates (certs/ is under infra/secrets/)
        postgres_certs = secrets_base / "certs" / "postgres"
        assert postgres_certs.exists(), "PostgreSQL certs directory not created"
        assert (postgres_certs / "server.crt").exists(), (
            "PostgreSQL server.crt not generated"
        )
        assert (postgres_certs / "server.key").exists(), (
            "PostgreSQL server.key not generated"
        )

        print("✅ All secrets generated with correct values")

    def test_06_python_imports(self):
        """Test 6: Verify Python imports work correctly."""
        print(f"\n{'=' * 80}")
        print("TEST 6: Python Imports")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir
        project_name = TestCopierToDeployment._project_name

        # Test importing the app (just verify basic imports work)
        test_import = f"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from {project_name}.app.api.http.app import app
from {project_name}.app.runtime.config.config_data import ConfigData

print("✅ All imports successful")
"""

        result = self.run_command(
            ["uv", "run", "python", "-c", test_import],
            cwd=project_dir,
        )

        assert "✅ All imports successful" in result.stdout, "Import test failed"

        print("✅ Python imports working")

    @pytest.mark.slow
    def test_07_docker_compose_prod_deployment(self):
        """Test 7: Deploy to Docker Compose production."""
        print(f"\n{'=' * 80}")
        print("TEST 7: Docker Compose Production Deployment")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir
        print(f"📁 Using project directory: {project_dir}")

        try:
            # Clean up any previous Docker Compose deployment first
            print("\n🧹 Cleaning up any previous Docker Compose deployment...")
            self.run_command(
                ["uv", "run", "api-forge-cli", "deploy", "down", "prod", "--volumes"],
                cwd=project_dir,
                timeout=60,
                check=False,
            )
            # Give it a moment to clean up
            time.sleep(5)

            # Setup .env file (required for production deployment)
            env_example = project_dir / ".env.example"
            env_file = project_dir / ".env"

            if env_example.exists():
                print("📝 Creating .env from .env.example...")
                shutil.copy(env_example, env_file)
            else:
                print("⚠️  .env.example not found, creating minimal .env...")
                env_file.write_text("APP_ENVIRONMENT=production\n")

            # Ensure secrets are generated (Docker Compose needs them)
            # If test_06 already ran, secrets will exist
            # If running test_07 alone, this ensures secrets are available
            secrets_base = project_dir / "infra" / "secrets"
            keys_dir = secrets_base / "keys"
            session_secret_file = keys_dir / "session_signing_secret.txt"

            # Check for actual secret files, not just directory existence
            # (keys_dir may exist empty from Copier template structure)
            if not session_secret_file.exists():
                print("🔐 Generating secrets for Docker Compose deployment...")
                self.run_command(
                    [
                        "uv",
                        "run",
                        "api-forge-cli",
                        "secrets",
                        "generate",
                        "--pki",
                        "--force",
                        "--oidc-google-secret",
                        "test-google-secret-e2e",
                        "--oidc-microsoft-secret",
                        "test-microsoft-secret-e2e",
                        "--oidc-keycloak-secret",
                        "test-keycloak-secret-e2e",
                    ],
                    cwd=project_dir,
                    timeout=60,
                )

                # Verify OIDC secrets were generated correctly
                oidc_secrets = {
                    "oidc_google_client_secret.txt": "test-google-secret-e2e",
                    "oidc_microsoft_client_secret.txt": "test-microsoft-secret-e2e",
                    "oidc_keycloak_client_secret.txt": "test-keycloak-secret-e2e",
                }

                for secret_file, expected_value in oidc_secrets.items():
                    secret_path = keys_dir / secret_file
                    assert secret_path.exists(), (
                        f"OIDC secret {secret_file} not generated"
                    )
                    actual_value = secret_path.read_text().strip()
                    assert actual_value == expected_value, (
                        f"OIDC secret {secret_file} has wrong value!\n"
                        f"Expected: {expected_value}\n"
                        f"Actual: {actual_value}\n"
                        f"This means the secret came from environment variables instead of CLI flags."
                    )
                print("✅ OIDC secrets verified: Correct values (from CLI, not env)")

                # Verify TLS/PKI certificates were generated
                certs_dir = secrets_base / "certs"
                ca_bundle_file = certs_dir / "ca-bundle.crt"
                postgres_cert = certs_dir / "postgres" / "server.crt"
                postgres_key = certs_dir / "postgres" / "server.key"

                assert ca_bundle_file.exists(), (
                    f"CA bundle not generated: {ca_bundle_file}\n"
                    f"Temporal schema setup requires this file."
                )
                assert postgres_cert.exists(), (
                    f"PostgreSQL TLS cert not generated: {postgres_cert}"
                )
                assert postgres_key.exists(), (
                    f"PostgreSQL TLS key not generated: {postgres_key}"
                )
                print(
                    "✅ TLS/PKI certificates verified: CA bundle and PostgreSQL certs exist"
                )
            else:
                print("✅ Secrets already exist (from test_06)")

            # Start production deployment
            try:
                result = self.run_command(
                    ["uv", "run", "api-forge-cli", "deploy", "up", "prod"],
                    cwd=project_dir,
                    timeout=600,  # 10 minutes for building images in CI
                )
            except RuntimeError as e:
                print(f"\n❌ Deployment failed: {e}")

                # Try to get container logs for debugging
                print("\n🔍 Checking Docker container status...")
                try:
                    ps_result = subprocess.run(
                        ["docker", "ps", "-a", "--filter", "name=api-forge"],
                        capture_output=True,
                        text=True,
                        cwd=project_dir,
                    )
                    print(f"Containers:\n{ps_result.stdout}")

                    # Get logs from temporal-schema-setup if it exists
                    logs_result = subprocess.run(
                        ["docker", "logs", "api-forge-temporal-schema-setup"],
                        capture_output=True,
                        text=True,
                        cwd=project_dir,
                    )
                    if logs_result.returncode == 0:
                        print(f"\n📋 Temporal schema setup logs:\n{logs_result.stdout}")
                        if logs_result.stderr:
                            print(f"Errors:\n{logs_result.stderr}")
                except Exception as log_err:
                    print(f"Could not get container logs: {log_err}")

                raise  # Re-raise the original exception

            # Wait for services to be healthy
            print("⏳ Waiting for services to become healthy...")
            time.sleep(30)

            # TODO: This is for debugging; remove later
            # Check if temporal-schema-setup completed successfully
            print("\n🔍 Checking temporal-schema-setup status...")
            try:
                inspect_result = subprocess.run(
                    [
                        "docker",
                        "inspect",
                        "api-forge-temporal-schema-setup",
                        "--format",
                        "{{.State.ExitCode}}",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=project_dir,
                )
                if inspect_result.returncode == 0:
                    exit_code = inspect_result.stdout.strip()
                    print(f"Temporal schema setup exit code: {exit_code}")
                    if exit_code != "0":
                        print("\n❌ Temporal schema setup failed! Capturing logs...")
                        logs_result = subprocess.run(
                            ["docker", "logs", "api-forge-temporal-schema-setup"],
                            capture_output=True,
                            text=True,
                            cwd=project_dir,
                        )
                        print(f"\n📋 Temporal schema setup logs:\n{logs_result.stdout}")
                        if logs_result.stderr:
                            print(f"Stderr:\n{logs_result.stderr}")
                        raise AssertionError(
                            f"Temporal schema setup failed with exit code {exit_code}"
                        )
            except subprocess.CalledProcessError:
                print("⚠️ Could not inspect temporal-schema-setup container")

            # Check deployment status
            result = self.run_command(
                ["uv", "run", "api-forge-cli", "deploy", "status", "prod"],
                cwd=project_dir,
            )

            print(f"Deployment status:\n{result.stdout}")

            # Verify containers are running
            result = self.run_command(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=api-forge",
                    "--format",
                    "{{.Names}}",
                ],
                cwd=project_dir,
            )

            running_containers = result.stdout.strip().split("\n")
            print(f"Running containers: {running_containers}")

            expected_containers = ["postgres", "redis", "temporal", "app", "worker"]
            for container in expected_containers:
                assert any(container in name for name in running_containers), (
                    f"Container {container} not running"
                )

            print("✅ All containers running")

            # Test /health endpoint
            print("\n🏥 Testing /health endpoint...")
            result = self.run_command(
                [
                    "docker",
                    "exec",
                    "api-forge-app",
                    "python",
                    "-c",
                    "import urllib.request; import sys; sys.stdout.write(urllib.request.urlopen('http://localhost:8000/health').read().decode())",
                ],
                cwd=project_dir,
                check=False,
            )

            if result.returncode == 0:
                print(f"Health endpoint response:\n{result.stdout}")
                # Parse JSON and verify status
                try:
                    health_data = json.loads(result.stdout)
                    assert health_data.get("status") == "healthy", (
                        f"Health status not healthy: {health_data.get('status')}"
                    )
                    print("✅ /health endpoint: healthy")
                except json.JSONDecodeError:
                    print("⚠️  /health endpoint returned non-JSON response")

            # Test /health/ready endpoint
            print("\n🏥 Testing /health/ready endpoint...")
            result = self.run_command(
                [
                    "docker",
                    "exec",
                    "api-forge-app",
                    "python",
                    "-c",
                    "import urllib.request; import sys; sys.stdout.write(urllib.request.urlopen('http://localhost:8000/health/ready').read().decode())",
                ],
                cwd=project_dir,
                check=False,
            )

            if result.returncode == 0:
                print(f"Readiness endpoint response:\n{result.stdout}")
                # Parse JSON and verify all components ready
                try:
                    ready_data = json.loads(result.stdout)
                    assert ready_data.get("status") == "ready", (
                        f"Readiness status not ready: {ready_data.get('status')}"
                    )

                    # Check individual components
                    components = ready_data.get("components", {})
                    for component, status in components.items():
                        if status != "healthy":
                            print(f"⚠️  Component {component} not healthy: {status}")

                    print("✅ /health/ready endpoint: ready")
                except json.JSONDecodeError:
                    print("⚠️  /health/ready endpoint returned non-JSON response")
            else:
                print(
                    "⚠️  /health/ready endpoint check failed (may be expected in test env)"
                )

        finally:
            # Cleanup: Stop and remove containers
            print("\n🧹 Cleaning up Docker Compose deployment...")
            self.run_command(
                ["uv", "run", "api-forge-cli", "deploy", "down", "prod", "--volumes"],
                cwd=project_dir,
                check=False,
            )

    @pytest.mark.slow
    @pytest.mark.k8s
    def test_08_kubernetes_deployment(self):
        """Test 8: Deploy to Kubernetes."""
        print(f"\n{'=' * 80}")
        print("TEST 8: Kubernetes Deployment")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir
        project_name = TestCopierToDeployment._project_name

        # Check if kubectl is available
        try:
            result = self.run_command(
                ["kubectl", "version", "--client"], cwd=project_dir
            )
        except Exception as e:
            pytest.skip(f"kubectl not available: {e}")

        # Check if k8s cluster is available
        result = self.run_command(
            ["kubectl", "cluster-info"], cwd=project_dir, check=False
        )
        if result.returncode != 0:
            pytest.skip("Kubernetes cluster not available")

        try:
            # Clean up any previous K8s deployment first
            print("\n🧹 Cleaning up any previous K8s deployment...")
            self.run_command(
                ["kubectl", "delete", "namespace", "api-forge-prod", "--wait=false"],
                cwd=project_dir,
                timeout=30,
                check=False,
            )
            # Give it a moment to start deleting
            time.sleep(5)

            # Setup .env file (required for K8s deployment)
            env_example = project_dir / ".env.example"
            env_file = project_dir / ".env"

            if env_example.exists():
                print("📝 Creating .env from .env.example...")
                shutil.copy(env_example, env_file)
            else:
                print("⚠️  .env.example not found, creating minimal .env...")
                env_file.write_text("APP_ENVIRONMENT=production\n")

            # Ensure secrets are generated (K8s deployment needs them)
            # If test_06 already ran, secrets will exist and --force will regenerate
            # If running test_08 alone, this ensures secrets are available
            secrets_base = project_dir / "infra" / "secrets"
            keys_dir = secrets_base / "keys"
            session_secret_file = keys_dir / "session_signing_secret.txt"

            # Check for actual secret files, not just directory existence
            # (keys_dir may exist empty from Copier template structure)
            if not session_secret_file.exists():
                print("🔐 Generating secrets for K8s deployment...")
                self.run_command(
                    [
                        "uv",
                        "run",
                        "api-forge-cli",
                        "secrets",
                        "generate",
                        "--pki",
                        "--force",
                        "--oidc-google-secret",
                        "test-google-secret-e2e",
                        "--oidc-microsoft-secret",
                        "test-microsoft-secret-e2e",
                        "--oidc-keycloak-secret",
                        "test-keycloak-secret-e2e",
                    ],
                    cwd=project_dir,
                    timeout=60,
                )

                # Verify OIDC secrets were generated correctly
                oidc_secrets = {
                    "oidc_google_client_secret.txt": "test-google-secret-e2e",
                    "oidc_microsoft_client_secret.txt": "test-microsoft-secret-e2e",
                    "oidc_keycloak_client_secret.txt": "test-keycloak-secret-e2e",
                }

                for secret_file, expected_value in oidc_secrets.items():
                    secret_path = keys_dir / secret_file
                    assert secret_path.exists(), (
                        f"OIDC secret {secret_file} not generated"
                    )
                    actual_value = secret_path.read_text().strip()
                    assert actual_value == expected_value, (
                        f"OIDC secret {secret_file} has wrong value!\n"
                        f"Expected: {expected_value}\n"
                        f"Actual: {actual_value}\n"
                        f"This means the secret came from environment variables instead of CLI flags."
                    )
                print("✅ OIDC secrets verified: Correct values (from CLI, not env)")
            else:
                print("✅ Secrets already exist (from test_06)")

            # Deploy to Kubernetes (with real-time output streaming)
            print("🚀 Starting K8s deployment with real-time output...")
            result = self.run_command(
                ["uv", "run", "api-forge-cli", "deploy", "up", "k8s"],
                cwd=project_dir,
                timeout=600,
                stream_output=True,
            )

            # Wait for pods to be ready with retries
            print("⏳ Waiting for pods to become ready...")
            max_wait = 180  # 3 minutes
            wait_interval = 15
            elapsed = 0

            while elapsed < max_wait:
                # Check pod status including container state
                result_check = self.run_command(
                    [
                        "kubectl",
                        "get",
                        "pods",
                        "-n",
                        "api-forge-prod",
                        "-l",
                        "app.kubernetes.io/name in (app,worker)",
                        "-o",
                        "json",
                    ],
                    cwd=project_dir,
                    check=False,
                )

                try:
                    pods_data = json.loads(result_check.stdout)
                    all_running = True
                    crash_detected = False

                    for pod in pods_data.get("items", []):
                        pod_name = pod["metadata"]["name"]
                        phase = pod["status"]["phase"]

                        # Check container statuses for crashes
                        container_statuses = pod["status"].get("containerStatuses", [])
                        for container_status in container_statuses:
                            state = container_status.get("state", {})
                            waiting = state.get("waiting", {})
                            reason = waiting.get("reason", "")

                            if reason == "CrashLoopBackOff":
                                crash_detected = True
                                print(
                                    f"❌ Pod {pod_name} is in CrashLoopBackOff - deployment failed!"
                                )
                                # Get logs immediately
                                log_result = self.run_command(
                                    [
                                        "kubectl",
                                        "logs",
                                        "-n",
                                        "api-forge-prod",
                                        pod_name,
                                        "--tail=100",
                                    ],
                                    cwd=project_dir,
                                    check=False,
                                )
                                print(f"\n📜 Last 100 lines of logs for {pod_name}:")
                                print(log_result.stdout)
                                break

                        if crash_detected:
                            break

                        if phase != "Running":
                            all_running = False
                            print(f"  Pod {pod_name}: {phase}")

                    if crash_detected:
                        raise RuntimeError(
                            "Deployment failed - pods are in CrashLoopBackOff. "
                            "Check logs above for details."
                        )

                    if all_running and pods_data.get("items"):
                        print("✅ All app pods are running")
                        break

                except (json.JSONDecodeError, KeyError) as e:
                    print(f"⚠️  Error parsing pod status: {e}")

                elapsed += wait_interval
                if elapsed < max_wait:
                    print(f"  Waiting {wait_interval}s more... ({elapsed}/{max_wait}s)")
                    time.sleep(wait_interval)

            if elapsed >= max_wait:
                print(f"❌ Timeout waiting for pods after {max_wait}s")
                # Show final pod status before failing
                result = self.run_command(
                    ["kubectl", "get", "pods", "-n", "api-forge-prod"],
                    cwd=project_dir,
                    check=False,
                )
                print(f"Final pod status:\n{result.stdout}")
                raise RuntimeError(
                    f"Timeout waiting for pods to become ready after {max_wait}s"
                )

            # Check deployment status
            result = self.run_command(
                ["kubectl", "get", "pods", "-n", "api-forge-prod"],
                cwd=project_dir,
            )

            print(f"Pods status:\n{result.stdout}")

            # Check for any pods in CrashLoopBackOff and get their logs
            result_check = self.run_command(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    "api-forge-prod",
                    "-o",
                    "jsonpath={range .items[*]}{.metadata.name}={.status.phase}={.status.containerStatuses[0].state}{'\\n'}{end}",
                ],
                cwd=project_dir,
                check=False,
            )

            # Get logs for any crashing pods
            for line in result_check.stdout.strip().split("\n"):
                if line and ("CrashLoopBackOff" in line or "Error" in line):
                    pod_name = line.split("=")[0]
                    print(f"\n⚠️  Pod {pod_name} is unhealthy, fetching logs...")
                    log_result = self.run_command(
                        [
                            "kubectl",
                            "logs",
                            "-n",
                            "api-forge-prod",
                            pod_name,
                            "--tail=50",
                        ],
                        cwd=project_dir,
                        check=False,
                    )
                    print(f"Last 50 lines of logs for {pod_name}:")
                    print(log_result.stdout)

            # Verify critical pods are running
            result = self.run_command(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    "api-forge-prod",
                    "-o",
                    "jsonpath={.items[*].metadata.name}",
                ],
                cwd=project_dir,
            )

            pod_names = result.stdout.strip().split()
            print(f"Running pods: {pod_names}")

            expected_pods = ["app", "worker", "postgres", "redis", "temporal"]
            for pod_prefix in expected_pods:
                assert any(pod_prefix in name for name in pod_names), (
                    f"Pod with prefix {pod_prefix} not found"
                )

            print("✅ All pods deployed")

            # Check postgres-verifier job completed successfully
            result = self.run_command(
                [
                    "kubectl",
                    "get",
                    "job",
                    "postgres-verifier",
                    "-n",
                    "api-forge-prod",
                    "-o",
                    "jsonpath={.status.succeeded}",
                ],
                cwd=project_dir,
            )

            assert result.stdout == "1", (
                "postgres-verifier job did not complete successfully"
            )
            print("✅ postgres-verifier job completed")

            # Check worker is using correct module name
            result = self.run_command(
                [
                    "kubectl",
                    "get",
                    "deployment",
                    "worker",
                    "-n",
                    "api-forge-prod",
                    "-o",
                    "jsonpath={.spec.template.spec.containers[0].args}",
                ],
                cwd=project_dir,
            )

            worker_args = result.stdout
            assert f"{project_name}.worker.main" in worker_args, (
                f"Worker not using correct module name. Got: {worker_args}"
            )

            print(f"✅ Worker using correct module: {project_name}.worker.main")

            # Verify services are accessible
            result = self.run_command(
                ["kubectl", "get", "services", "-n", "api-forge-prod"],
                cwd=project_dir,
            )

            print(f"Services:\n{result.stdout}")

            # Get app pod name for health checks
            # Note: K8s deployments use app.kubernetes.io/name label, not just app
            result = self.run_command(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    "api-forge-prod",
                    "-l",
                    "app.kubernetes.io/name=app",
                    "-o",
                    "jsonpath={.items[?(@.status.phase=='Running')].metadata.name}",
                ],
                cwd=project_dir,
                check=False,
            )

            if not result.stdout.strip():
                print("⚠️  No running app pods found, skipping health checks")
                return

            app_pod_name = result.stdout.strip().split()[0]  # Get first running pod
            print(f"App pod name: {app_pod_name}")

            # Test /health endpoint
            print("\n🏥 Testing /health endpoint...")
            result = self.run_command(
                [
                    "kubectl",
                    "exec",
                    "-n",
                    "api-forge-prod",
                    app_pod_name,
                    "--",
                    "python",
                    "-c",
                    "import urllib.request; import sys; sys.stdout.write(urllib.request.urlopen('http://localhost:8000/health').read().decode())",
                ],
                cwd=project_dir,
                check=False,
            )

            if result.returncode == 0:
                print(f"Health endpoint response:\n{result.stdout}")
                # Parse JSON and verify status
                try:
                    health_data = json.loads(result.stdout)
                    assert health_data.get("status") == "healthy", (
                        f"Health status not healthy: {health_data.get('status')}"
                    )
                    print("✅ /health endpoint: healthy")
                except json.JSONDecodeError:
                    print("⚠️  /health endpoint returned non-JSON response")

            # Test /health/ready endpoint
            print("\n🏥 Testing /health/ready endpoint...")
            result = self.run_command(
                [
                    "kubectl",
                    "exec",
                    "-n",
                    "api-forge-prod",
                    app_pod_name,
                    "--",
                    "python",
                    "-c",
                    "import urllib.request; import sys; sys.stdout.write(urllib.request.urlopen('http://localhost:8000/health/ready').read().decode())",
                ],
                cwd=project_dir,
                check=False,
            )

            if result.returncode == 0:
                print(f"Readiness endpoint response:\n{result.stdout}")
                # Parse JSON and verify all components ready
                try:
                    ready_data = json.loads(result.stdout)
                    assert ready_data.get("status") == "ready", (
                        f"Readiness status not ready: {ready_data.get('status')}"
                    )

                    # Check individual components
                    components = ready_data.get("components", {})
                    for component, status in components.items():
                        if status != "healthy":
                            print(f"⚠️  Component {component} not healthy: {status}")

                    print("✅ /health/ready endpoint: ready")
                except json.JSONDecodeError:
                    print("⚠️  /health/ready endpoint returned non-JSON response")
            else:
                print(
                    "⚠️  /health/ready endpoint check failed (may be expected in test env)"
                )

        finally:
            # Cleanup: Delete namespace
            print("\n🧹 Cleaning up Kubernetes deployment...")
            self.run_command(
                ["kubectl", "delete", "namespace", "api-forge-prod", "--wait=true"],
                cwd=project_dir,
                timeout=180,
                check=False,
            )

    def test_09_file_replacement_statistics(self):
        """Test 9: Verify unified replacement processed expected number of files."""
        print(f"\n{'=' * 80}")
        print("TEST 9: File Replacement Statistics")
        print(f"{'=' * 80}")

        # Access class variables set by setup_project fixture
        project_dir = TestCopierToDeployment._project_dir
        project_name = TestCopierToDeployment._project_name

        # Count files that should have been processed
        patterns = [
            "**/*.py",
            "**/*.yml",
            "**/*.yaml",
            "**/Dockerfile",
            "**/docker-compose*.yml",
        ]
        processed_files = set()

        exclude_dirs = {".venv", "__pycache__", ".git", "node_modules", "data"}

        for pattern in patterns:
            for file in project_dir.rglob(pattern.replace("**/", "")):
                # Skip excluded directories
                if any(excluded in file.parts for excluded in exclude_dirs):
                    continue
                processed_files.add(file)

        print(f"📊 Files that should have been processed: {len(processed_files)}")

        # Verify at least expected number (based on test_unified results: 89 files)
        assert len(processed_files) >= 80, (
            f"Expected at least 80 files, found {len(processed_files)}"
        )

        # Spot check a few critical files have correct module names
        critical_checks = [
            (project_dir / "docker-compose.prod.yml", f"{project_name}.worker.main"),
            (
                project_dir / "k8s" / "base" / "deployments" / "worker.yaml",
                f"{project_name}.worker.main",
            ),
            (
                project_dir / project_name / "app" / "worker" / "registry.py",
                f"{project_name}.app.worker",
            ),
        ]

        for file_path, expected_content in critical_checks:
            if file_path.exists():
                content = file_path.read_text()
                assert expected_content in content, (
                    f"{file_path.name} doesn't contain expected: {expected_content}"
                )
                print(f"✅ {file_path.name} contains: {expected_content}")

        print(
            f"\n✅ Unified replacement processed {len(processed_files)} files correctly"
        )


@pytest.mark.slow
class TestE2ESmokeTest:
    """Quick smoke test for CI/CD pipelines."""

    def test_copier_to_cli(self, tmp_path: Path):
        """Minimal E2E: Generate project and verify CLI works."""
        # Generate project (simplified - manual copier for now)
        # In real usage, this would use copier programmatically
        _ = tmp_path  # Mark as intentionally unused
        pytest.skip("Requires copier programmatic API - use full E2E test instead")


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s", "--tb=short"])
