"""The two AQI colour scales of the CLI; each value is coloured on its own scale."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from .constants import AQI_CATEGORIES, AQI_COLORS
from .us_aqi import US_AQI_CATEGORIES, US_AQI_COLORS, us_aqi_category
from .utils import get_aqi_category


@dataclass(frozen=True)
class Scale:
    """One AQI standard: its name, categories, value ranges and colours."""

    key: str
    label: str
    colors: Dict[str, str]
    ranges: Dict[str, str]
    category: Callable[[float], str]

    def color(self, category: str) -> str:
        """The official hex colour of a category of this scale."""
        return self.colors[category]

    def style(self, category: str) -> str:
        """Rich style for a cell of this category, with readable text."""
        background = self.color(category)
        return f"{readable_text(background)} on {background}"

    def band(self, category: str) -> int:
        """1 for the cleanest category of this scale, and so on upward."""
        return list(self.colors).index(category) + 1

    def legend(self) -> List[Tuple[int, str, str, str]]:
        """(band, category, value range, style) of each category."""
        return [
            (self.band(name), name, self.ranges[name], self.style(name))
            for name in self.colors
        ]


def _channel(value: int) -> float:
    """Linear value of one sRGB channel, from the WCAG formula."""
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of a #RRGGBB colour."""
    code = hex_color.lstrip("#")
    r, g, b = (_channel(int(code[i : i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio of two #RRGGBB colours."""
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


def readable_text(background: str) -> str:
    """Black or white, whichever contrasts more with the background."""
    black, white = "#000000", "#FFFFFF"
    return (
        black if contrast(background, black) >= contrast(background, white) else white
    )


INDIA = Scale(
    key="india",
    label="India National AQI (CPCB)",
    colors=AQI_COLORS,
    ranges={n: f"{b['min']}-{b['max']}" for n, b in AQI_CATEGORIES.items()},
    category=get_aqi_category,
)
US = Scale(
    key="us",
    label="US AQI (EPA)",
    colors=US_AQI_COLORS,
    # Hazardous has no upper limit: US_AQI_CATEGORIES ends at infinity
    ranges={
        n: f"{int(lo)}+" if hi == float("inf") else f"{int(lo)}-{int(hi)}"
        for n, (lo, hi) in US_AQI_CATEGORIES.items()
    },
    category=us_aqi_category,
)
SCALES: Dict[str, Scale] = {INDIA.key: INDIA, US.key: US}
