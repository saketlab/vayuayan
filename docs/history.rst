History
=======

Releases and changes of vayuayan.

v0.1.5 (2026-06-27)
------------------

* Added Google Earth Engine fallback for PM2.5 data when AWS S3 returns 403, with automatic GEE project detection and ``setup_earth_engine()`` helper
* Added support for V5 (V5.GL.05.02, GWR-based) WUSTL ACAG data alongside the default V6
* Moved CPCB historical data to the new CPCB JSON endpoints. The old base64 endpoints return 404.
* Historical downloads do not need a login. A snapshot of the CPCB station directory is part of the package.
* Optional ``CPCB_USERNAME``, ``CPCB_PASSWORD``, ``CPCB_CLIENT_ID`` and ``CPCB_CLIENT_SECRET`` environment variables enable the live station directory
* Added ``CPCBHistorical.iter_stations()``
* Added ``CPCBHistorical.download_raw_aqi_data_station_level()`` for raw 15-minute station data
* Added ``download_hourly_aqi_data_city_level()`` and ``download_hourly_aqi_data_station_level()``
* Live station data uses the CPCB RSS feed if the old endpoints fail
* The package now includes type information (``py.typed``)

v0.1.4 (2025-11-30)
------------------

* Added an SSL fallback
* Historical data functions return the full DataFrame

v0.1.3 (2025-10-12)
------------------

* Fixed a documentation link

v0.1.2 (2025-10-11)
------------------

* Fixed the missing logo on PyPI

v0.1.1 (2025-10-11)
------------------

* Updated the installation instructions. PyPI is the primary method.

v0.1.0 (2025-10-11)
------------------

* First release of the vayuayan package
* Historical AQI data from CPCB India
* Live air quality data
* Analysis of PM2.5 satellite data for GeoJSON polygons
* Command-line interface to get the data
* Python API to get the data from code

**Data Sources**

* Central Pollution Control Board (CPCB) India
* WUSTL ACAG PM2.5 satellite data


