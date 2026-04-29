"""Managed Postgres (MPG) mixin for Fly.io controller."""

from __future__ import annotations

from .base import FlyCtlBase
from .types import BackupInfo, CommandResult, ManagedPostgresInfo


class FlyManagedPostgresMixin(FlyCtlBase):
    """Managed Postgres operations: create, list, status, connect, proxy, attach, detach,
    connection_string, backup, restore, destroy."""

    async def mpg_create(
        self,
        name: str,
        region: str,
        *,
        plan: str = "basic",
        org: str | None = None,
        volume_size: int = 10,
        pg_major_version: int | None = None,
        enable_postgis: bool = False,
    ) -> CommandResult:
        """Create a Fly Managed Postgres cluster."""
        args = [
            "mpg",
            "create",
            "--name",
            name,
            "--region",
            region,
            "--plan",
            plan,
            "--volume-size",
            str(volume_size),
        ]
        if org:
            args.extend(["--org", org])
        if pg_major_version:
            args.extend(["--pg-major-version", str(pg_major_version)])
        if enable_postgis:
            args.append("--enable-postgis-support")
        return await self._run_flyctl(args)

    async def mpg_list(self, *, org: str | None = None) -> list[ManagedPostgresInfo]:
        """List Managed Postgres clusters."""
        args = ["mpg", "list"]
        if org:
            args.extend(["--org", org])

        success, data = await self._run_flyctl_json(args)
        if not success or not isinstance(data, list):
            return []

        return [
            ManagedPostgresInfo(
                id=item.get("id", ""),
                name=item.get("name", ""),
                region=item.get("region", ""),
                plan=item.get("plan", ""),
                status=item.get("status", ""),
                created_at=item.get("created_at", ""),
                connection_string=item.get("connection_string"),
            )
            for item in data
        ]

    async def mpg_status(self, cluster_id: str) -> ManagedPostgresInfo | None:
        """Get status of a Managed Postgres cluster."""
        success, data = await self._run_flyctl_json(["mpg", "status", cluster_id])
        if not success or not isinstance(data, dict):
            return None

        return ManagedPostgresInfo(
            id=data.get("id", ""),
            name=data.get("name", ""),
            region=data.get("region", ""),
            plan=data.get("plan", ""),
            status=data.get("status", ""),
            created_at=data.get("created_at", ""),
            connection_string=data.get("connection_string"),
        )

    async def mpg_connect(self, cluster_id: str) -> CommandResult:
        """Open psql connection to cluster (interactive)."""
        return await self._run_flyctl(
            ["mpg", "connect", cluster_id], capture_output=False
        )

    async def mpg_proxy(
        self,
        cluster_id: str,
        *,
        port: int = 5432,
    ) -> CommandResult:
        """Start local proxy to cluster."""
        return await self._run_flyctl(
            ["mpg", "proxy", cluster_id, "--port", str(port)],
            capture_output=False,
        )

    async def mpg_attach(
        self,
        cluster_id: str,
        app_name: str,
        *,
        database_name: str | None = None,
        variable_name: str = "DATABASE_URL",
    ) -> CommandResult:
        """Attach a Fly app to the cluster (sets DATABASE_URL secret)."""
        args = ["mpg", "attach", cluster_id, "-a", app_name]
        if database_name:
            args.extend(["--database-name", database_name])
        args.extend(["--variable-name", variable_name])
        return await self._run_flyctl(args)

    async def mpg_detach(self, cluster_id: str, app_name: str) -> CommandResult:
        """Detach a Fly app from the cluster."""
        return await self._run_flyctl(["mpg", "detach", cluster_id, "-a", app_name])

    async def mpg_connection_string(
        self,
        cluster_id: str,
        *,
        database_name: str | None = None,
        role: str | None = None,
    ) -> tuple[bool, str]:
        """Get connection string for a cluster."""
        args = ["mpg", "connection-string", cluster_id]
        if database_name:
            args.extend(["--database-name", database_name])
        if role:
            args.extend(["--role", role])

        result = await self._run_flyctl(args)
        if result.success:
            return True, result.stdout.strip()
        return False, result.stderr.strip()

    async def mpg_backup_create(self, cluster_id: str) -> CommandResult:
        """Create a backup of the cluster."""
        return await self._run_flyctl(["mpg", "backup", "create", cluster_id])

    async def mpg_backup_list(self, cluster_id: str) -> list[BackupInfo]:
        """List backups for a cluster."""
        success, data = await self._run_flyctl_json(
            ["mpg", "backup", "list", cluster_id]
        )
        if not success or not isinstance(data, list):
            return []

        return [
            BackupInfo(
                id=item.get("id", ""),
                status=item.get("status", ""),
                created_at=item.get("created_at", ""),
                size_bytes=item.get("size_bytes", 0),
            )
            for item in data
        ]

    async def mpg_backup_restore(
        self,
        cluster_id: str,
        backup_id: str,
    ) -> CommandResult:
        """Restore cluster from a backup."""
        return await self._run_flyctl(
            ["mpg", "restore", cluster_id, "--backup-id", backup_id]
        )

    async def mpg_destroy(
        self,
        cluster_id: str,
        *,
        confirm: bool = False,
    ) -> CommandResult:
        """Destroy a Managed Postgres cluster."""
        args = ["mpg", "destroy", cluster_id]
        if confirm:
            args.append("--yes")
        return await self._run_flyctl(args)
