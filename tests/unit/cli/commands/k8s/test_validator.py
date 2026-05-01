"""Unit tests for the deployment validator module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.cli.deployment.helm_deployer.validator import (
    DeploymentValidator,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from src.infra.constants import DeploymentConstants
from src.infra.k8s.controller import JobInfo, PodInfo


class TestValidationResult:
    """Tests for the ValidationResult dataclass."""

    def test_empty_result_is_clean(self) -> None:
        """An empty validation result should be considered clean."""
        result = ValidationResult()
        assert result.is_clean is True
        assert result.has_errors is False
        assert result.requires_cleanup is False

    def test_result_with_warning_not_clean(self) -> None:
        """A result with warnings is not clean but doesn't require cleanup."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                title="Test warning",
                description="Test description",
                recovery_hint="Test hint",
            )
        )
        assert result.is_clean is False
        assert result.has_errors is False
        assert result.requires_cleanup is False

    def test_result_with_error_has_errors(self) -> None:
        """A result with errors has_errors but may not require cleanup."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                title="Test error",
                description="Test description",
                recovery_hint="Test hint",
            )
        )
        assert result.is_clean is False
        assert result.has_errors is True
        assert result.requires_cleanup is False

    def test_result_with_critical_requires_cleanup(self) -> None:
        """A result with critical issues requires cleanup."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                title="Test critical",
                description="Test description",
                recovery_hint="Test hint",
            )
        )
        assert result.is_clean is False
        assert result.has_errors is True
        assert result.requires_cleanup is True


class TestValidationIssue:
    """Tests for the ValidationIssue dataclass."""

    def test_issue_creation(self) -> None:
        """Test basic issue creation with required fields."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            title="Test Issue",
            description="This is a test issue",
            recovery_hint="Try this to fix it",
        )
        assert issue.severity == ValidationSeverity.WARNING
        assert issue.title == "Test Issue"
        assert issue.description == "This is a test issue"
        assert issue.recovery_hint == "Try this to fix it"
        # Empty strings are used as defaults instead of None
        assert issue.resource_type == ""
        assert issue.resource_name == ""

    def test_issue_with_resource_info(self) -> None:
        """Test issue creation with resource information."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            title="Failed Job",
            description="Job failed to complete",
            recovery_hint="Delete the job and retry",
            resource_type="job",
            resource_name="postgres-verifier",
        )
        assert issue.resource_type == "job"
        assert issue.resource_name == "postgres-verifier"


class TestDeploymentValidator:
    """Tests for the DeploymentValidator class."""

    @pytest.fixture
    def mock_commands(self) -> MagicMock:
        """Create a mock shell commands instance."""
        commands = MagicMock()
        commands.kubectl = MagicMock()
        commands.helm = MagicMock()
        return commands

    @pytest.fixture
    def mock_console(self) -> MagicMock:
        """Create a mock Rich console."""
        return MagicMock()

    @pytest.fixture
    def mock_controller(self) -> MagicMock:
        """Create a mock Kubernetes controller."""
        controller = MagicMock()
        controller.namespace_exists = MagicMock()
        controller.get_jobs = MagicMock()
        controller.get_pods = MagicMock()
        return controller

    @pytest.fixture
    def validator(
        self,
        mock_commands: MagicMock,
        mock_console: MagicMock,
        mock_controller: MagicMock,
    ) -> DeploymentValidator:
        """Create a validator instance with mocked dependencies."""
        return DeploymentValidator(
            commands=mock_commands,
            console=mock_console,
            controller=mock_controller,
            constants=DeploymentConstants(),
        )

    def test_validate_fresh_namespace(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """Validation of a non-existent namespace should return clean result."""
        mock_controller.namespace_exists.return_value = False

        result = validator.validate("api-forge-prod")

        assert result.is_clean is True
        assert result.namespace_exists is False
        assert len(result.issues) == 0

    def test_validate_existing_namespace_no_issues(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """Validation of existing namespace with no issues should be clean."""
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = []
        mock_controller.get_pods.return_value = []

        result = validator.validate("api-forge-prod")

        assert result.is_clean is True
        assert result.namespace_exists is True

    def test_validate_detects_failed_jobs(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """Validation should detect failed Kubernetes jobs.

        Init jobs like postgres-verifier are expected to have transient failures
        during startup, so they should be flagged as warnings, not errors.
        """
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = [
            JobInfo(name="postgres-verifier", status="Failed"),
        ]
        mock_controller.get_pods.return_value = []

        result = validator.validate("api-forge-prod")

        assert result.is_clean is False
        assert len(result.issues) == 1
        # Init jobs like postgres-verifier are expected to have transient failures
        # during startup, so they should be WARNING not ERROR
        assert result.issues[0].severity == ValidationSeverity.WARNING
        assert "postgres-verifier" in result.issues[0].title

    def test_validate_any_failed_job_is_warning(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """All failed jobs should be flagged as warnings (may be transient)."""
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = [
            JobInfo(name="migration-job", status="Failed"),
        ]
        mock_controller.get_pods.return_value = []

        result = validator.validate("api-forge-prod")

        assert result.is_clean is False
        assert len(result.issues) == 1
        # All failed jobs are warnings since they may be transient
        assert result.issues[0].severity == ValidationSeverity.WARNING
        assert "migration-job" in result.issues[0].title

    def test_validate_detects_crashloop_pods(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """Validation should detect pods in CrashLoopBackOff state."""
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = []
        mock_controller.get_pods.return_value = [
            PodInfo(name="api-forge-app-xyz", status="CrashLoopBackOff"),
        ]

        result = validator.validate("api-forge-prod")

        assert result.is_clean is False
        assert len(result.issues) == 1
        # CrashLoopBackOff is an ERROR severity in the implementation
        assert result.issues[0].severity == ValidationSeverity.ERROR
        assert "CrashLoopBackOff" in result.issues[0].title

    def test_validate_detects_pending_pods(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """Validation should detect pods stuck in Pending state."""
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = []
        mock_controller.get_pods.return_value = [
            PodInfo(name="api-forge-app-xyz", status="Pending"),
        ]

        result = validator.validate("api-forge-prod")

        assert result.is_clean is False
        assert len(result.issues) == 1
        assert result.issues[0].severity == ValidationSeverity.WARNING
        # Title uses lowercase "pending"
        assert "pending" in result.issues[0].title.lower()

    def test_validate_detects_error_pods(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """Validation should detect pods in Error state."""
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = []
        mock_controller.get_pods.return_value = [
            PodInfo(name="api-forge-app-xyz", status="Error"),
        ]

        result = validator.validate("api-forge-prod")

        assert result.is_clean is False
        assert len(result.issues) == 1
        assert result.issues[0].severity == ValidationSeverity.ERROR
        assert "Error" in result.issues[0].title

    def test_validate_job_pods_only_checks_most_recent(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """For job-owned pods, only the most recent pod should be checked.

        If old pods from a job are in Error state but a newer pod succeeded,
        we should not flag the old errors.
        """
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = []
        mock_controller.get_pods.return_value = [
            # Old pod from first attempt - failed
            PodInfo(
                name="postgres-verifier-abc",
                status="Error",
                job_owner="postgres-verifier",
                creation_timestamp="2025-01-01T10:00:00Z",
            ),
            # Newer pod from second attempt - succeeded
            PodInfo(
                name="postgres-verifier-def",
                status="Succeeded",
                job_owner="postgres-verifier",
                creation_timestamp="2025-01-01T10:05:00Z",
            ),
        ]

        result = validator.validate("api-forge-prod")

        # Should be clean - the most recent pod succeeded
        assert result.is_clean is True
        assert len(result.issues) == 0

    def test_validate_job_pods_flags_if_most_recent_failed(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """If the most recent job pod is in Error state, flag it as a warning."""
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = []
        mock_controller.get_pods.return_value = [
            # Old pod succeeded
            PodInfo(
                name="postgres-verifier-abc",
                status="Succeeded",
                job_owner="postgres-verifier",
                creation_timestamp="2025-01-01T10:00:00Z",
            ),
            # Newer pod failed
            PodInfo(
                name="postgres-verifier-def",
                status="Error",
                job_owner="postgres-verifier",
                creation_timestamp="2025-01-01T10:05:00Z",
            ),
        ]

        result = validator.validate("api-forge-prod")

        # Should flag the most recent failed pod as a warning
        assert result.is_clean is False
        assert len(result.issues) == 1
        assert result.issues[0].severity == ValidationSeverity.WARNING
        assert "postgres-verifier-def" in result.issues[0].title

    def test_validate_detects_multiple_issues(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """Validation should accumulate multiple issues."""
        mock_controller.namespace_exists.return_value = True
        mock_commands.helm.list_releases.return_value = []
        mock_controller.get_jobs.return_value = [
            JobInfo(name="postgres-verifier", status="Failed"),
        ]
        mock_controller.get_pods.return_value = [
            PodInfo(name="api-forge-app-xyz", status="CrashLoopBackOff"),
            PodInfo(name="api-forge-worker-abc", status="Pending"),
        ]

        result = validator.validate("api-forge-prod")

        assert result.is_clean is False
        assert len(result.issues) == 3
        # Should have 1 ERROR (crashloop), 2 WARNINGs (init job + pending)
        # postgres-verifier is an init job so it's a WARNING, not ERROR
        severities = [issue.severity for issue in result.issues]
        assert severities.count(ValidationSeverity.ERROR) == 1
        assert severities.count(ValidationSeverity.WARNING) == 2

    def test_display_results_clean(
        self,
        validator: DeploymentValidator,
        mock_console: MagicMock,
    ) -> None:
        """Display results should handle clean results gracefully."""
        result = ValidationResult()
        result.namespace_exists = True

        validator.display_results(result, "api-forge-prod")

        # Should print a success message
        mock_console.print.assert_called()
        call_args = str(mock_console.print.call_args_list)
        assert "passed" in call_args.lower() or "✓" in call_args

    def test_display_results_with_issues(
        self,
        validator: DeploymentValidator,
        mock_console: MagicMock,
    ) -> None:
        """Display results should show issues with formatting."""
        result = ValidationResult()
        result.namespace_exists = True
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                title="Test Error",
                description="Something went wrong",
                recovery_hint="Fix it",
            )
        )

        validator.display_results(result, "api-forge-prod")

        # Should print issue information
        mock_console.print.assert_called()
        call_count = mock_console.print.call_count
        assert call_count > 1  # Multiple print calls for formatted output

    def test_prompt_cleanup_returns_true_on_yes(
        self, validator: DeploymentValidator, mock_console: MagicMock
    ) -> None:
        """prompt_cleanup should return True when user enters 'y'."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                title="Critical Issue",
                description="Very bad",
                recovery_hint="Cleanup",
            )
        )

        with patch("builtins.input", return_value="y"):
            should_cleanup = validator.prompt_cleanup(result, "api-forge-prod")

        assert should_cleanup is True

    def test_prompt_cleanup_returns_false_on_no(
        self, validator: DeploymentValidator, mock_console: MagicMock
    ) -> None:
        """prompt_cleanup should return False when user enters 'n' or empty."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                title="Critical Issue",
                description="Very bad",
                recovery_hint="Cleanup",
            )
        )

        with patch("builtins.input", return_value="n"):
            should_cleanup = validator.prompt_cleanup(result, "api-forge-prod")

        assert should_cleanup is False

    def test_run_cleanup_uninstalls_helm_and_deletes_resources(
        self,
        validator: DeploymentValidator,
        mock_controller: MagicMock,
        mock_commands: MagicMock,
    ) -> None:
        """run_cleanup should uninstall Helm release and delete PVCs/namespace."""
        mock_commands.helm.uninstall.return_value = MagicMock(success=True)
        mock_controller.delete_pvcs.return_value = MagicMock(success=True)
        mock_controller.delete_namespace.return_value = MagicMock(success=True)

        result = validator.run_cleanup("api-forge-prod")

        assert result is True
        mock_commands.helm.uninstall.assert_called_once()
        mock_controller.delete_pvcs.assert_called_once_with("api-forge-prod")
        mock_controller.delete_namespace.assert_called_once()

    def test_run_cleanup_handles_failure(
        self,
        validator: DeploymentValidator,
        mock_commands: MagicMock,
        mock_console: MagicMock,
    ) -> None:
        """run_cleanup should handle cleanup failures gracefully."""
        mock_commands.helm.uninstall.side_effect = Exception("Helm error")

        result = validator.run_cleanup("api-forge-prod")

        assert result is False
        # Should call error method with failure message
        mock_console.error.assert_called_once()
        call_args = str(mock_console.error.call_args_list)
        assert "failed" in call_args.lower() or "error" in call_args.lower()
