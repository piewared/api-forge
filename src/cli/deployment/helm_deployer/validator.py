"""Pre-deployment validation for Kubernetes deployments.

This module provides validation checks to detect deployment state issues
before attempting a new deployment, such as:
- Failed jobs from previous deployments
- Pods in error states
- Database initialization issues
- Stale PVC states

When issues are detected, users are prompted to clean up before proceeding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

    from ..shell_commands import ShellCommands
    from .constants import DeploymentConstants


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    WARNING = "warning"  # Can proceed, but may cause problems
    ERROR = "error"  # Should clean up before proceeding
    CRITICAL = "critical"  # Must clean up, cannot proceed


@dataclass
class ValidationIssue:
    """Represents a detected deployment issue."""

    severity: ValidationSeverity
    title: str
    description: str
    recovery_hint: str
    resource_type: str = ""
    resource_name: str = ""


@dataclass
class ValidationResult:
    """Result of pre-deployment validation."""

    issues: list[ValidationIssue] = field(default_factory=list)
    namespace_exists: bool = False
    has_previous_deployment: bool = False

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return any(
            i.severity in (ValidationSeverity.ERROR, ValidationSeverity.CRITICAL)
            for i in self.issues
        )

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)

    @property
    def is_clean(self) -> bool:
        """Check if the state is clean for deployment."""
        return len(self.issues) == 0

    @property
    def requires_cleanup(self) -> bool:
        """Check if cleanup is required before proceeding."""
        return any(i.severity == ValidationSeverity.CRITICAL for i in self.issues)


class DeploymentValidator:
    """Validates Kubernetes deployment state before deployment.

    Performs checks for:
    - Failed jobs that need cleanup
    - Pods in CrashLoopBackOff or Error states
    - Previous deployment issues
    - Database initialization problems

    Provides user-friendly prompts for cleanup when issues are detected.
    """

    def __init__(
        self,
        commands: ShellCommands,
        console: Console,
        constants: DeploymentConstants,
    ) -> None:
        """Initialize the validator.

        Args:
            commands: Shell command executor
            console: Rich console for output
            constants: Deployment constants
        """
        self.commands = commands
        self.console = console
        self.constants = constants

    def validate(self, namespace: str) -> ValidationResult:
        """Run all pre-deployment validation checks.

        Args:
            namespace: Target Kubernetes namespace

        Returns:
            ValidationResult containing any detected issues
        """
        result = ValidationResult()

        # Check if namespace exists
        result.namespace_exists = self._namespace_exists(namespace)
        if not result.namespace_exists:
            # Fresh deployment, no validation needed
            return result

        # Check for previous Helm release
        result.has_previous_deployment = self._has_helm_release(namespace)

        # Run validation checks
        self._check_failed_jobs(namespace, result)
        self._check_crashloop_pods(namespace, result)
        self._check_pending_pods(namespace, result)
        self._check_error_pods(namespace, result)

        return result

    def display_results(self, result: ValidationResult, namespace: str) -> None:
        """Display validation results to the user.

        Args:
            result: Validation result to display
            namespace: Target namespace (for cleanup hints)
        """
        if result.is_clean:
            if result.namespace_exists:
                self.console.print("[dim]✓ Pre-deployment checks passed[/dim]")
            return

        self.console.print(
            "\n[bold yellow]⚠️  Pre-deployment Issues Detected[/bold yellow]\n"
        )

        for issue in result.issues:
            icon = self._get_severity_icon(issue.severity)
            color = self._get_severity_color(issue.severity)

            self.console.print(f"[{color}]{icon} {issue.title}[/{color}]")
            self.console.print(f"   [dim]{issue.description}[/dim]")
            if issue.resource_name:
                self.console.print(
                    f"   [dim]Resource: {issue.resource_type}/{issue.resource_name}[/dim]"
                )
            self.console.print(f"   [cyan]💡 {issue.recovery_hint}[/cyan]")
            self.console.print()

    def prompt_cleanup(self, result: ValidationResult, namespace: str) -> bool:
        """Prompt user to clean up issues before proceeding.

        Args:
            result: Validation result with issues
            namespace: Target namespace

        Returns:
            True if user wants to proceed with cleanup, False to abort
        """
        if result.is_clean:
            return True

        if result.requires_cleanup:
            self.console.print(
                "[bold red]Critical issues detected. Cleanup required before deployment.[/bold red]\n"
            )
            self.console.print(
                "[yellow]Recommended: Run the following command to clean up:[/yellow]"
            )
            self.console.print(
                "[bold cyan]  uv run api-forge-cli deploy down k8s --volumes[/bold cyan]\n"
            )
            self.console.print(
                "[dim]This will delete all resources and persistent volumes, "
                "allowing a fresh deployment.[/dim]\n"
            )

            # Prompt user
            try:
                response = (
                    input("Would you like to run cleanup now? [y/N]: ").strip().lower()
                )
                return response in ("y", "yes")
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[dim]Deployment cancelled.[/dim]")
                return False

        elif result.has_errors:
            self.console.print(
                "[bold yellow]Errors detected that may cause deployment issues.[/bold yellow]\n"
            )
            self.console.print("[yellow]Consider running cleanup first:[/yellow]")
            self.console.print(
                "[bold cyan]  uv run api-forge-cli deploy down k8s --volumes[/bold cyan]\n"
            )

            try:
                response = (
                    input("Proceed with deployment anyway? [y/N]: ").strip().lower()
                )
                return response in ("y", "yes")
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[dim]Deployment cancelled.[/dim]")
                return False

        else:
            # Only warnings, continue with notification
            self.console.print(
                "[dim]Warnings detected but proceeding with deployment.[/dim]\n"
            )
            return True

    def run_cleanup(self, namespace: str) -> bool:
        """Run cleanup to remove deployment and volumes.

        Args:
            namespace: Target namespace to clean up

        Returns:
            True if cleanup succeeded, False otherwise
        """
        self.console.print(
            f"\n[bold red]🧹 Cleaning up namespace {namespace}...[/bold red]"
        )

        try:
            # Uninstall Helm release first
            helm_result = self.commands.helm.uninstall(
                self.constants.HELM_RELEASE_NAME, namespace
            )
            if helm_result.success:
                self.console.print(
                    f"[green]✓ Helm release '{self.constants.HELM_RELEASE_NAME}' uninstalled[/green]"
                )
            else:
                self.console.print(
                    "[dim]Helm release not found or already removed[/dim]"
                )

            # Delete PVCs
            pvc_result = self.commands.kubectl.delete_pvcs(namespace)
            if pvc_result.success:
                self.console.print("[green]✓ Persistent volume claims deleted[/green]")

            # Delete namespace
            ns_result = self.commands.kubectl.delete_namespace(
                namespace, timeout="120s"
            )
            if ns_result.success:
                self.console.print(f"[green]✓ Namespace {namespace} deleted[/green]")

            self.console.print(
                "\n[bold green]✓ Cleanup complete. You can now run deployment again.[/bold green]"
            )
            return True

        except Exception as e:
            self.console.print(f"[red]✗ Cleanup failed: {e}[/red]")
            self.console.print(
                f"[yellow]💡 Try manual cleanup: kubectl delete namespace {namespace}[/yellow]"
            )
            return False

    # =========================================================================
    # Validation Checks
    # =========================================================================

    def _namespace_exists(self, namespace: str) -> bool:
        """Check if the namespace exists."""
        result = self.commands.kubectl.namespace_exists(namespace)
        return result

    def _has_helm_release(self, namespace: str) -> bool:
        """Check if there's an existing Helm release."""
        releases = self.commands.helm.list_releases(namespace)
        return any(r.name == self.constants.HELM_RELEASE_NAME for r in releases)

    def _check_failed_jobs(self, namespace: str, result: ValidationResult) -> None:
        """Check for failed jobs in the namespace."""
        jobs = self.commands.kubectl.get_jobs(namespace)

        for job in jobs:
            if job.get("status") == "Failed":
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        title=f"Failed job: {job['name']}",
                        description=(
                            f"Job '{job['name']}' failed. This may indicate "
                            "initialization or configuration problems."
                        ),
                        recovery_hint=(
                            "Delete the failed job and redeploy, or run full cleanup "
                            "with 'deploy down k8s --volumes'"
                        ),
                        resource_type="Job",
                        resource_name=job["name"],
                    )
                )

    def _check_crashloop_pods(self, namespace: str, result: ValidationResult) -> None:
        """Check for pods in CrashLoopBackOff state."""
        pods = self.commands.kubectl.get_pods(namespace)

        for pod in pods:
            if pod.get("status") == "CrashLoopBackOff":
                restarts = pod.get("restarts", 0)
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        title=f"Pod in CrashLoopBackOff: {pod['name']}",
                        description=(
                            f"Pod '{pod['name']}' is crash-looping ({restarts} restarts). "
                            "This usually indicates configuration or dependency issues."
                        ),
                        recovery_hint=(
                            "Check pod logs with 'kubectl logs {name} -n {namespace}', "
                            "then fix the issue or run cleanup"
                        ).format(name=pod["name"], namespace=namespace),
                        resource_type="Pod",
                        resource_name=pod["name"],
                    )
                )

    def _check_pending_pods(self, namespace: str, result: ValidationResult) -> None:
        """Check for pods stuck in Pending state."""
        pods = self.commands.kubectl.get_pods(namespace)

        for pod in pods:
            if pod.get("status") == "Pending":
                # Check if it's been pending for a while (ignore recently created)
                # For now, treat all Pending as warnings
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        title=f"Pod pending: {pod['name']}",
                        description=(
                            f"Pod '{pod['name']}' is stuck in Pending state. "
                            "This may indicate resource constraints or scheduling issues."
                        ),
                        recovery_hint=(
                            "Check events with 'kubectl describe pod {name} -n {namespace}'"
                        ).format(name=pod["name"], namespace=namespace),
                        resource_type="Pod",
                        resource_name=pod["name"],
                    )
                )

    def _check_error_pods(self, namespace: str, result: ValidationResult) -> None:
        """Check for pods in Error state."""
        pods = self.commands.kubectl.get_pods(namespace)

        for pod in pods:
            if pod.get("status") == "Error":
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        title=f"Pod in Error state: {pod['name']}",
                        description=(
                            f"Pod '{pod['name']}' is in Error state. "
                            "Check logs to determine the cause."
                        ),
                        recovery_hint=(
                            "Check pod logs with 'kubectl logs {name} -n {namespace}', "
                            "then fix the issue or run cleanup"
                        ).format(name=pod["name"], namespace=namespace),
                        resource_type="Pod",
                        resource_name=pod["name"],
                    )
                )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_severity_icon(self, severity: ValidationSeverity) -> str:
        """Get icon for severity level."""
        icons = {
            ValidationSeverity.WARNING: "⚠️ ",
            ValidationSeverity.ERROR: "❌",
            ValidationSeverity.CRITICAL: "🚫",
        }
        return icons.get(severity, "•")

    def _get_severity_color(self, severity: ValidationSeverity) -> str:
        """Get color for severity level."""
        colors = {
            ValidationSeverity.WARNING: "yellow",
            ValidationSeverity.ERROR: "red",
            ValidationSeverity.CRITICAL: "bold red",
        }
        return colors.get(severity, "white")
