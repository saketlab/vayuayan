"""What the live, history and find commands share."""

from __future__ import annotations

from typing import Optional

from .cli_places import PlaceResult
from .cli_results import CommandResult


def unresolved_place(command: str, place: PlaceResult) -> Optional[CommandResult]:
    """The result of a place that is not one station or city, else None."""
    if place.status == "not_found":
        message = f"No station or city matches '{place.query}'."
        return CommandResult(command, "not_found", {"query": place.query}, message)
    if place.status == "ambiguous":
        message = place.reason or f"Several places match '{place.query}'."
        data = {"query": place.query, "matches": [m.to_dict() for m in place.matches]}
        return CommandResult(command, "ambiguous", data, message)
    return None
