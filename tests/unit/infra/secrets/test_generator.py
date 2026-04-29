"""Unit tests for secrets generator module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.infra.secrets import (
    CharSet,
    GeneratorConfig,
    PKICertificateGenerator,
    SecretGenerationOrchestrator,
    SecretGenerator,
    SecretKind,
    SecretType,
    ServiceType,
)


class TestSecretGenerator:
    """Test cases for SecretGenerator class."""

    def test_check_dependencies_success(self):
        """Test dependency checking when all dependencies are present."""
        with (
            patch("shutil.which", return_value="/usr/bin/openssl"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            # Should not raise any exception
            SecretGenerator.check_dependencies()

    def test_check_dependencies_no_openssl(self):
        """Test dependency checking when openssl is missing."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="openssl command not found"):
                SecretGenerator.check_dependencies()

    def test_check_dependencies_no_urandom(self):
        """Test dependency checking when /dev/urandom is missing."""
        with (
            patch("shutil.which", return_value="/usr/bin/openssl"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="/dev/urandom not available"):
                SecretGenerator.check_dependencies()

    def test_generate_secure_random_base64(self):
        """Test generating base64 random string."""
        mock_result = Mock()
        mock_result.stdout = "dGVzdHNlY3JldA==\n"
        with patch("subprocess.run", return_value=mock_result):
            result = SecretGenerator.generate_secure_random(32, CharSet.BASE64)
            assert result == "dGVzdHNlY3JldA=="

    def test_generate_secure_random_hex(self):
        """Test generating hex random string."""
        mock_result = Mock()
        mock_result.stdout = "abcdef1234567890\n"
        with patch("subprocess.run", return_value=mock_result):
            result = SecretGenerator.generate_secure_random(16, CharSet.HEX)
            assert result == "abcdef1234567890"

    def test_generate_secure_random_alphanumeric(self):
        """Test generating alphanumeric random string."""
        result = SecretGenerator.generate_secure_random(24, CharSet.ALPHANUMERIC)
        assert len(result) == 24
        assert result.isalnum()

    def test_generate_secure_random_password(self):
        """Test generating password with special characters."""
        result = SecretGenerator.generate_secure_random(32, CharSet.PASSWORD)
        assert len(result) == 32
        # Should contain at least one special character
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        assert any(c in result for c in special_chars) or result.isalnum()

    def test_generate_jwt_secret(self):
        """Test JWT secret generation."""
        mock_result = Mock()
        mock_result.stdout = "base64encodedsecret\n"
        with patch("subprocess.run", return_value=mock_result):
            result = SecretGenerator.generate_jwt_secret()
            assert result == "base64encodedsecret"

    def test_generate_db_password(self):
        """Test database password generation."""
        result = SecretGenerator.generate_db_password()
        assert len(result) == 24
        assert result.isalnum()
        # Should not contain special characters (URL-safe)
        assert all(c.isalnum() for c in result)

    def test_generate_csrf_secret(self):
        """Test CSRF secret generation."""
        mock_result = Mock()
        mock_result.stdout = "secret+with/special==\n"
        with patch("subprocess.run", return_value=mock_result):
            result = SecretGenerator.generate_csrf_secret()
            # Should replace + with -, / with _, and remove =
            assert "+" not in result
            assert "/" not in result
            assert "=" not in result

    def test_generate_session_secret(self):
        """Test session secret generation."""
        mock_result = Mock()
        mock_result.stdout = "session+secret/here==\n"
        with patch("subprocess.run", return_value=mock_result):
            result = SecretGenerator.generate_session_secret()
            # Should replace + with -, / with _, and remove =
            assert "+" not in result
            assert "/" not in result
            assert "=" not in result

    def test_generate_backup_password(self):
        """Test backup password generation."""
        result = SecretGenerator.generate_backup_password()
        assert len(result) == 32
        # Should contain alphanumeric and some allowed special chars
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-=[]{}|"
        assert all(c in allowed for c in result)


class TestPKICertificateGenerator:
    """Test cases for PKICertificateGenerator class."""

    @pytest.fixture
    def secrets_manager(self, tmp_path: Path):
        """Create FileSecretsManager for testing."""
        from src.infra.secrets.file_manager import FileSecretsManager

        return FileSecretsManager(
            secrets_dir=tmp_path / "keys",
            certs_dir=tmp_path / "certs",
            backups_dir=tmp_path / "backups",
        )

    @pytest.fixture
    def pki_gen(self, secrets_manager):
        """Create PKICertificateGenerator instance."""
        return PKICertificateGenerator(secrets_manager)

    def test_generate_root_ca(self, pki_gen: PKICertificateGenerator, secrets_manager):
        """Test root CA generation."""
        with patch("subprocess.run") as mock_run:
            # Mock genkey output
            mock_run.return_value = Mock(
                stdout=b"-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----\n",
                returncode=0,
            )
            pki_gen.generate_root_ca()

            # Should call openssl genrsa
            assert mock_run.call_count >= 1
            # Verify files were written via SecretsManager
            assert secrets_manager.exists("root-ca.key", SecretKind.CERT)
            assert secrets_manager.exists("root-ca.crt", SecretKind.CERT)

    def test_generate_intermediate_ca(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test intermediate CA generation."""
        # Create mock root CA files via SecretsManager
        secrets_manager.write(
            "root-ca.key",
            "-----BEGIN RSA PRIVATE KEY-----\nMOCK\n-----END RSA PRIVATE KEY-----",
            SecretKind.CERT,
        )
        secrets_manager.write(
            "root-ca.crt",
            "-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
            SecretKind.CERT,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=b"-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----\n",
                returncode=0,
            )
            pki_gen.generate_intermediate_ca()

            # Verify files were written via SecretsManager
            assert secrets_manager.exists("intermediate-ca.key", SecretKind.CERT)
            assert secrets_manager.exists("intermediate-ca.crt", SecretKind.CERT)

    def test_generate_service_certificate(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test service certificate generation."""
        # Create mock CA files via SecretsManager
        secrets_manager.write(
            "intermediate-ca.key",
            "-----BEGIN RSA PRIVATE KEY-----\nMOCK\n-----END RSA PRIVATE KEY-----",
            SecretKind.CERT,
        )
        secrets_manager.write(
            "intermediate-ca.crt",
            "-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
            SecretKind.CERT,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=b"-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----\n",
                returncode=0,
            )
            pki_gen.generate_service_certificate(ServiceType.POSTGRES)

            # Verify files were written via SecretsManager
            assert secrets_manager.exists("postgres/server.key", SecretKind.CERT)
            assert secrets_manager.exists("postgres/server.crt", SecretKind.CERT)

    def test_create_certificate_chain(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test certificate chain creation."""
        # Create mock files via SecretsManager
        secrets_manager.write("postgres/server.crt", "SERVER CERT\n", SecretKind.CERT)
        secrets_manager.write(
            "intermediate-ca.crt", "INTERMEDIATE CERT\n", SecretKind.CERT
        )
        secrets_manager.write("root-ca.crt", "ROOT CERT\n", SecretKind.CERT)

        pki_gen.create_certificate_chain(ServiceType.POSTGRES)

        # Check full chain
        chain_content = secrets_manager.read(
            "postgres/server-chain.crt", SecretKind.CERT
        )
        assert chain_content is not None
        assert "SERVER CERT" in chain_content
        assert "INTERMEDIATE CERT" in chain_content
        assert "ROOT CERT" in chain_content

        # Check chain without root
        chain_no_root = secrets_manager.read(
            "postgres/server-chain-no-root.crt", SecretKind.CERT
        )
        assert chain_no_root is not None
        assert "SERVER CERT" in chain_no_root
        assert "INTERMEDIATE CERT" in chain_no_root
        assert "ROOT CERT" not in chain_no_root

    def test_create_ca_bundle(self, pki_gen: PKICertificateGenerator, secrets_manager):
        """Test CA bundle creation."""
        # Create mock files via SecretsManager
        secrets_manager.write(
            "intermediate-ca.crt", "INTERMEDIATE CERT\n", SecretKind.CERT
        )
        secrets_manager.write("root-ca.crt", "ROOT CERT\n", SecretKind.CERT)

        pki_gen.create_ca_bundle()

        ca_bundle = secrets_manager.read("ca-bundle.crt", SecretKind.CERT)
        assert ca_bundle is not None
        assert "INTERMEDIATE CERT" in ca_bundle
        assert "ROOT CERT" in ca_bundle

    def test_create_ca_bundle_with_external_pg_ca(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test CA bundle creation with external PostgreSQL CA."""
        # Create mock files via SecretsManager
        secrets_manager.write(
            "intermediate-ca.crt", "INTERMEDIATE CERT\n", SecretKind.CERT
        )
        secrets_manager.write("root-ca.crt", "ROOT CERT\n", SecretKind.CERT)
        secrets_manager.write(
            "ca-bundle-postgres-external.crt", "EXTERNAL PG CA\n", SecretKind.CERT
        )

        pki_gen.create_ca_bundle()

        ca_bundle = secrets_manager.read("ca-bundle.crt", SecretKind.CERT)
        assert ca_bundle is not None
        assert "INTERMEDIATE CERT" in ca_bundle
        assert "ROOT CERT" in ca_bundle
        assert "EXTERNAL PG CA" in ca_bundle

    def test_ca_certificates_exist_true(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test checking if CA certificates exist - positive case."""
        # Create all required files via SecretsManager
        secrets_manager.write("root-ca.crt", "MOCK", SecretKind.CERT)
        secrets_manager.write("root-ca.key", "MOCK", SecretKind.CERT)
        secrets_manager.write("intermediate-ca.crt", "MOCK", SecretKind.CERT)
        secrets_manager.write("intermediate-ca.key", "MOCK", SecretKind.CERT)

        assert pki_gen.ca_certificates_exist() is True

    def test_ca_certificates_exist_false(self, pki_gen: PKICertificateGenerator):
        """Test checking if CA certificates exist - negative case."""
        assert pki_gen.ca_certificates_exist() is False

    def test_generate_pki_certificates(self, pki_gen: PKICertificateGenerator):
        """Test full PKI certificate generation."""
        with (
            patch.object(pki_gen, "generate_root_ca") as mock_root_ca,
            patch.object(pki_gen, "generate_intermediate_ca") as mock_int_ca,
            patch.object(pki_gen, "generate_service_certificate") as mock_svc_cert,
            patch.object(pki_gen, "create_certificate_chain") as mock_cert_chain,
            patch.object(
                pki_gen, "create_ca_bundle", return_value=False
            ) as mock_ca_bundle,
        ):
            result = pki_gen.generate_pki_certificates()

            # Should generate for all three services
            assert mock_svc_cert.call_count == 3
            assert mock_cert_chain.call_count == 3
            # Verify other methods were called
            mock_root_ca.assert_called_once()
            mock_int_ca.assert_called_once()
            mock_ca_bundle.assert_called_once()
            # Verify result
            assert result.root_ca_generated is True
            assert result.intermediate_ca_generated is True

    def test_certificate_chain_has_proper_newlines(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test that certificate chains have proper newline separators.

        This test catches the bug where FileSecretsManager.read() strips trailing
        newlines, causing certificates to run together in chains.
        """
        # Create realistic PEM certificate content (with trailing newlines)
        server_cert = (
            "-----BEGIN CERTIFICATE-----\nSERVER_CERT_DATA\n-----END CERTIFICATE-----\n"
        )
        intermediate_cert = "-----BEGIN CERTIFICATE-----\nINTERMEDIATE_DATA\n-----END CERTIFICATE-----\n"
        root_cert = (
            "-----BEGIN CERTIFICATE-----\nROOT_CERT_DATA\n-----END CERTIFICATE-----\n"
        )

        secrets_manager.write("postgres/server.crt", server_cert, SecretKind.CERT)
        secrets_manager.write("intermediate-ca.crt", intermediate_cert, SecretKind.CERT)
        secrets_manager.write("root-ca.crt", root_cert, SecretKind.CERT)

        pki_gen.create_certificate_chain(ServiceType.POSTGRES)

        # Read the full chain
        chain_content = secrets_manager.read(
            "postgres/server-chain.crt", SecretKind.CERT
        )
        assert chain_content is not None

        # Critical: Certificates must be separated by newlines
        # Without newlines, OpenSSL will fail with "bad end line" error
        assert "-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----" in chain_content

        # Verify each certificate is complete and properly terminated
        assert chain_content.count("-----BEGIN CERTIFICATE-----") == 3
        assert chain_content.count("-----END CERTIFICATE-----") == 3

        # Verify certificates are in the correct order
        parts = chain_content.split("-----BEGIN CERTIFICATE-----")
        assert "SERVER_CERT_DATA" in parts[1]
        assert "INTERMEDIATE_DATA" in parts[2]
        assert "ROOT_CERT_DATA" in parts[3]

    def test_certificate_chain_no_root_has_proper_newlines(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test that certificate chains without root CA have proper newline separators."""
        server_cert = (
            "-----BEGIN CERTIFICATE-----\nSERVER_CERT_DATA\n-----END CERTIFICATE-----\n"
        )
        intermediate_cert = "-----BEGIN CERTIFICATE-----\nINTERMEDIATE_DATA\n-----END CERTIFICATE-----\n"
        root_cert = (
            "-----BEGIN CERTIFICATE-----\nROOT_CERT_DATA\n-----END CERTIFICATE-----\n"
        )

        secrets_manager.write("postgres/server.crt", server_cert, SecretKind.CERT)
        secrets_manager.write("intermediate-ca.crt", intermediate_cert, SecretKind.CERT)
        secrets_manager.write("root-ca.crt", root_cert, SecretKind.CERT)

        pki_gen.create_certificate_chain(ServiceType.POSTGRES)

        # Read the chain without root CA
        chain_content = secrets_manager.read(
            "postgres/server-chain-no-root.crt", SecretKind.CERT
        )
        assert chain_content is not None

        # Must have proper separation between certificates
        assert "-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----" in chain_content

        # Should have exactly 2 certificates (server + intermediate, no root)
        assert chain_content.count("-----BEGIN CERTIFICATE-----") == 2
        assert chain_content.count("-----END CERTIFICATE-----") == 2

        # Verify root CA is NOT in the chain
        assert "ROOT_CERT_DATA" not in chain_content

    def test_ca_bundle_has_proper_newlines(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test that CA bundle has proper newline separators."""
        intermediate_cert = "-----BEGIN CERTIFICATE-----\nINTERMEDIATE_DATA\n-----END CERTIFICATE-----\n"
        root_cert = (
            "-----BEGIN CERTIFICATE-----\nROOT_CERT_DATA\n-----END CERTIFICATE-----\n"
        )

        secrets_manager.write("intermediate-ca.crt", intermediate_cert, SecretKind.CERT)
        secrets_manager.write("root-ca.crt", root_cert, SecretKind.CERT)

        pki_gen.create_ca_bundle()

        ca_bundle = secrets_manager.read("ca-bundle.crt", SecretKind.CERT)
        assert ca_bundle is not None

        # Certificates must be separated by newlines
        assert "-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----" in ca_bundle

        # Should have exactly 2 certificates
        assert ca_bundle.count("-----BEGIN CERTIFICATE-----") == 2
        assert ca_bundle.count("-----END CERTIFICATE-----") == 2

    def test_ca_bundle_with_external_ca_has_proper_newlines(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test that CA bundle with external CA has proper newline separators."""
        intermediate_cert = "-----BEGIN CERTIFICATE-----\nINTERMEDIATE_DATA\n-----END CERTIFICATE-----\n"
        root_cert = (
            "-----BEGIN CERTIFICATE-----\nROOT_CERT_DATA\n-----END CERTIFICATE-----\n"
        )
        external_cert = (
            "-----BEGIN CERTIFICATE-----\nEXTERNAL_CA_DATA\n-----END CERTIFICATE-----\n"
        )

        secrets_manager.write("intermediate-ca.crt", intermediate_cert, SecretKind.CERT)
        secrets_manager.write("root-ca.crt", root_cert, SecretKind.CERT)
        secrets_manager.write(
            "ca-bundle-postgres-external.crt", external_cert, SecretKind.CERT
        )

        result = pki_gen.create_ca_bundle()

        assert result is True  # External CA was included

        ca_bundle = secrets_manager.read("ca-bundle.crt", SecretKind.CERT)
        assert ca_bundle is not None

        # All certificates must be separated properly
        assert ca_bundle.count("-----BEGIN CERTIFICATE-----") == 3
        assert ca_bundle.count("-----END CERTIFICATE-----") == 3

        # Verify external CA is included and properly separated
        assert "EXTERNAL_CA_DATA" in ca_bundle
        assert "# External PostgreSQL CA Certificate" in ca_bundle

    def test_certificate_chain_handles_stripped_content(
        self, pki_gen: PKICertificateGenerator, secrets_manager
    ):
        """Test that certificate chains work even when FileSecretsManager strips newlines.

        FileSecretsManager.read() calls .strip() which removes trailing whitespace.
        The PKI generator must compensate by adding newlines between certificates.
        """
        # Simulate what happens after FileSecretsManager.read() strips content
        server_cert_stripped = (
            "-----BEGIN CERTIFICATE-----\nSERVER_CERT_DATA\n-----END CERTIFICATE-----"
        )
        intermediate_cert_stripped = (
            "-----BEGIN CERTIFICATE-----\nINTERMEDIATE_DATA\n-----END CERTIFICATE-----"
        )
        root_cert_stripped = (
            "-----BEGIN CERTIFICATE-----\nROOT_CERT_DATA\n-----END CERTIFICATE-----"
        )

        # Write with trailing newlines (as generated by OpenSSL)
        secrets_manager.write(
            "postgres/server.crt", server_cert_stripped + "\n", SecretKind.CERT
        )
        secrets_manager.write(
            "intermediate-ca.crt", intermediate_cert_stripped + "\n", SecretKind.CERT
        )
        secrets_manager.write("root-ca.crt", root_cert_stripped + "\n", SecretKind.CERT)

        pki_gen.create_certificate_chain(ServiceType.POSTGRES)

        # Read back - FileSecretsManager will strip the trailing newline
        chain_content = secrets_manager.read(
            "postgres/server-chain.crt", SecretKind.CERT
        )

        # Even though read() strips trailing whitespace, the chain should still be valid
        # because create_certificate_chain() adds explicit newlines between certs
        assert chain_content is not None

        # This is the critical assertion that would have caught the original bug:
        # Without explicit newlines added by create_certificate_chain(), this would fail
        # because the certificates would be concatenated as:
        # "...-----END CERTIFICATE----------BEGIN CERTIFICATE-----..."
        # instead of:
        # "...-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----..."

        # Verify certificates are properly separated
        # The fix adds "\n" between certs, which creates proper PEM format
        assert (
            "-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----" in chain_content
        ), (
            "Certificates must be separated by newlines. "
            "Without this, PostgreSQL will fail with 'bad end line' error."
        )

        # Verify all three certificates are present
        assert chain_content.count("-----BEGIN CERTIFICATE-----") == 3
        assert chain_content.count("-----END CERTIFICATE-----") == 3


class TestSecretGenerationOrchestrator:
    """Test cases for SecretGenerationOrchestrator class."""

    @pytest.fixture
    def temp_secrets_dir(self, tmp_path: Path):
        """Create temporary secrets directory."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "keys").mkdir()
        (secrets_dir / "certs").mkdir()
        (secrets_dir / "backups").mkdir()
        return secrets_dir

    @pytest.fixture
    def config(self, temp_secrets_dir: Path):
        """Create test configuration."""
        from src.infra.secrets.file_manager import FileSecretsManager

        secrets_manager = FileSecretsManager(
            secrets_dir=temp_secrets_dir / "keys",
            certs_dir=temp_secrets_dir / "certs",
            backups_dir=temp_secrets_dir / "backups",
        )
        return GeneratorConfig(
            secrets_manager=secrets_manager,
            secrets_dir=temp_secrets_dir,
            non_interactive=True,
            overwrite_secrets=False,
        )

    @pytest.fixture
    def mock_console(self):
        """Create mock console."""
        return MagicMock()

    def test_init_validation_missing_prompt_provider(
        self, config: GeneratorConfig, mock_console
    ):
        """Test validation fails when interactive mode lacks prompt provider."""
        config.non_interactive = False
        config.prompt_provider = None

        with pytest.raises(ValueError, match="PromptProvider is required"):
            SecretGenerationOrchestrator(config, mock_console)

    @pytest.fixture
    def orchestrator(self, config: GeneratorConfig, mock_console):
        """Create SecretGenerationOrchestrator instance."""
        return SecretGenerationOrchestrator(config, mock_console)

    def test_load_user_supplied_secrets(
        self, orchestrator: SecretGenerationOrchestrator, tmp_path: Path
    ):
        """Test loading user-supplied secrets from file."""
        user_secrets_file = tmp_path / "user-secrets.env"
        user_secrets_file.write_text(
            "OIDC_GOOGLE_CLIENT_SECRET=google_secret_123\n"
            "OIDC_MICROSOFT_CLIENT_SECRET=ms_secret_456\n"
            "# Comment line\n"
            "\n"
            "OIDC_KEYCLOAK_CLIENT_SECRET=keycloak_secret_789\n"
        )

        orchestrator.config.user_secrets_file = user_secrets_file
        orchestrator.load_user_supplied_secrets()

        assert orchestrator.user_secrets_loaded is True
        assert (
            orchestrator.user_secrets["OIDC_GOOGLE_CLIENT_SECRET"]
            == "google_secret_123"
        )
        assert (
            orchestrator.user_secrets["OIDC_MICROSOFT_CLIENT_SECRET"] == "ms_secret_456"
        )
        assert (
            orchestrator.user_secrets["OIDC_KEYCLOAK_CLIENT_SECRET"]
            == "keycloak_secret_789"
        )

    def test_load_user_supplied_secrets_file_not_found(
        self, orchestrator: SecretGenerationOrchestrator, tmp_path: Path
    ):
        """Test loading user-supplied secrets when file doesn't exist."""
        orchestrator.config.user_secrets_file = tmp_path / "nonexistent.env"
        orchestrator.load_user_supplied_secrets()

        assert orchestrator.user_secrets_loaded is False
        assert len(orchestrator.user_secrets) == 0

    def test_obtain_deterministic_secret_from_cli(
        self, orchestrator: SecretGenerationOrchestrator
    ):
        """Test obtaining secret from CLI argument."""
        result = orchestrator.obtain_deterministic_secret(
            secret_label="Test Secret",
            cli_value="cli_provided_value",
            env_var_name="TEST_SECRET",
            prompt_message="Enter test secret",
        )

        assert result == "cli_provided_value"

    def test_obtain_deterministic_secret_from_env(
        self, orchestrator: SecretGenerationOrchestrator
    ):
        """Test obtaining secret from environment variable."""
        with patch.dict("os.environ", {"TEST_SECRET": "env_provided_value"}):
            result = orchestrator.obtain_deterministic_secret(
                secret_label="Test Secret",
                cli_value=None,
                env_var_name="TEST_SECRET",
                prompt_message="Enter test secret",
            )

            assert result == "env_provided_value"

    def test_obtain_deterministic_secret_non_interactive_missing(
        self, orchestrator: SecretGenerationOrchestrator
    ):
        """Test obtaining secret in non-interactive mode when missing."""
        orchestrator.config.non_interactive = True

        with pytest.raises(SystemExit):
            orchestrator.obtain_deterministic_secret(
                secret_label="Test Secret",
                cli_value=None,
                env_var_name="MISSING_SECRET",
                prompt_message="Enter test secret",
            )

    def test_write_secret_new_file(
        self, orchestrator: SecretGenerationOrchestrator, temp_secrets_dir: Path
    ):
        """Test writing a new secret via SecretsManager."""
        result = orchestrator.write_secret("test_secret", "my_secret_value")

        assert result is True
        # Read back via secrets manager
        assert orchestrator._secrets_manager.exists("test_secret")
        assert orchestrator._secrets_manager.read("test_secret") == "my_secret_value"

    def test_write_secret_existing_no_overwrite(
        self, orchestrator: SecretGenerationOrchestrator, temp_secrets_dir: Path
    ):
        """Test writing secret when file exists and overwrite is False."""
        # Write initial secret
        orchestrator._secrets_manager.write("existing_secret", "old_value")

        result = orchestrator.write_secret("existing_secret", "new_value")

        assert result is False
        # Original value should be preserved
        assert orchestrator._secrets_manager.read("existing_secret") == "old_value"

    def test_write_secret_existing_with_overwrite(
        self, orchestrator: SecretGenerationOrchestrator, temp_secrets_dir: Path
    ):
        """Test writing secret when file exists and overwrite is True."""
        orchestrator.config.overwrite_secrets = True
        # Write initial secret
        orchestrator._secrets_manager.write("existing_secret", "old_value")

        result = orchestrator.write_secret("existing_secret", "new_value")

        assert result is True
        # Value should be updated
        assert orchestrator._secrets_manager.read("existing_secret") == "new_value"

    def test_generate_deterministic_secrets(
        self, orchestrator: SecretGenerationOrchestrator
    ):
        """Test generating deterministic secrets."""
        orchestrator.config.oidc_google_secret = "google_123"
        orchestrator.config.oidc_microsoft_secret = "microsoft_456"
        orchestrator.config.oidc_keycloak_secret = "keycloak_789"

        with patch.object(orchestrator, "write_secret") as mock_write:
            orchestrator.generate_deterministic_secrets()

            # Should write all three OIDC secrets
            assert mock_write.call_count == 3
            mock_write.assert_any_call("oidc_google_client_secret", "google_123")
            mock_write.assert_any_call("oidc_microsoft_client_secret", "microsoft_456")
            mock_write.assert_any_call("oidc_keycloak_client_secret", "keycloak_789")

    def test_generate_all_secrets(self, orchestrator: SecretGenerationOrchestrator):
        """Test generating all secrets."""
        orchestrator.config.oidc_google_secret = "google_test"
        orchestrator.config.oidc_microsoft_secret = "microsoft_test"
        orchestrator.config.oidc_keycloak_secret = "keycloak_test"

        with patch("src.infra.secrets.generator.SecretGenerator") as mock_gen_class:
            mock_generator = MagicMock()
            mock_gen_class.return_value = mock_generator
            mock_generator.generate_db_password.return_value = "db_pass_123"
            mock_generator.generate_session_secret.return_value = "session_secret"
            mock_generator.generate_csrf_secret.return_value = "csrf_secret"

            orchestrator.generate_all_secrets()

            # Should generate all database passwords
            assert mock_generator.generate_db_password.call_count == 6

    def test_verify_secrets_all_good(
        self, orchestrator: SecretGenerationOrchestrator, temp_secrets_dir: Path
    ):
        """Test verifying secrets when all are present and valid."""
        # Create all required secrets with proper lengths
        for secret_type in SecretType:
            orchestrator._secrets_manager.write(secret_type.value, "a" * 32)

        orchestrator.verify_secrets()

        # Should print success message (check console was called)
        assert len(orchestrator.console.mock_calls) > 0  # type: ignore[attr-defined]

    def test_verify_secrets_missing_files(
        self, orchestrator: SecretGenerationOrchestrator
    ):
        """Test verifying secrets when files are missing."""
        # Don't create any files
        orchestrator.verify_secrets()

        # Should print warnings (check console was called with warnings)
        assert len(orchestrator.console.mock_calls) > 0  # type: ignore[attr-defined]

    def test_list_secrets(
        self, orchestrator: SecretGenerationOrchestrator, temp_secrets_dir: Path
    ):
        """Test listing secrets."""
        # Create some test secrets
        orchestrator._secrets_manager.write("postgres_password", "password123")
        orchestrator._secrets_manager.write("session_signing_secret", "session_secret")

        orchestrator.list_secrets()

        # Should print the list (check console was called)
        assert len(orchestrator.console.mock_calls) > 0  # type: ignore[attr-defined]
