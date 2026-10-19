"""
Google Earth Engine: the fallback source of PM2.5 data.

earthengine-api is optional and slow to import and initialize, so the
functions import ee on first use.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from . import http_client
from .constants import get_gee_project_file
from .pm25_versions import PM25_VERSIONS

if TYPE_CHECKING:
    import ee

logger = logging.getLogger(__name__)

SETUP_HINT = """Google Earth Engine is not set up, so PM2.5 data cannot come from GEE.
1. Register a Noncommercial Cloud project at https://code.earthengine.google.com/
2. Run: from vayuayan import setup_earth_engine; setup_earth_engine()
   or set your project ID: export GEE_PROJECT=your-project-id"""


def is_available() -> bool:
    """True if the earthengine-api package is installed."""
    return importlib.util.find_spec("ee") is not None


def setup_earth_engine(project_id: Optional[str] = None) -> bool:
    """Set up Google Earth Engine authentication with a Cloud project.

    Args:
        project_id: Optional Google Cloud project ID. If None, the
                   function asks the user for the ID.

    Returns:
        True if setup succeeded, False otherwise.

    Example:
        >>> from vayuayan import setup_earth_engine
        >>> setup_earth_engine()
        # Follow the prompts to enter your project ID
    """
    if not is_available():
        print("✗ Earth Engine library not installed")
        print("  Install it with: pip install earthengine-api")
        return False

    import ee

    print("=" * 70)
    print("Google Earth Engine Setup")
    print("=" * 70)
    print()

    if project_id:
        print(f"Using project ID: {project_id}")
    else:
        try:
            # Initialize without a project to find the authentication status
            ee.Initialize()
            print("✓ Already authenticated!")
            print("\nNote: You still need a project ID for the new API.")
            print("Visit https://code.earthengine.google.com/ to register.")
            print()
        except Exception:
            pass

        print("STEP-BY-STEP INSTRUCTIONS:")
        print("-" * 70)
        print()
        print("1. Open this URL in your browser:")
        print("   https://code.earthengine.google.com/")
        print()
        print("2. Click 'Register a Noncommercial or Commercial Cloud project'")
        print()
        print("3. Select or create a Google Cloud project")
        print("   - If you don't have one, it will create one for you")
        print("   - Choose 'Noncommercial' (free for research/education)")
        print()
        print("4. Copy the project ID (e.g., 'ee-myproject123')")
        print()
        print("-" * 70)
        print()

        try:
            project_id = input("Enter your Google Cloud project ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nSetup cancelled.")
            return False

        if not project_id:
            print("\n✗ No project ID provided. Exiting.")
            return False

    print(f"\nUsing project: {project_id}")
    print("\nAuthenticating with Earth Engine...")
    print("(A browser window will open for authentication)")
    print()

    try:
        ee.Authenticate(force=True)

        print(f"\nInitializing Earth Engine with project '{project_id}'...")
        ee.Initialize(project=project_id)

        print("\nTesting data access...")
        collection = ee.ImageCollection(PM25_VERSIONS["V6"].gee_monthly)
        count = collection.size().getInfo()

        print("\n" + "=" * 70)
        print("✓ SUCCESS!")
        print("=" * 70)
        print(f"\n✓ Earth Engine authenticated with project: {project_id}")
        print(f"✓ Can access PM2.5 data collection ({count} images)")

        gee_project_file = get_gee_project_file()
        gee_project_file.write_text(project_id)
        print(f"✓ Project ID saved to {gee_project_file}")

        print()
        print("You can now use PM25Client to download data!")
        print()
        print("Example:")
        print("  >>> from vayuayan import PM25Client")
        print('  >>> client = PM25Client(version="V6")  # the version that GEE has')
        print("  >>> data = client.get_pm25_at_point(28.6139, 77.2090, 2020, 1)")
        print()

        return True

    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print()
        print("Troubleshooting:")
        print("1. Make sure you registered at https://code.earthengine.google.com/")
        print("2. Verify your project ID is correct")
        print("3. Wait a few minutes for permissions to propagate")
        print("4. Try running setup_earth_engine() again")
        return False


def project_id() -> Optional[str]:
    """GEE project ID from the environment or the config file, if any."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEE_PROJECT")
    if project:
        return project
    gee_project_file = get_gee_project_file()
    if gee_project_file.exists():
        return gee_project_file.read_text().strip()
    legacy_file = Path(".gee_project")
    if not legacy_file.exists():
        return None
    project = legacy_file.read_text().strip()
    try:
        gee_project_file.write_text(project)
        logger.info("Migrated GEE config to %s", gee_project_file)
    except OSError as e:
        logger.debug("Could not migrate GEE config: %s", e)
    return project


def initialize() -> bool:
    """Initialize Google Earth Engine, and find and set the project.

    Returns:
        True if initialization succeeded, False otherwise.
    """
    import ee

    gee_project = project_id()
    attempts: List[Dict[str, str]] = []
    if gee_project:
        attempts += [
            {
                "project": gee_project,
                "opt_url": "https://earthengine-highvolume.googleapis.com",
            },
            {"project": gee_project},
        ]
    attempts += [{"project": "earthengine-legacy"}, {}]

    for kwargs in attempts:
        try:
            ee.Initialize(**kwargs)
        except Exception as e:  # ee raises many unrelated error types
            logger.debug("ee.Initialize(%s) failed: %s", kwargs, e)
            continue
        logger.info("Google Earth Engine initialized (%s)", kwargs or "default")
        return True

    logger.warning(SETUP_HINT)
    return False


def download_geotiff(
    collection_id: str,
    year: int,
    month: Optional[int],
    output_path: Path,
    region: Optional[ee.Geometry] = None,
) -> Optional[str]:
    """Download one PM2.5 image of a GEE collection as a GeoTIFF.

    Note: GEE has a download limit of 32768x32768 pixels. For global data,
    give a region for the clip, or use the export-to-Drive API.

    Args:
        collection_id: GEE image collection (annual or monthly images).
        year: Year for data.
        month: Optional month (1-12) for a monthly collection.
        output_path: Path of the GeoTIFF file to write.
        region: Optional ee.Geometry for the clip. If None, the image is
            clipped to the India bounds.

    Returns:
        Path to the GeoTIFF file, or None if there is no image or the download
        fails.
    """
    import ee

    zip_path = output_path.with_suffix(".zip")
    try:
        date_filter = ee.Filter.calendarRange(year, year, "year")
        if month is not None:
            date_filter = ee.Filter.And(
                date_filter, ee.Filter.calendarRange(month, month, "month")
            )
        image = ee.ImageCollection(collection_id).filter(date_filter).first()
        if image is None:
            logger.warning("No GEE data for %d-%s", year, month or "annual")
            return None

        # The India raster is downloaded once and cached; every station then
        # reads from it, which is faster than one clip per station.
        if region is None:
            region = ee.Geometry.Rectangle([68.0, 8.0, 98.0, 37.0])  # India
        url = image.clip(region).getDownloadURL(
            {
                "scale": 10000,  # ~0.1 degree at the equator
                "crs": "EPSG:4326",
                "fileFormat": "GeoTIFF",
                "region": region,
            }
        )

        # getDownloadURL() returns a ZIP archive, not a raw GeoTIFF
        logger.info("Downloading PM2.5 from GEE to %s", zip_path)
        response = http_client.request("get", url, stream=True, timeout=300)
        http_client.stream_to_file(response, zip_path, "Downloading (GEE)")

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            tif_files = [f for f in zip_ref.namelist() if f.endswith(".tif")]
            if not tif_files:
                raise ValueError(f"No .tif file in GEE download: {zip_ref.namelist()}")
            zip_ref.extract(tif_files[0], output_path.parent)
        (output_path.parent / tif_files[0]).replace(output_path)
        logger.info("GeoTIFF extracted: %s", output_path)
        return str(output_path)

    except Exception as e:  # ee raises many unrelated error types
        logger.warning("GEE download failed: %s", e)
        output_path.unlink(missing_ok=True)
        return None
    finally:
        zip_path.unlink(missing_ok=True)
