import pytest
import typer

from src.cli.shared.console import with_error_handling
from src.cli.shared.errors import DeploymentError


def test_with_error_handling_handles_deployment_error():
    @with_error_handling
    def _command() -> None:
        raise DeploymentError("Boom", details="extra")

    with pytest.raises(typer.Exit) as excinfo:
        _command()

    assert excinfo.value.exit_code == 1


def test_with_error_handling_handles_keyboard_interrupt():
    @with_error_handling
    def _command() -> None:
        raise KeyboardInterrupt

    with pytest.raises(typer.Exit) as excinfo:
        _command()

    assert excinfo.value.exit_code == 130
