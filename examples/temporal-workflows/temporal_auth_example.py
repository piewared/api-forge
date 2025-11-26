"""
Temporal client configuration with mTLS and JWT authentication for production.
"""

import os
from pathlib import Path

from temporalio.client import Client, TLSConfig


class TemporalClientConfig:
    """Production-ready Temporal client configuration with authentication."""

    def __init__(self):
        self.temporal_url = os.getenv("TEMPORAL_URL", "temporal:7233")
        self.tls_enabled = os.getenv("TEMPORAL_TLS_ENABLED", "false").lower() == "true"
        self.certs_dir = Path("/etc/temporal/certs")

    async def get_client(self) -> Client:
        """Get authenticated Temporal client."""
        if self.tls_enabled:
            return await self._get_secure_client()
        else:
            # Development/insecure mode
            return await Client.connect(self.temporal_url)

    async def _get_secure_client(self) -> Client:
        """Get Temporal client with mTLS and JWT authentication."""

        # Read TLS certificates
        client_cert = self._read_cert_file("temporal-client.crt")
        client_key = self._read_cert_file("temporal-client.key")
        ca_cert = self._read_cert_file("ca.crt")

        # Read JWT token
        jwt_token = self._read_cert_file("client-token.jwt")

        # Configure TLS
        tls_config = TLSConfig(
            client_cert=client_cert,
            client_private_key=client_key,
            server_root_ca_cert=ca_cert,
            domain="temporal-server",  # Must match certificate CN
        )

        # Connect with authentication
        client = await Client.connect(
            self.temporal_url,
            tls=tls_config,
            rpc_metadata={"authorization": f"Bearer {jwt_token}"},
        )

        return client

    def _read_cert_file(self, filename: str) -> bytes:
        """Read certificate file content."""
        cert_path = self.certs_dir / filename

        if not cert_path.exists():
            raise FileNotFoundError(f"Certificate file not found: {cert_path}")

        return cert_path.read_bytes()


# Example usage in your FastAPI application
async def get_temporal_client() -> Client:
    """Dependency to get Temporal client."""
    config = TemporalClientConfig()
    return await config.get_client()


# Example workflow execution with authentication
async def start_workflow_example():
    """Example of starting a workflow with authenticated client."""

    client = await get_temporal_client()

    try:
        # Start a workflow
        handle = await client.start_workflow(
            "my-workflow",
            "input-data",
            id="workflow-id-123",
            task_queue="my-task-queue",
        )

        print(f"Started workflow: {handle.id}")

        # Wait for result
        result = await handle.result()
        print(f"Workflow result: {result}")

    finally:
        # await client.close()
        pass


# Environment variables for Temporal configuration
REQUIRED_ENV_VARS = {
    "TEMPORAL_URL": "temporal:7233",
    "TEMPORAL_TLS_ENABLED": "true",
}

# Temporal authentication roles mapping
TEMPORAL_ROLES = {
    "temporal-system": "Full admin access to all namespaces and operations",
    "temporal-worker": "Can execute workflows and activities",
    "temporal-client": "Can start workflows and query status",
}

# Example environment configuration for .env file
ENV_EXAMPLE = """
# Temporal Configuration
TEMPORAL_URL=temporal:7233
TEMPORAL_TLS_ENABLED=true

# Temporal certificates are mounted at /etc/temporal/certs/ in containers
# Generated automatically by the temporal container on first startup
"""
