"""PKI Certificate generation logic.

This module handles the generation of PKI certificates using OpenSSL.
It is completely decoupled from UI/Console output.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .base import SecretKind

if TYPE_CHECKING:
    from .base import SecretsManager


class ServiceType(Enum):
    """Service types for certificate generation."""

    POSTGRES = "postgres"
    REDIS = "redis"
    TEMPORAL = "temporal"


# Subject Alternative Names for each service type
SERVICE_SANS: dict[ServiceType, list[str]] = {
    ServiceType.POSTGRES: [
        "DNS:postgres",
        "DNS:postgres.backend",
        "DNS:app_data_postgres_db",
        "DNS:database",
        "DNS:db",
        "DNS:localhost",
        "DNS:*.fly.dev",
        "DNS:*.internal",
        "IP:127.0.0.1",
        "IP:::1",
    ],
    ServiceType.REDIS: [
        "DNS:redis",
        "DNS:redis.backend",
        "DNS:cache",
        "DNS:localhost",
        "DNS:*.fly.dev",
        "DNS:*.internal",
        "IP:127.0.0.1",
        "IP:::1",
    ],
    ServiceType.TEMPORAL: [
        "DNS:temporal",
        "DNS:temporal.backend",
        "DNS:temporal-server",
        "DNS:workflow",
        "DNS:localhost",
        "DNS:*.fly.dev",
        "DNS:*.internal",
        "IP:127.0.0.1",
        "IP:::1",
    ],
}


@dataclass
class PKIGenerationResult:
    """Result of PKI certificate generation."""

    root_ca_generated: bool = False
    intermediate_ca_generated: bool = False
    services_generated: list[str] = field(default_factory=list)
    chains_created: list[str] = field(default_factory=list)
    ca_bundle_created: bool = False
    external_ca_included: bool = False


class PKICertificateGenerator:
    """Generator for PKI certificates.

    This class generates PKI certificate content (via openssl) and uses
    a SecretsManager for storage. It does NOT access the filesystem directly
    and has NO UI dependencies.

    The separation ensures:
    - Certificate generation logic is independent of storage backend
    - Can be used with file-based, Vault, K8s, or any SecretsManager implementation
    - UI/output handling is the caller's responsibility
    """

    def __init__(self, secrets_manager: SecretsManager):
        """Initialize the PKI certificate generator.

        Args:
            secrets_manager: SecretsManager for storing generated certificates
        """
        self._secrets_manager = secrets_manager

    def _run_openssl_genkey(self, bits: int = 4096) -> str:
        """Generate an RSA private key using openssl.

        Args:
            bits: Key size in bits (default 4096 for CA, 2048 for services)

        Returns:
            PEM-encoded private key content
        """
        result = subprocess.run(
            ["openssl", "genrsa", str(bits)],
            capture_output=True,
            check=True,
        )
        return result.stdout.decode()

    def _run_openssl_req(
        self,
        key_content: str,
        subject: str,
        config: str,
        days: int | None = None,
        is_self_signed: bool = False,
    ) -> str:
        """Generate a certificate or CSR using openssl.

        Args:
            key_content: PEM-encoded private key
            subject: Certificate subject DN
            config: OpenSSL config content
            days: Validity period (only for self-signed)
            is_self_signed: If True, generate self-signed cert; otherwise CSR

        Returns:
            PEM-encoded certificate or CSR content
        """
        import tempfile

        with (
            tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as key_f,
            tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as cfg_f,
        ):
            key_f.write(key_content)
            key_f.flush()
            cfg_f.write(config)
            cfg_f.flush()

            cmd = ["openssl", "req", "-new"]
            if is_self_signed:
                cmd.extend(["-x509", "-days", str(days or 3650)])
            cmd.extend(["-key", key_f.name, "-subj", subject, "-config", cfg_f.name])

            result = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
            )

            # Clean up temp files
            Path(key_f.name).unlink(missing_ok=True)
            Path(cfg_f.name).unlink(missing_ok=True)

            return result.stdout.decode()

    def generate_root_ca(self) -> None:
        """Generate Root Certificate Authority."""
        # Generate root CA private key (4096-bit for security)
        root_key_content = self._run_openssl_genkey(4096)

        # Create OpenSSL config for root CA
        config = """[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca

[req_distinguished_name]

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer:always
"""

        # Create root CA certificate (valid for 10 years)
        root_crt_content = self._run_openssl_req(
            key_content=root_key_content,
            subject="/C=US/ST=State/L=City/O=Organization/OU=IT Department/CN=Internal Root CA",
            config=config,
            days=3650,
            is_self_signed=True,
        )

        # Store via SecretsManager
        self._secrets_manager.write("root-ca.key", root_key_content, SecretKind.CERT)
        self._secrets_manager.write("root-ca.crt", root_crt_content, SecretKind.CERT)

    def _sign_certificate(
        self,
        csr_content: str,
        ca_key_content: str,
        ca_cert_content: str,
        config: str,
        days: int,
        extensions_section: str | None = None,
    ) -> str:
        """Sign a CSR with a CA certificate using openssl.

        Args:
            csr_content: PEM-encoded CSR
            ca_key_content: PEM-encoded CA private key
            ca_cert_content: PEM-encoded CA certificate
            config: OpenSSL extensions config
            days: Certificate validity in days
            extensions_section: Name of the section in config to use for extensions

        Returns:
            PEM-encoded signed certificate
        """
        import tempfile

        # OpenSSL x509 -req requires files for CA cert/key, so we use temp files
        with (
            tempfile.NamedTemporaryFile(mode="w", suffix=".csr", delete=False) as csr_f,
            tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as key_f,
            tempfile.NamedTemporaryFile(mode="w", suffix=".crt", delete=False) as crt_f,
            tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as cfg_f,
        ):
            csr_f.write(csr_content)
            csr_f.flush()
            key_f.write(ca_key_content)
            key_f.flush()
            crt_f.write(ca_cert_content)
            crt_f.flush()
            cfg_f.write(config)
            cfg_f.flush()

            cmd = [
                "openssl",
                "x509",
                "-req",
                "-in",
                csr_f.name,
                "-CA",
                crt_f.name,
                "-CAkey",
                key_f.name,
                "-CAcreateserial",
                "-days",
                str(days),
                "-extfile",
                cfg_f.name,
            ]

            # Add -extensions flag if extensions_section is specified
            if extensions_section:
                cmd.extend(["-extensions", extensions_section])

            result = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
            )

            # Clean up temp files
            for f in [csr_f, key_f, crt_f, cfg_f]:
                Path(f.name).unlink(missing_ok=True)
            # Also clean up .srl file created by -CAcreateserial
            Path(crt_f.name).with_suffix(".srl").unlink(missing_ok=True)

            return result.stdout.decode()

    def _generate_csr(self, key_content: str, subject: str) -> str:
        """Generate a Certificate Signing Request.

        Args:
            key_content: PEM-encoded private key
            subject: Certificate subject DN

        Returns:
            PEM-encoded CSR
        """
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".key", delete=False
        ) as key_f:
            key_f.write(key_content)
            key_f.flush()

            result = subprocess.run(
                [
                    "openssl",
                    "req",
                    "-new",
                    "-key",
                    key_f.name,
                    "-subj",
                    subject,
                ],
                capture_output=True,
                check=True,
            )

            Path(key_f.name).unlink(missing_ok=True)
            return result.stdout.decode()

    def generate_intermediate_ca(self) -> None:
        """Generate Intermediate Certificate Authority."""
        # Read root CA from SecretsManager
        root_key_content = self._secrets_manager.read("root-ca.key", SecretKind.CERT)
        root_crt_content = self._secrets_manager.read("root-ca.crt", SecretKind.CERT)
        if not root_key_content or not root_crt_content:
            raise RuntimeError("Root CA not found. Generate root CA first.")

        # Generate intermediate CA private key
        int_key_content = self._run_openssl_genkey(4096)

        # Create CSR
        int_csr_content = self._generate_csr(
            int_key_content,
            "/C=US/ST=State/L=City/O=Organization/OU=IT Department/CN=Internal Intermediate CA",
        )

        # OpenSSL config for intermediate CA
        config = """[v3_intermediate_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer:always
"""

        # Sign intermediate CA certificate with root CA (valid for 5 years)
        int_crt_content = self._sign_certificate(
            csr_content=int_csr_content,
            ca_key_content=root_key_content,
            ca_cert_content=root_crt_content,
            config=config,
            days=1825,
            extensions_section="v3_intermediate_ca",
        )

        # Store via SecretsManager
        self._secrets_manager.write(
            "intermediate-ca.key", int_key_content, SecretKind.CERT
        )
        self._secrets_manager.write(
            "intermediate-ca.crt", int_crt_content, SecretKind.CERT
        )

    def generate_service_certificate(self, service: ServiceType) -> None:
        """Generate certificate for a service.

        Args:
            service: Service type to generate certificate for
        """
        # Read intermediate CA from SecretsManager
        int_key_content = self._secrets_manager.read(
            "intermediate-ca.key", SecretKind.CERT
        )
        int_crt_content = self._secrets_manager.read(
            "intermediate-ca.crt", SecretKind.CERT
        )
        if not int_key_content or not int_crt_content:
            raise RuntimeError("Intermediate CA not found. Generate CAs first.")

        # Generate service private key (2048-bit for services)
        srv_key_content = self._run_openssl_genkey(2048)

        # Create CSR
        srv_csr_content = self._generate_csr(
            srv_key_content,
            f"/C=US/ST=State/L=City/O=Organization/OU=IT Department/CN={service.value}.local",
        )

        # Get SANs for this service
        sans = ",".join(SERVICE_SANS[service])

        # OpenSSL config for service certificate
        config = f"""[v3_service]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer:always
subjectAltName = {sans}
"""

        # Sign service certificate with intermediate CA (valid for 1 year)
        srv_crt_content = self._sign_certificate(
            csr_content=srv_csr_content,
            ca_key_content=int_key_content,
            ca_cert_content=int_crt_content,
            config=config,
            days=365,
            extensions_section="v3_service",
        )

        # Store via SecretsManager (with service subdirectory prefix)
        self._secrets_manager.write(
            f"{service.value}/server.key", srv_key_content, SecretKind.CERT
        )
        self._secrets_manager.write(
            f"{service.value}/server.crt", srv_crt_content, SecretKind.CERT
        )

    def create_certificate_chain(self, service: ServiceType) -> None:
        """Create certificate chain files for a service.

        Args:
            service: Service type to create chain for
        """
        # Read certificates from SecretsManager
        srv_crt = self._secrets_manager.read(
            f"{service.value}/server.crt", SecretKind.CERT
        )
        int_crt = self._secrets_manager.read("intermediate-ca.crt", SecretKind.CERT)
        root_crt = self._secrets_manager.read("root-ca.crt", SecretKind.CERT)

        if srv_crt is None or int_crt is None or root_crt is None:
            raise RuntimeError(f"Missing certificates for {service.value} chain")

        # Create full certificate chain (service cert + intermediate CA + root CA)
        # Recommended for internal PKI - self-contained and simpler deployment
        # Note: Ensure newlines between certificates since read() strips trailing whitespace
        chain_content = srv_crt + "\n" + int_crt + "\n" + root_crt + "\n"
        self._secrets_manager.write(
            f"{service.value}/server-chain.crt", chain_content, SecretKind.CERT
        )

        # Create certificate chain without root CA (service cert + intermediate CA only)
        # Industry standard for public CAs - requires root CA in client trust store
        chain_no_root_content = srv_crt + "\n" + int_crt + "\n"
        self._secrets_manager.write(
            f"{service.value}/server-chain-no-root.crt",
            chain_no_root_content,
            SecretKind.CERT,
        )

    def create_ca_bundle(self) -> bool:
        """Create CA bundle for client certificate validation.

        Returns:
            True if external PostgreSQL CA was included, False otherwise
        """
        # Read CA certificates from SecretsManager
        int_crt = self._secrets_manager.read("intermediate-ca.crt", SecretKind.CERT)
        root_crt = self._secrets_manager.read("root-ca.crt", SecretKind.CERT)

        if not int_crt or not root_crt:
            raise RuntimeError("CA certificates not found for bundle")

        # Build bundle content
        # Note: Ensure newlines between certificates since read() strips trailing whitespace
        bundle_content = int_crt + "\n" + root_crt + "\n"

        # Include external PostgreSQL CA if it exists (for Aiven, RDS, etc.)
        external_pg_ca = self._secrets_manager.read(
            "ca-bundle-postgres-external.crt", SecretKind.CERT
        )
        external_included = False
        if external_pg_ca:
            bundle_content += (
                "\n# External PostgreSQL CA Certificate\n" + external_pg_ca + "\n"
            )
            external_included = True

        # Store via SecretsManager
        self._secrets_manager.write("ca-bundle.crt", bundle_content, SecretKind.CERT)

        return external_included

    def ca_certificates_exist(self) -> bool:
        """Check if CA certificates exist."""
        return (
            self._secrets_manager.exists("root-ca.crt", SecretKind.CERT)
            and self._secrets_manager.exists("root-ca.key", SecretKind.CERT)
            and self._secrets_manager.exists("intermediate-ca.crt", SecretKind.CERT)
            and self._secrets_manager.exists("intermediate-ca.key", SecretKind.CERT)
        )

    def generate_pki_certificates(self, force_ca: bool = False) -> PKIGenerationResult:
        """Generate all PKI certificates.

        Args:
            force_ca: Force regeneration of CA certificates

        Returns:
            PKIGenerationResult with details of what was generated
        """
        result = PKIGenerationResult()

        # Check if CA certificates already exist
        ca_exists = self.ca_certificates_exist()

        if not ca_exists or force_ca:
            # Generate root and intermediate CAs
            self.generate_root_ca()
            result.root_ca_generated = True

            self.generate_intermediate_ca()
            result.intermediate_ca_generated = True

        # Generate service certificates
        for service in ServiceType:
            self.generate_service_certificate(service)
            result.services_generated.append(service.value)

            self.create_certificate_chain(service)
            result.chains_created.append(service.value)

        # Create CA bundle for client certificate validation
        result.external_ca_included = self.create_ca_bundle()
        result.ca_bundle_created = True

        return result
