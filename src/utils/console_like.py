from __future__ import annotations

from typing import Protocol

from rich.console import ConsoleRenderable


class ConsoleLike(Protocol):
    def print(self, msg: ConsoleRenderable | str | None = None) -> None: ...

    def info(self, msg: str) -> None: ...

    def warn(self, msg: str) -> None: ...

    def error(self, msg: str) -> None: ...

    def ok(self, msg: str) -> None: ...


class StdoutConsole:
    """Minimal console fallback.

    Keeps infrastructure code usable without importing the CLI console.
    """

    def print(self, msg: ConsoleRenderable | str | None = None) -> None:
        print(msg)

    def info(self, msg: str) -> None:
        print(msg)

    def warn(self, msg: str) -> None:
        print(msg)

    def error(self, msg: str) -> None:
        print(msg)

    def ok(self, msg: str) -> None:
        print(msg)


def coalesce_console(console: ConsoleLike | None) -> ConsoleLike:
    return console if console is not None else StdoutConsole()
