#!/usr/bin/env python3
"""
Health check script for Temporal worker.
Tests that the worker can connect to Temporal server.
"""

import asyncio
import sys

from temporalio.client import Client


async def check_temporal_health(url: str, namespace: str = "default") -> bool:
    """Check if Temporal server is accessible."""
    try:
        # Simply connecting and getting the client is enough to verify connectivity
        _client = await asyncio.wait_for(
            Client.connect(url, namespace=namespace),
            timeout=5.0,
        )
        # Connection successful means Temporal is accessible
        return True
    except Exception as e:
        print(f"Temporal health check failed: {e}", file=sys.stderr)
        return False


async def main() -> int:
    """Main health check entry point."""
    # Get Temporal URL from environment or use default
    import os

    temporal_url = os.getenv("PRODUCTION_TEMPORAL_URL") or os.getenv(
        "DEVELOPMENT_TEMPORAL_URL", "temporal:7233"
    )
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    if not temporal_url:
        print("Temporal URL not configured", file=sys.stderr)
        return 1

    healthy = await check_temporal_health(temporal_url, namespace)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
