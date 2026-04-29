"""Unit tests for FileSecretsManager."""

from pathlib import Path

import pytest

from src.infra.secrets import FileSecretsManager, SecretKind, SecretsManager


class TestFileSecretsManagerInit:
    """Tests for FileSecretsManager initialization."""

    def test_default_secrets_dir(self) -> None:
        """Default secrets dir is infra/secrets/keys/."""
        manager = FileSecretsManager()
        assert manager.secrets_dir.name == "keys"
        assert manager.secrets_dir.parent.name == "secrets"

    def test_default_certs_dir(self) -> None:
        """Default certs dir is infra/secrets/certs/."""
        manager = FileSecretsManager()
        assert manager.certs_dir.name == "certs"
        assert manager.certs_dir.parent.name == "secrets"

    def test_custom_secrets_dir(self, tmp_path: Path) -> None:
        """Can specify custom secrets directory."""
        custom_dir = tmp_path / "my_secrets"
        manager = FileSecretsManager(secrets_dir=custom_dir)
        assert manager.secrets_dir == custom_dir

    def test_custom_certs_dir(self, tmp_path: Path) -> None:
        """Can specify custom certificates directory."""
        custom_dir = tmp_path / "my_certs"
        manager = FileSecretsManager(certs_dir=custom_dir)
        assert manager.certs_dir == custom_dir

    def test_implements_secrets_manager(self) -> None:
        """FileSecretsManager implements SecretsManager interface."""
        manager = FileSecretsManager()
        assert isinstance(manager, SecretsManager)


class TestFileSecretsManagerRead:
    """Tests for read operations."""

    def test_read_existing_secret(self, tmp_path: Path) -> None:
        """Can read an existing secret."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("secret_value")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        assert manager.read("my_secret") == "secret_value"

    def test_read_with_txt_extension(self, tmp_path: Path) -> None:
        """Can read using key with .txt extension."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("secret_value")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        assert manager.read("my_secret.txt") == "secret_value"

    def test_read_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """Reading nonexistent secret returns None."""
        manager = FileSecretsManager(secrets_dir=tmp_path)
        assert manager.read("nonexistent") is None

    def test_read_strips_whitespace(self, tmp_path: Path) -> None:
        """Read strips trailing whitespace and newlines."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("secret_value\n\n  ")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        assert manager.read("my_secret") == "secret_value"

    def test_read_preserves_internal_whitespace(self, tmp_path: Path) -> None:
        """Read preserves internal whitespace."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("secret with spaces")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        assert manager.read("my_secret") == "secret with spaces"

    def test_read_certificate(self, tmp_path: Path) -> None:
        """Can read a certificate file using kind=CERT."""
        certs_dir = tmp_path / "certs"
        certs_dir.mkdir()
        (certs_dir / "root-ca.crt").write_text("-----BEGIN CERTIFICATE-----")

        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )
        assert (
            manager.read("root-ca.crt", kind=SecretKind.CERT)
            == "-----BEGIN CERTIFICATE-----"
        )

    def test_read_nested_certificate(self, tmp_path: Path) -> None:
        """Can read a certificate from nested directory."""
        certs_dir = tmp_path / "certs"
        (certs_dir / "postgres").mkdir(parents=True)
        (certs_dir / "postgres" / "server.key").write_text(
            "-----BEGIN PRIVATE KEY-----"
        )

        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )
        assert (
            manager.read("postgres/server.key", kind=SecretKind.CERT)
            == "-----BEGIN PRIVATE KEY-----"
        )


class TestFileSecretsManagerWrite:
    """Tests for write operations."""

    def test_write_creates_file(self, tmp_path: Path) -> None:
        """Write creates secret file."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        result = manager.write("new_secret", "new_value")

        assert result == secrets_dir / "new_secret.txt"
        assert (secrets_dir / "new_secret.txt").read_text() == "new_value"

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Write creates parent directories if needed."""
        secrets_dir = tmp_path / "deep" / "nested" / "secrets"

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        manager.write("my_secret", "value")

        assert (secrets_dir / "my_secret.txt").exists()

    def test_write_overwrites_existing(self, tmp_path: Path) -> None:
        """Write overwrites existing secret."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("old_value")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        manager.write("my_secret", "new_value")

        assert (secrets_dir / "my_secret.txt").read_text() == "new_value"

    def test_write_returns_path(self, tmp_path: Path) -> None:
        """Write returns the path to the written file."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        result = manager.write("my_secret", "value")

        assert isinstance(result, Path)
        assert result.name == "my_secret.txt"

    def test_write_certificate(self, tmp_path: Path) -> None:
        """Write creates certificate file using kind=CERT."""
        certs_dir = tmp_path / "certs"

        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )
        result = manager.write(
            "root-ca.crt", "-----BEGIN CERTIFICATE-----", kind=SecretKind.CERT
        )

        assert result == certs_dir / "root-ca.crt"
        assert result.read_text() == "-----BEGIN CERTIFICATE-----"

    def test_write_nested_certificate(self, tmp_path: Path) -> None:
        """Write creates nested certificate directories."""
        certs_dir = tmp_path / "certs"

        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )
        result = manager.write(
            "postgres/server.key", "-----BEGIN PRIVATE KEY-----", kind=SecretKind.CERT
        )

        assert result == certs_dir / "postgres" / "server.key"
        assert result.read_text() == "-----BEGIN PRIVATE KEY-----"


class TestFileSecretsManagerExists:
    """Tests for exists operation."""

    def test_exists_returns_true_for_existing(self, tmp_path: Path) -> None:
        """exists() returns True for existing secret."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("value")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        assert manager.exists("my_secret") is True

    def test_exists_returns_false_for_missing(self, tmp_path: Path) -> None:
        """exists() returns False for missing secret."""
        manager = FileSecretsManager(secrets_dir=tmp_path)
        assert manager.exists("nonexistent") is False


class TestFileSecretsManagerDelete:
    """Tests for delete operation."""

    def test_delete_removes_file(self, tmp_path: Path) -> None:
        """delete() removes the secret file."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        secret_file = secrets_dir / "my_secret.txt"
        secret_file.write_text("value")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        result = manager.delete("my_secret")

        assert result is True
        assert not secret_file.exists()

    def test_delete_returns_false_for_missing(self, tmp_path: Path) -> None:
        """delete() returns False for nonexistent secret."""
        manager = FileSecretsManager(secrets_dir=tmp_path)
        result = manager.delete("nonexistent")
        assert result is False


class TestFileSecretsManagerListKeys:
    """Tests for list_keys operation."""

    def test_list_keys_returns_all_secrets(self, tmp_path: Path) -> None:
        """list_keys() returns all secret names."""
        secrets_dir = tmp_path / "secrets"
        certs_dir = tmp_path / "certs"
        secrets_dir.mkdir()
        (secrets_dir / "secret_a.txt").write_text("a")
        (secrets_dir / "secret_b.txt").write_text("b")
        (secrets_dir / "secret_c.txt").write_text("c")

        manager = FileSecretsManager(secrets_dir=secrets_dir, certs_dir=certs_dir)
        keys = manager.list_keys()

        assert set(keys) == {"secret_a", "secret_b", "secret_c"}

    def test_list_keys_does_not_include_certificates(self, tmp_path: Path) -> None:
        """list_keys() returns only secrets, not certificates."""
        secrets_dir = tmp_path / "secrets"
        certs_dir = tmp_path / "certs"
        secrets_dir.mkdir()
        certs_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("value")
        (certs_dir / "root-ca.crt").write_text("cert")

        manager = FileSecretsManager(secrets_dir=secrets_dir, certs_dir=certs_dir)
        keys = manager.list_keys()

        assert keys == ["my_secret"]

    def test_list_keys_with_prefix(self, tmp_path: Path) -> None:
        """list_keys(prefix) filters results."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "postgres_password.txt").write_text("value1")
        (secrets_dir / "postgres_user.txt").write_text("value2")
        (secrets_dir / "redis_password.txt").write_text("value3")

        manager = FileSecretsManager(secrets_dir=secrets_dir)

        # Only postgres secrets
        postgres_keys = manager.list_keys(prefix="postgres")
        assert set(postgres_keys) == {"postgres_password", "postgres_user"}

    def test_list_keys_excludes_non_txt_files(self, tmp_path: Path) -> None:
        """list_keys() only returns .txt files from secrets dir."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "secret.txt").write_text("value")
        (secrets_dir / "readme.md").write_text("docs")
        (secrets_dir / "config.json").write_text("{}")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        keys = manager.list_keys()

        assert keys == ["secret"]

    def test_list_keys_empty_dir(self, tmp_path: Path) -> None:
        """list_keys() returns empty list for empty directory."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        assert manager.list_keys() == []

    def test_list_keys_nonexistent_dir(self, tmp_path: Path) -> None:
        """list_keys() returns empty list for nonexistent directory."""
        manager = FileSecretsManager(secrets_dir=tmp_path / "nonexistent")
        assert manager.list_keys() == []


class TestFileSecretsManagerListCerts:
    """Tests for list_certs operation."""

    def test_list_certs_returns_all_certs(self, tmp_path: Path) -> None:
        """list_certs() returns all certificate names."""
        certs_dir = tmp_path / "certs"
        certs_dir.mkdir()
        (certs_dir / "root-ca.crt").write_text("cert1")
        (certs_dir / "intermediate-ca.crt").write_text("cert2")

        manager = FileSecretsManager(certs_dir=certs_dir)
        certs = manager.list_certs()

        assert set(certs) == {"root-ca.crt", "intermediate-ca.crt"}

    def test_list_certs_includes_nested(self, tmp_path: Path) -> None:
        """list_certs() includes nested certificate directories."""
        certs_dir = tmp_path / "certs"
        certs_dir.mkdir()
        (certs_dir / "postgres").mkdir()
        (certs_dir / "root-ca.crt").write_text("root")
        (certs_dir / "postgres" / "server.key").write_text("key")
        (certs_dir / "postgres" / "server.crt").write_text("cert")

        manager = FileSecretsManager(certs_dir=certs_dir)
        certs = manager.list_certs()

        assert set(certs) == {
            "root-ca.crt",
            "postgres/server.key",
            "postgres/server.crt",
        }

    def test_list_certs_with_prefix(self, tmp_path: Path) -> None:
        """list_certs(prefix) filters results."""
        certs_dir = tmp_path / "certs"
        certs_dir.mkdir()
        (certs_dir / "postgres").mkdir()
        (certs_dir / "redis").mkdir()
        (certs_dir / "root-ca.crt").write_text("root")
        (certs_dir / "postgres" / "server.crt").write_text("pg")
        (certs_dir / "redis" / "server.crt").write_text("redis")

        manager = FileSecretsManager(certs_dir=certs_dir)
        postgres_certs = manager.list_certs(prefix="postgres/")

        assert postgres_certs == ["postgres/server.crt"]

    def test_list_certs_empty_dir(self, tmp_path: Path) -> None:
        """list_certs() returns empty list for empty directory."""
        certs_dir = tmp_path / "certs"
        certs_dir.mkdir()

        manager = FileSecretsManager(certs_dir=certs_dir)
        assert manager.list_certs() == []

    def test_list_certs_nonexistent_dir(self, tmp_path: Path) -> None:
        """list_certs() returns empty list for nonexistent directory."""
        manager = FileSecretsManager(certs_dir=tmp_path / "nonexistent")
        assert manager.list_certs() == []


class TestFileSecretsManagerHealthcheck:
    """Tests for healthcheck operation."""

    def test_healthcheck_returns_true_for_accessible_dirs(self, tmp_path: Path) -> None:
        """healthcheck() returns True when directories are accessible."""
        secrets_dir = tmp_path / "secrets"
        certs_dir = tmp_path / "certs"
        secrets_dir.mkdir()

        manager = FileSecretsManager(secrets_dir=secrets_dir, certs_dir=certs_dir)
        assert manager.healthcheck() is True

    def test_healthcheck_creates_secrets_dir_if_missing(self, tmp_path: Path) -> None:
        """healthcheck() creates secrets directory if it doesn't exist."""
        secrets_dir = tmp_path / "new_secrets"
        certs_dir = tmp_path / "certs"

        manager = FileSecretsManager(secrets_dir=secrets_dir, certs_dir=certs_dir)
        assert manager.healthcheck() is True
        assert secrets_dir.exists()

    def test_healthcheck_returns_true_with_existing_certs(self, tmp_path: Path) -> None:
        """healthcheck() returns True when certs directory exists."""
        secrets_dir = tmp_path / "secrets"
        certs_dir = tmp_path / "certs"
        secrets_dir.mkdir()
        certs_dir.mkdir()
        (certs_dir / "test.crt").write_text("cert")

        manager = FileSecretsManager(secrets_dir=secrets_dir, certs_dir=certs_dir)
        assert manager.healthcheck() is True


class TestFileSecretsManagerAppendToCaBundle:
    """Tests for append_to_ca_bundle operation."""

    def test_append_creates_bundle_if_missing(self, tmp_path: Path) -> None:
        """append_to_ca_bundle() creates bundle file if it doesn't exist."""
        certs_dir = tmp_path / "certs"
        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )

        cert_content = "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----"
        result = manager.append_to_ca_bundle(cert_content)

        assert cert_content in result
        assert (certs_dir / "ca-bundle.crt").exists()

    def test_append_adds_comment(self, tmp_path: Path) -> None:
        """append_to_ca_bundle() adds comment before certificate."""
        certs_dir = tmp_path / "certs"
        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )

        cert_content = "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----"
        result = manager.append_to_ca_bundle(cert_content, comment="Root CA")

        assert "# Root CA" in result
        assert cert_content in result

    def test_append_skips_duplicate(self, tmp_path: Path) -> None:
        """append_to_ca_bundle() skips if cert already in bundle."""
        certs_dir = tmp_path / "certs"
        certs_dir.mkdir()
        bundle_path = certs_dir / "ca-bundle.crt"
        cert_content = "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----"
        bundle_path.write_text(f"# Existing\n{cert_content}\n")

        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )

        # Try to add same cert again
        result = manager.append_to_ca_bundle(cert_content, comment="Duplicate")

        # Should not have duplicate
        assert result.count(cert_content) == 1
        assert "# Duplicate" not in result

    def test_append_multiple_certs(self, tmp_path: Path) -> None:
        """append_to_ca_bundle() can add multiple certificates."""
        certs_dir = tmp_path / "certs"
        manager = FileSecretsManager(
            secrets_dir=tmp_path / "secrets", certs_dir=certs_dir
        )

        cert1 = "-----BEGIN CERTIFICATE-----\nCERT1\n-----END CERTIFICATE-----"
        cert2 = "-----BEGIN CERTIFICATE-----\nCERT2\n-----END CERTIFICATE-----"

        manager.append_to_ca_bundle(cert1, comment="First")
        result = manager.append_to_ca_bundle(cert2, comment="Second")

        assert "# First" in result
        assert cert1 in result
        assert "# Second" in result
        assert cert2 in result


class TestSecretsManagerBaseMethods:
    """Tests for base class convenience methods."""

    def test_read_or_raise_returns_value(self, tmp_path: Path) -> None:
        """read_or_raise() returns value for existing secret."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("value")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        assert manager.read_or_raise("my_secret") == "value"

    def test_read_or_raise_raises_for_missing(self, tmp_path: Path) -> None:
        """read_or_raise() raises KeyError for missing secret."""
        manager = FileSecretsManager(secrets_dir=tmp_path)

        with pytest.raises(KeyError, match="Key not found: nonexistent"):
            manager.read_or_raise("nonexistent")

    def test_ensure_returns_existing(self, tmp_path: Path) -> None:
        """ensure() returns existing secret value."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_secret.txt").write_text("existing")

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        result = manager.ensure("my_secret", default_factory=lambda: "default")

        assert result == "existing"

    def test_ensure_creates_with_factory(self, tmp_path: Path) -> None:
        """ensure() creates secret using factory if missing."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()

        manager = FileSecretsManager(secrets_dir=secrets_dir)
        result = manager.ensure("new_secret", default_factory=lambda: "generated")

        assert result == "generated"
        assert manager.read("new_secret") == "generated"

    def test_ensure_raises_without_factory(self, tmp_path: Path) -> None:
        """ensure() raises KeyError if no factory and secret missing."""
        manager = FileSecretsManager(secrets_dir=tmp_path)

        with pytest.raises(KeyError, match="Key not found"):
            manager.ensure("nonexistent")


class TestFileSecretsManagerRoundTrip:
    """Integration tests for read/write round trips."""

    def test_write_then_read(self, tmp_path: Path) -> None:
        """Can write a secret then read it back."""
        manager = FileSecretsManager(secrets_dir=tmp_path)

        manager.write("test_secret", "test_value")
        result = manager.read("test_secret")

        assert result == "test_value"

    def test_write_read_delete_cycle(self, tmp_path: Path) -> None:
        """Full create/read/delete lifecycle works."""
        manager = FileSecretsManager(secrets_dir=tmp_path)

        # Create
        manager.write("lifecycle", "value")
        assert manager.exists("lifecycle")

        # Read
        assert manager.read("lifecycle") == "value"

        # Delete
        assert manager.delete("lifecycle") is True
        assert not manager.exists("lifecycle")
        assert manager.read("lifecycle") is None

    def test_special_characters_in_value(self, tmp_path: Path) -> None:
        """Handles special characters in secret values."""
        manager = FileSecretsManager(secrets_dir=tmp_path)

        special_value = "p@ssw0rd!#$%^&*()_+-=[]{}|;':\",./<>?"
        manager.write("special", special_value)

        assert manager.read("special") == special_value

    def test_multiline_value(self, tmp_path: Path) -> None:
        """Handles multiline secret values."""
        manager = FileSecretsManager(secrets_dir=tmp_path)

        multiline = "line1\nline2\nline3"
        manager.write("multiline", multiline)

        assert manager.read("multiline") == multiline

    def test_unicode_value(self, tmp_path: Path) -> None:
        """Handles unicode in secret values."""
        manager = FileSecretsManager(secrets_dir=tmp_path)

        unicode_value = "密码123🔐"
        manager.write("unicode", unicode_value)

        assert manager.read("unicode") == unicode_value
