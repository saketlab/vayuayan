"""The interactive menu shown when vayuayan runs in a terminal with no command."""

from __future__ import annotations

from typing import Callable, List, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

Execute = Callable[[List[str]], int]

_ITEMS = (
    ("1", "Air quality near me"),
    ("2", "Air quality for a place"),
    ("3", "History of a place"),
    ("4", "Find a station"),
    ("5", "Quit"),
)


def _ask_place(console: Console, question: str) -> Sequence[str]:
    """The words of a place, or none if the user typed nothing."""
    return Prompt.ask(question, console=console).split()


def _action(choice: str, console: Console) -> List[str]:
    """The command line of a menu choice; empty if the user gave no place."""
    if choice == "1":
        return ["live"]
    place = _ask_place(
        console,
        "Which place? (station or city)" if choice != "4" else "Search for",
    )
    if not place:
        return []
    if choice == "2":
        return ["live", *place]
    if choice == "4":
        return ["find", *place]
    year = Prompt.ask("Which year? (Enter for the last full year)", console=console)
    return ["history", *place, *([year] if year.strip() else [])]


def run_menu(console: Console, execute: Execute) -> int:
    """Show the menu until the user quits.

    Args:
        console: The console for the menu.
        execute: Runs one command line and returns its exit code.

    Returns:
        0 when the user quits.
    """
    lines = "\n".join(f"[bold]{key}[/bold]  {label}" for key, label in _ITEMS)
    while True:
        console.print(Panel(lines, title="vayuayan: air quality in India", width=52))
        choice = Prompt.ask(
            "Choose", choices=[key for key, _ in _ITEMS], console=console
        )
        if choice == "5":
            return 0
        command = _action(choice, console)
        if command:
            execute(command)
        console.print()
