"""
The WUSTL ACAG PM2.5 dataset versions that PM25Client can download.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

_GEE_PM25 = "projects/sat-io/open-datasets/GLOBAL-SATELLITE-PM25"


@dataclass(frozen=True)
class PM25Version:
    """Where one WUSTL ACAG PM2.5 dataset version is, and what it covers."""

    name: str
    s3_dir: str
    region_dir: str
    file_stem: str
    variable_name: str
    year_range: Tuple[int, int]
    manual_url: str
    gee_monthly: Optional[str] = None
    gee_annual: Optional[str] = None
    gee_year_range: Optional[Tuple[int, int]] = None

    def __post_init__(self) -> None:
        gee = (self.gee_monthly, self.gee_annual, self.gee_year_range)
        if any(f is not None for f in gee) and not all(f is not None for f in gee):
            raise ValueError(f"{self.name}: set all GEE fields, or none")

    def check_year(self, year: int) -> None:
        """Raise ValueError if the dataset has no data for the year."""
        first, last = self.year_range
        if not (first <= year <= last):
            raise ValueError(
                f"Year {year} is outside valid range for {self.name}: {first}-{last}"
            )

    def gee_collection(self, month: Optional[int] = None) -> Optional[str]:
        """GEE collection of annual (month None) or monthly images, if any."""
        return self.gee_annual if month is None else self.gee_monthly

    def filename(self, year: int, month: Optional[int] = None) -> str:
        """NetCDF filename for a year, or for one month of the year."""
        if month is None:
            return f"{self.file_stem}.{year}01-{year}12.nc"
        return f"{self.file_stem}.{year}{month:02d}-{year}{month:02d}.nc"

    def key(self, year: int, month: Optional[int] = None) -> str:
        """S3 key of the NetCDF file in the satpmdata bucket."""
        timescale = "Annual" if month is None else "Monthly"
        name = self.filename(year, month)
        return f"{self.s3_dir}/{timescale}/{self.region_dir}/{name}"


PM25_VERSIONS: Dict[str, PM25Version] = {
    "V6": PM25Version(
        name="V6.GL.02.04 (CNN)",
        s3_dir="archive/V6GL0204/CNNPM25",
        region_dir="GL",
        file_stem="V6GL02.04.CNNPM25.GL",
        variable_name="PM25",
        year_range=(1998, 2023),
        manual_url="https://wustl.box.com/v/ACAG-V6GL0204-CNNPM25",
        gee_monthly=f"{_GEE_PM25}/MONTHLY",
        gee_annual=f"{_GEE_PM25}/ANNUAL",
        gee_year_range=(2000, 2022),
    ),
    "V5": PM25Version(
        name="V5.GL.05.02 (GWR)",
        s3_dir="archive/V5GL0502/GWRPM25",
        region_dir="Global",
        file_stem="V5GL0502.HybridPM25.Global",
        variable_name="GWRPM25",
        year_range=(1998, 2023),
        manual_url="https://wustl.box.com/v/ACAG-V5GL0502-GWRPM25",
    ),
    # The newest CNN version. GEE has only V6.GL.02, so there is no GEE fallback.
    "V6GL03": PM25Version(
        name="V6.GL.03 (CNN)",
        s3_dir="V6GL03/CNNPM25",
        region_dir="GL",
        file_stem="V6GL03.CNNPM25.GL",
        variable_name="PM25",
        year_range=(1998, 2024),
        manual_url="https://www.satpm.org/v6-gl-03",
    ),
}
