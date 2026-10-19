History
=======

Releases and changes of vayuayan.

v0.3.0 (unreleased)
-------------------

**Breaking changes**

* ``PM25Client()`` and ``vayuayan pm25`` default to V6.GL.03 (1998-2024). Use ``version="V6"`` for V6.GL.02.04, the only version with the Google Earth Engine fallback.
* ``CPCBHistorical.get_file_path()`` raises ``NetworkError`` when CPCB does not answer, instead of returning ``[]``.
* Download methods raise ``DataNotFoundError`` or ``StationNotFoundError`` instead of ``Exception``; a failed CPCB login raises ``AuthenticationError``.
* The library logs to the ``vayuayan`` loggers instead of printing.
* ``list_states``, ``list_cities`` and ``list_stations`` read the station directory: they include offline stations and match names and codes in any case.
* ``CPCBLive.get_nearest_station`` uses the haversine distance; in a near-tie it can pick a different station.
* Removed ``get_version()``, ``get_package_info()`` and the unused date helpers in ``vayuayan.utils``.
* Requires pandas 2.0 or newer. Removed the ``boto3`` and ``geopy`` dependencies.

**Added**

* ``vayuayan.us_aqi``: the US EPA AQI (``compute_us_aqi``, ``us_sub_index``, ``us_aqi_category``, ``us_aqi_color``, ``us_pollutant_name``) with the May 2024 EPA tables. Labels with a mass unit, such as ``"O3 (µg/m³)"``, are converted to ppm or ppb at 25 °C.
* ``vayuayan.aqi``: the CPCB National AQI (``compute_aqi``, ``sub_index``, ``daily_aqi``), with CPCB's 16-hour and three-pollutant rules, plus ``health_impact``, ``pollutant_category`` and ``WHO_PM25_GUIDELINES``. CPCB gives no Severe upper limit; vayuayan extends the band by the Very Poor width, and above it the sub-index continues on the same slope, as in CPCB's AQI calculator. The AQI is rounded half up.
* ``vayuayan.tidy``: long tables (``TIDY_COLUMNS``) from raw CPCB data, daily AQI workbooks and live data.
* ``CPCBHistorical.daily_aqi``, the ``daily_aqi`` CLI command, and ``tidy=True`` for raw downloads.
* ``PM25Client.get_pm25_monthly_stats``, and ``get_pm25_stats(..., geometry=True)`` for maps.
* A cache of past-year CPCB downloads in ``~/.cache/vayuayan`` (``VAYUAYAN_CACHE_DIR``, ``use_cache=False``).
* New: ``OAQClient`` (OAQ low-cost sensors), ``CPCBHistorical.add_coords``, ``city_daily`` and ``station_daily``, ``cpcb_tidy_daily``, ``nearest_stations``, ``get_aqi_categories``, ``india_boundary``, and the exports ``pollutant_name``, ``get_cache_dir`` and ``stations_to_city_summary``.
* OAQ sensor tools: ``OAQClient.sensors``, ``readings``, ``daily_means``, ``daily_records`` and ``check_daily_records``, ``oaq_nearest_cpcb`` and ``oaq_city_tally``; ``CPCBHistorical.raw_readings`` for several stations.
* ``set_theme`` and ``vayuayan.plot_theme``: one figure theme for all vayuayan plots (300 pixels per inch on screen and when saved, system sans-serif font, colour-blind-safe palette). ``plot_sensor_vs_reference``: sensor-days against the reference station, with the median of both over time.
* OAQ daily records: ``compare_daily_records``, ``daily_record_summary``, ``OAQClient.audit_daily_records`` and the ``plot_daily_record_*`` figures (``pip install "vayuayan[plot]"``). ``check_daily_records`` also compares with the median and the mean of the last 2 and 4 readings, and its tolerance is 0.005 (OAQ's 2 decimals).
* OAQ data requests are retried after network errors and 5xx statuses; ``get_city_latest`` lower-cases the city, as OAQ's paths need.
* ``vayuayan.sensor_qa``: ``readings_mean``, ``sensor_completeness``, ``sensor_plausibility``, ``collocated_precision``, ``peer_ratio``, ``sensor_accuracy``, ``ratio_by_humidity`` and ``EPA_PM25_TARGETS`` (US EPA targets for PM2.5 sensors).
* ``PM25Client(region=...)`` and ``vayuayan pm25 --region`` for the smaller regional files (``"AS"`` covers India), and the ``V5GL04`` version (1998-2022).

**Fixed**

* PM2.5 downloads use the ``satpmdata`` S3 bucket; the old bucket no longer exists. V5 downloads work, and the V5 range is 1998-2023.
* Live AQI values from the RSS feed were always empty.
* The CLI exits with code 1 when a command fails.
* Interrupted downloads no longer leave partial files.

**Changed**

* ``import vayuayan`` and the CLI start in about 40 ms (from about 400 ms): heavy libraries load on first use, and Google Earth Engine starts only when needed.
* The SSL fallback applies only to CPCB and the PM2.5 S3 download.
* With CPCB credentials, station lookups fetch the live directory in parallel.
* Hourly downloads always start with ``Year`` and ``Month`` columns.
* ``stations_to_dataframe`` adds ``status`` and ``aqi_category`` columns, and ``get_pm25_stats`` adds ``count``.
* Timestamps of raw and live data are parsed value by value (``%Y-%m-%d %H:%M:%S``, ``%H:%M`` or a date), so one value in another format no longer drops the others.
* ``air_quality_client`` is split into smaller modules; the old import path still works.
* CI tests Linux, macOS and Windows on Python 3.9-3.14, the lowest supported dependencies and the built wheel.

v0.1.5 (2026-06-27)
-------------------

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
-------------------

* Added an SSL fallback
* Historical data functions return the full DataFrame

v0.1.3 (2025-10-12)
-------------------

* Fixed a documentation link

v0.1.2 (2025-10-11)
-------------------

* Fixed the missing logo on PyPI

v0.1.1 (2025-10-11)
-------------------

* Updated the installation instructions. PyPI is the primary method.

v0.1.0 (2025-10-11)
-------------------

* First release of the vayuayan package
* Historical AQI data from CPCB India
* Live air quality data
* Analysis of PM2.5 satellite data for GeoJSON polygons
* Command-line interface to get the data
* Python API to get the data from code

**Data Sources**

* Central Pollution Control Board (CPCB) India
* WUSTL ACAG PM2.5 satellite data


