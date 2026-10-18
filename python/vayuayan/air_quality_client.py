"""
The client classes, under their original import path.

The code is in cpcb_historical, cpcb_live, pm25 and gee. Import from here or
from vayuayan; both keep working.
"""

from .cpcb_historical import CPCBHistorical
from .cpcb_live import CPCBLive
from .gee import setup_earth_engine
from .pm25 import PM25Client

__all__ = [
    "CPCBHistorical",
    "CPCBLive",
    "PM25Client",
    "setup_earth_engine",
]
