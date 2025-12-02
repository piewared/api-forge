"""Temporal client service for managing shared Temporal client state."""

from typing import TYPE_CHECKING

from loguru import logger

from src.app.runtime.context import get_config

if TYPE_CHECKING:
    from temporalio.client import Client


class TemporalClientService:
    """Service for managing shared Temporal client connection and state.

    This service provides a singleton-like client connection that can be shared
    across the application. Workflow-specific operations should use the BaseWorkflow
    class methods which provide proper type safety.

    Example:
        # In a route handler:
        temporal_service = Depends(get_temporal_service)
        client = await temporal_service.get_client()

        # Use BaseWorkflow class methods for type-safe operations:
        handle = await MyWorkflow.start_workflow(
            client,
            input=MyWorkflowInput(...),
            id="workflow-123"
        )
    """

    def __init__(self) -> None:
        """Initialize Temporal client service.

        Note: The actual client connection is lazy-loaded on first use
        to avoid blocking during application startup.
        """
        self._client: Client | None = None
        self._config = get_config().temporal
        self._connection_attempts = 0
        self._max_retry_attempts = 3

    @property
    def is_enabled(self) -> bool:
        """Check if Temporal service is enabled in configuration."""
        return self._config.enabled

    @property
    def namespace(self) -> str:
        """Get configured Temporal namespace."""
        return self._config.namespace

    @property
    def task_queue(self) -> str:
        """Get default task queue name."""
        return self._config.task_queue

    @property
    def url(self) -> str:
        """Get Temporal server URL."""
        return self._config.url

    async def get_client(self) -> Client:
        """Get or create Temporal client connection.

        Returns:
            Connected Temporal client instance

        Raises:
            RuntimeError: If Temporal is disabled in configuration
            Exception: If connection fails after retries
        """
        if not self._config.enabled:
            raise RuntimeError("Temporal service is disabled in configuration")

        if self._client is None:
            self._client = await self._connect()

        return self._client

    async def _connect(self) -> Client:
        """Establish connection to Temporal server with retry logic.

        Returns:
            Connected Temporal client

        Raises:
            Exception: If connection fails after max retries
        """
        from temporalio.client import Client, TLSConfig
        from temporalio.contrib.pydantic import pydantic_data_converter

        last_exception = None

        for attempt in range(1, self._max_retry_attempts + 1):
            try:
                # Prepare TLS configuration if enabled
                tls_config: TLSConfig | bool = False
                if self._config.tls:
                    # TODO: Add TLS certificate paths to config if needed
                    tls_config = TLSConfig(
                        # server_root_ca_cert=...,
                        # client_cert=...,
                        # client_private_key=...,
                    )
                    logger.info(
                        "Connecting to Temporal with TLS",
                        extra={
                            "url": self._config.url,
                            "namespace": self._config.namespace,
                            "attempt": attempt,
                        },
                    )
                else:
                    logger.info(
                        "Connecting to Temporal",
                        extra={
                            "url": self._config.url,
                            "namespace": self._config.namespace,
                            "attempt": attempt,
                        },
                    )

                # Create client connection
                client = await Client.connect(
                    self._config.url,
                    namespace=self._config.namespace,
                    tls=tls_config,
                    data_converter=pydantic_data_converter,
                )

                self._connection_attempts = attempt
                logger.info(
                    "Successfully connected to Temporal",
                    extra={
                        "namespace": self._config.namespace,
                        "attempts": attempt,
                    },
                )

                return client

            except Exception as e:
                last_exception = e
                logger.warning(
                    "Failed to connect to Temporal",
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "url": self._config.url,
                        "namespace": self._config.namespace,
                        "attempt": attempt,
                        "max_attempts": self._max_retry_attempts,
                    },
                )

                # Don't retry if this was the last attempt
                if attempt == self._max_retry_attempts:
                    break

        # All retries exhausted
        logger.error(
            "Failed to connect to Temporal after all retries",
            extra={
                "url": self._config.url,
                "namespace": self._config.namespace,
                "total_attempts": self._max_retry_attempts,
            },
        )
        raise last_exception or RuntimeError("Failed to connect to Temporal")

    async def health_check(self) -> bool:
        """Perform health check on Temporal connection.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self._config.enabled:
            logger.debug("Temporal service is disabled")
            return False

        try:
            client = await self.get_client()
            # Simple check - try to get workflow service
            # The client.workflow_service property exists and can be used for health checks
            _ = client.workflow_service
            return True

        except Exception as e:
            logger.error(
                "Temporal health check failed",
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return False

    async def reconnect(self) -> Client:
        """Force reconnection to Temporal server.

        Useful for recovery scenarios or after network issues.

        Returns:
            New connected Temporal client instance
        """
        logger.info("Forcing Temporal reconnection")
        await self.close()
        return await self.get_client()

    async def close(self) -> None:
        """Close Temporal client connection."""
        if self._client is not None:
            try:
                # Note: Temporal Python SDK client doesn't have a close() method
                # The connection is automatically managed. We just clear our reference.
                logger.info("Releasing Temporal client connection")
                self._client = None
            except Exception as e:
                logger.warning(
                    "Error releasing Temporal client",
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
