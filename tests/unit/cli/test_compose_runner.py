"""Tests for ComposeRunner helper."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.cli.shared.compose import ComposeRunner


@pytest.fixture
def compose_runner():
    """Create a ComposeRunner instance for testing."""
    return ComposeRunner(
        Path("/test/project"),
        compose_file=Path("/test/project/docker-compose.test.yml"),
        project_name="test-project",
    )


@pytest.fixture
def compose_runner_no_project():
    """Create a ComposeRunner without project name."""
    return ComposeRunner(
        Path("/test/project"),
        compose_file=Path("/test/project/docker-compose.yml"),
    )


def test_base_cmd_with_project_name(compose_runner):
    """Test that base command includes project name when provided."""
    cmd = compose_runner._base_cmd()

    assert cmd == [
        "docker",
        "compose",
        "-p",
        "test-project",
        "-f",
        "/test/project/docker-compose.test.yml",
    ]


def test_base_cmd_without_project_name(compose_runner_no_project):
    """Test that base command works without project name."""
    cmd = compose_runner_no_project._base_cmd()

    assert cmd == [
        "docker",
        "compose",
        "-f",
        "/test/project/docker-compose.yml",
    ]


@patch("subprocess.run")
def test_run_executes_command(mock_run, compose_runner):
    """Test that run() executes subprocess with correct arguments."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.run(["up", "-d"])

    mock_run.assert_called_once()
    call_args = mock_run.call_args

    expected_cmd = [
        "docker",
        "compose",
        "-p",
        "test-project",
        "-f",
        "/test/project/docker-compose.test.yml",
        "up",
        "-d",
    ]

    assert call_args.args[0] == expected_cmd
    assert call_args.kwargs["cwd"] == Path("/test/project")
    assert call_args.kwargs["text"] is True


@patch("subprocess.run")
def test_run_with_capture_output(mock_run, compose_runner):
    """Test that run() respects capture_output flag."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="output", stderr=""
    )

    compose_runner.run(["ps"], capture_output=True)

    assert mock_run.call_args.kwargs["capture_output"] is True


@patch("subprocess.run")
def test_run_with_check(mock_run, compose_runner):
    """Test that run() respects check flag."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.run(["up"], check=True)

    assert mock_run.call_args.kwargs["check"] is True


@patch("subprocess.run")
def test_logs_without_service(mock_run, compose_runner):
    """Test logs() without specific service."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.logs()

    expected_cmd = [
        "docker",
        "compose",
        "-p",
        "test-project",
        "-f",
        "/test/project/docker-compose.test.yml",
        "logs",
    ]

    assert mock_run.call_args.args[0] == expected_cmd


@patch("subprocess.run")
def test_logs_with_service(mock_run, compose_runner):
    """Test logs() with specific service."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.logs(service="postgres")

    cmd = mock_run.call_args.args[0]
    assert cmd[-1] == "postgres"


@patch("subprocess.run")
def test_logs_with_follow(mock_run, compose_runner):
    """Test logs() with follow flag."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.logs(follow=True)

    cmd = mock_run.call_args.args[0]
    assert "--follow" in cmd


@patch("subprocess.run")
def test_logs_with_tail(mock_run, compose_runner):
    """Test logs() with tail option."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.logs(tail=50)

    cmd = mock_run.call_args.args[0]
    assert "--tail=50" in cmd


@patch("subprocess.run")
def test_logs_with_all_options(mock_run, compose_runner):
    """Test logs() with all options combined."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.logs(service="app", follow=True, tail=100)

    cmd = mock_run.call_args.args[0]
    assert "--tail=100" in cmd
    assert "--follow" in cmd
    assert cmd[-1] == "app"


@patch("subprocess.run")
def test_restart_without_service(mock_run, compose_runner):
    """Test restart() without specific service."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.restart()

    expected_cmd = [
        "docker",
        "compose",
        "-p",
        "test-project",
        "-f",
        "/test/project/docker-compose.test.yml",
        "restart",
    ]

    assert mock_run.call_args.args[0] == expected_cmd


@patch("subprocess.run")
def test_restart_with_service(mock_run, compose_runner):
    """Test restart() with specific service."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.restart(service="redis")

    cmd = mock_run.call_args.args[0]
    assert cmd[-1] == "redis"


@patch("subprocess.run")
def test_build_without_service(mock_run, compose_runner):
    """Test build() without specific service."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.build()

    expected_cmd = [
        "docker",
        "compose",
        "-p",
        "test-project",
        "-f",
        "/test/project/docker-compose.test.yml",
        "build",
    ]

    assert mock_run.call_args.args[0] == expected_cmd


@patch("subprocess.run")
def test_build_with_service(mock_run, compose_runner):
    """Test build() with specific service."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.build(service="app")

    cmd = mock_run.call_args.args[0]
    assert cmd[-1] == "app"


@patch("subprocess.run")
def test_build_with_no_cache(mock_run, compose_runner):
    """Test build() with no_cache flag."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.build(no_cache=True)

    cmd = mock_run.call_args.args[0]
    assert "--no-cache" in cmd


@patch("subprocess.run")
def test_build_with_service_and_no_cache(mock_run, compose_runner):
    """Test build() with both service and no_cache."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )

    compose_runner.build(service="app", no_cache=True)

    cmd = mock_run.call_args.args[0]
    assert "--no-cache" in cmd
    assert cmd[-1] == "app"


@patch("subprocess.run")
def test_check_flag_propagates_exceptions(mock_run, compose_runner):
    """Test that check=True causes CalledProcessError to be raised."""
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["docker", "compose", "up"]
    )

    with pytest.raises(subprocess.CalledProcessError):
        compose_runner.run(["up"], check=True)
