#!/usr/bin/env python3
"""Command-line interface of vayuayan: routing only.

Commands live in commands.py and return plain data; cli_render.py draws it.
"""

import argparse
import json
import logging
import os
import re
import sys
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from typing import Callable, Dict, Iterator, List, Optional, Sequence

from rich.console import Console
from rich.prompt import IntPrompt, Prompt

from . import CPCBHistorical, CPCBLive, PM25Client, commands
from .cli_menu import run_menu
from .cli_parser import UsageError, build_parser
from .cli_places import PlaceResult, choose
from .cli_render import make_console, render, render_matches
from .cli_results import CommandResult
from .commands import HistoryRequest, ReportRequest
from .commands_report import FREQUENCIES

_YEAR_WORD = re.compile(r"(?:19|20)\d{2}$")
_EXIT_INTERRUPTED = 130


@dataclass(frozen=True)
class _Context:
    """What the commands need from the session."""

    out: Console
    err: Console
    json: bool
    interactive: bool
    debug: bool


def _stdin_is_terminal() -> bool:
    """True if a person can answer a prompt."""
    return sys.stdin.isatty()


def _stdout_is_terminal() -> bool:
    """True if a person sees the output."""
    return sys.stdout.isatty()


@contextmanager
def _busy(ctx: _Context, message: str) -> Iterator[Callable[[str], None]]:
    """A spinner on stderr; without a terminal, progress goes there as text."""
    if not ctx.err.is_terminal:
        yield lambda text: ctx.err.print(text, markup=False)
        return
    with ctx.err.status(message) as status:
        yield lambda text: status.update(text)


def _settle(ctx: _Context, place: PlaceResult) -> PlaceResult:
    """Ask the user to pick when a name is ambiguous and asking is allowed."""
    if place.status != "ambiguous" or not ctx.interactive:
        return place
    ctx.err.print(
        place.reason or f"Several places match '{place.query}':", markup=False
    )
    render_matches([m.to_dict() for m in place.matches], ctx.err)
    count = len(place.matches)
    number = IntPrompt.ask(
        f"Which one? (1-{count})",
        console=ctx.err,
        choices=[str(i) for i in range(1, count + 1)],
        show_choices=False,
    )
    return choose(place, number - 1)


def _lookup(
    ctx: _Context, args: argparse.Namespace, words: Sequence[str]
) -> PlaceResult:
    """The place a command was given, after any choice the user made."""
    with _busy(ctx, "Looking up the place..."):
        place = commands.lookup_place(
            CPCBHistorical(), " ".join(words), args.city, args.state
        )
    if place.others:
        assert place.station is not None
        ctx.err.print(
            f"Using {place.station.name}. Also: "
            + "; ".join(f"{s.name} (--city {s.city})" for s in place.others),
            markup=False,
        )
    return _settle(ctx, place)


def _with_others(result: CommandResult, place: PlaceResult) -> CommandResult:
    """The result, naming any same-named stations the place was chosen over."""
    if not place.others:
        return result
    others = [s.to_dict() for s in place.others]
    return replace(result, data={**result.data, "also_matches": others})


def _live_for(ctx: _Context, place: PlaceResult, save: str) -> CommandResult:
    """The live reading of a resolved place."""
    with _busy(ctx, "Fetching the latest reading..."):
        return _with_others(commands.live_place(CPCBLive(), place, save=save), place)


def _live(ctx: _Context, args: argparse.Namespace) -> CommandResult:
    if args.words or args.city:
        return _live_for(ctx, _lookup(ctx, args, args.words or [args.city]), args.save)
    if args.state:
        raise UsageError("--state narrows a place; give a place too")
    if (args.lat is None) != (args.lon is None):
        raise UsageError("--lat and --lon go together")
    coords = None if args.lat is None else (args.lat, args.lon)
    with _busy(ctx, "Finding the nearest station..."):
        result = commands.live_near(CPCBLive(), coords, save=args.save)
    if result.status != "location_unknown" or not ctx.interactive:
        return result
    ctx.err.print(result.message, markup=False)
    reply = Prompt.ask("Which place? (station or city)", console=ctx.err).split()
    return _live_for(ctx, _lookup(ctx, args, reply), args.save) if reply else result


def _report_request(args: argparse.Namespace, year: Optional[int]) -> ReportRequest:
    """The period of a history command with --from and --to."""
    if year is not None:
        raise UsageError("give a YEAR or --from and --to, not both")
    if not args.start or not args.end:
        raise UsageError("a period needs both --from and --to")
    if args.standard == "us" or args.computed or args.bulletin or args.month:
        raise UsageError(
            "--from and --to give readings; they do not combine with "
            "--standard us, --computed, --bulletin or --month"
        )
    every = "hourly" if args.hourly else args.every or "hourly"
    names = None
    if args.pollutants:
        names = tuple(p.strip() for p in args.pollutants.split(","))
    return ReportRequest(args.start, args.end, FREQUENCIES[every], names, args.save)


def _history(ctx: _Context, args: argparse.Namespace) -> CommandResult:
    words: List[str] = list(args.words)
    year: Optional[int] = None
    if len(words) > 1 and _YEAR_WORD.match(words[-1]):
        year = int(words.pop())
    client = CPCBHistorical()

    if any((args.start, args.end, args.every, args.hourly, args.pollutants)):
        report = _report_request(args, year)
        place = _lookup(ctx, args, words)
        with _busy(ctx, "Downloading the report...") as progress:
            result = commands.history_report(client, place, report, progress)
            return _with_others(result, place)

    request = HistoryRequest(
        year=year if year is not None else date.today().year - 1,
        month=args.month,
        standard=args.standard,
        computed=args.computed or args.bulletin,
        bulletin=args.bulletin,
        save=args.save,
    )
    place = _settle(ctx, commands.place_for_request(_lookup(ctx, args, words), request))
    with _busy(ctx, "Downloading the daily AQI...") as progress:
        return _with_others(commands.history(client, place, request, progress), place)


def _find(ctx: _Context, args: argparse.Namespace) -> CommandResult:
    with _busy(ctx, "Searching..."):
        place = commands.lookup_place(CPCBHistorical(), " ".join(args.words))
        return commands.find_stations(place, args.save)


def _stations(ctx: _Context, args: argparse.Namespace) -> CommandResult:
    with _busy(ctx, "Loading stations..."):
        return commands.list_stations(
            CPCBHistorical(), args.city, args.state, args.save
        )


def _pm25(ctx: _Context, args: argparse.Namespace) -> CommandResult:
    with _busy(ctx, "Calculating PM2.5..."):
        return commands.pm25_stats(
            PM25Client(version=args.version, region=args.region),
            args.geojson,
            args.year,
            args.month,
            args.group_by,
        )


_HANDLERS: Dict[str, Callable[[_Context, argparse.Namespace], CommandResult]] = {
    "live": _live,
    "history": _history,
    "find": _find,
    "stations": _stations,
    "pm25": _pm25,
}


def _print_document(result: CommandResult) -> None:
    """Write the one JSON document of this run."""
    sys.stdout.write(json.dumps(result.to_document(), ensure_ascii=False) + "\n")


def _emit(ctx: _Context, args: argparse.Namespace, result: CommandResult) -> int:
    """Print a result as JSON or for people, and return its exit code."""
    if ctx.json:
        _print_document(result)
    else:
        limit = None if getattr(args, "all", False) else getattr(args, "limit", None)
        render(result, ctx.out, ctx.err, limit)
    return result.exit_code


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    """Parse argv; words left over after an option belong to the place."""
    parser = build_parser()
    args, extras = parser.parse_known_args(list(argv))
    if extras:
        takes_words = hasattr(args, "words")
        unknown = [e for e in extras if e.startswith("-") or not takes_words]
        if unknown:
            message = f"unrecognised: {' '.join(unknown)}"
            raise UsageError(message, parser.format_usage())
        args.words = [*args.words, *extras]
    return args


def _run_command(ctx: _Context, args: argparse.Namespace) -> int:
    """Run one parsed command, turning every failure into a result."""
    try:
        return _emit(ctx, args, _HANDLERS[args.command](ctx, args))
    except (UsageError, BrokenPipeError):
        raise
    except (KeyboardInterrupt, EOFError):
        ctx.err.print("Stopped.")
        return _EXIT_INTERRUPTED
    except Exception as error:
        if ctx.debug:
            ctx.err.print_exception()
        return _emit(ctx, args, commands.error_result(args.command, error))


def _usage_failure(error: UsageError, as_json: bool, err: Console) -> int:
    """Report a wrong command line."""
    if as_json:
        _print_document(CommandResult("usage", "usage_error", message=str(error)))
    else:
        if error.usage:
            err.print(error.usage.rstrip(), markup=False)
        err.print(f"vayuayan: error: {error}", markup=False)
    return 2


def _menu(ctx: _Context) -> int:
    """The interactive menu, until the user quits or presses Ctrl-C."""

    def execute(command: List[str]) -> int:
        try:
            return _run_command(ctx, _parse(command))
        except UsageError as error:
            return _usage_failure(error, False, ctx.err)

    try:
        return run_menu(ctx.out, execute)
    except (KeyboardInterrupt, EOFError):
        ctx.err.print("Stopped.")
        return _EXIT_INTERRUPTED


def run(
    argv: Optional[Sequence[str]] = None,
    out: Optional[Console] = None,
    err: Optional[Console] = None,
) -> int:
    """Run the CLI and return the process exit code.

    Args:
        argv: The arguments; sys.argv is used by default.
        out: Console for results.
        err: Console for progress, prompts and problems.

    Returns:
        The exit code.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    out = out or make_console()
    err = err or make_console(stderr=True)
    as_json = "--json" in arguments
    try:
        args = _parse(arguments)
    except UsageError as error:
        return _usage_failure(error, as_json, err)

    # A prompt would corrupt a --json document and hang a script without a terminal
    interactive = _stdin_is_terminal() and not args.no_input and not args.json
    ctx = _Context(out, err, args.json, interactive, args.debug)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(message)s",
        stream=sys.stderr,
    )
    warnings.filterwarnings("ignore", message="Workbook contains no default style")

    if not args.command:
        if ctx.interactive and _stdout_is_terminal():
            return _menu(ctx)
        if args.json:
            return _usage_failure(UsageError("no command given"), True, err)
        out.print(build_parser().format_help(), markup=False)
        return 2
    try:
        return _run_command(ctx, args)
    except UsageError as error:
        return _usage_failure(error, as_json, err)


def main() -> None:
    """Entry point of the CLI."""
    try:
        code = run()
    except BrokenPipeError:
        # the reader of a pipe left, such as head; not a failure
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
