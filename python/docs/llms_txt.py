"""Write llms.txt at docs build: llms_header.md, then the public API from __all__."""

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent


def _summary(obj: Any) -> str:
    return (inspect.getdoc(obj) or "").split("\n\n")[0].replace("\n", " ")


def _signature(name: str, obj: Any) -> str:
    try:
        return f"{name}{inspect.signature(obj)}"
    except (TypeError, ValueError):
        return name


def _entry(name: str, obj: Any) -> List[str]:
    if not inspect.isclass(obj):
        return [f"- `{_signature(name, obj)}`: {_summary(obj)}"]
    lines = [f"- `class {_signature(name, obj)}`: {_summary(obj)}"]
    for meth, fn in inspect.getmembers(obj, inspect.isfunction):
        if not meth.startswith("_") and fn.__qualname__.startswith(f"{obj.__name__}."):
            lines.append(f"  - `.{_signature(meth, fn)}`: {_summary(fn)}")
    return lines


def render(package: str) -> str:
    """The llms.txt text of a package: the header, then its API by module."""
    pkg = importlib.import_module(package)
    sections: Dict[str, List[str]] = {}
    constants: List[str] = []
    for name in pkg.__all__:
        obj = getattr(pkg, name)
        if callable(obj):
            sections.setdefault(obj.__module__, []).extend(_entry(name, obj))
        else:
            constants.append(f"- `{name}`: {type(obj).__name__}")
    out = [(HERE / "llms_header.md").read_text().rstrip(), "", "## API", ""]
    out.append(f"Every name below is importable with `from {package} import <name>`.")
    for module, lines in sections.items():
        about = _summary(sys.modules[module]).rstrip(".")
        out += ["", f"### {module}" + (f": {about}" if about else ""), "", *lines]
    if constants:
        out += ["", "### Constants", "", *constants]
    return "\n".join(out) + "\n"


def write(app: Any, exception: Optional[Exception]) -> None:
    """Sphinx build-finished hook: write llms.txt next to index.html."""
    if exception is None and app.builder.format == "html":
        Path(app.outdir, "llms.txt").write_text(render(app.config.project))


if __name__ == "__main__":
    print(render(sys.argv[1]), end="")
