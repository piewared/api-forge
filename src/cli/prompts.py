"""CLI prompts for secret operations.

This module isolates Rich/Console dependency from the core secrets logic.
"""

from rich.console import Console
from rich.prompt import Confirm, Prompt


class ConsolePromptProvider:
    """Rich console-based prompt provider."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def prompt_for_secret(self, message: str) -> str:
        """Prompt user for a secret value."""
        return Prompt.ask(message, password=True, console=self.console)

    def confirm(self, message: str) -> bool:
        """Prompt user for yes/no confirmation."""
        return Confirm.ask(message, console=self.console, default=False)
