# vayuayan (development version)

* `cpcb_station_table()` includes stations that only the CPCB live feed knows.
  If the feed is unavailable, the directory alone is used.
* `cpcb_raw_readings()` and `cpcb_station_daily()` accept `city` and `state`.
  The single-station functions accept them to narrow an ambiguous name.
* `cpcb_download_city_report()` sends its requests in parallel, and a network
  failure stops a batch with one warning, keeping what was fetched.
* `sensor_plausibility()` is about 9 times faster, with the same results for
  odd windows; an even `spike_window` now matches the Python package.
* `us_aqi_pollutant_name("SO2 (24h) (ppb)")` is the 24-hour SO2.
* `pm25_load_netcdf_bbox(mask = TRUE)` keeps cells by their centres.

* `aqi_sub_index()`, `compute_aqi()` and `daily_aqi()` use the continuous bands
  of CPCB's AQI calculator (for example PM2.5 30-60 maps to 50-100), so values
  near a band boundary change by a few points.
* New `daily_us_aqi()`: daily US EPA AQI from raw readings; and
  `cpcb_station_daily_aqi(standard = "us")`.
* New `cpcb_station_table()`: every station with its ID, name, city, state and coordinates. `cpcb_download_city_report()`: the report export of all stations of a city as one table.
* New `cpcb_download_station_report()`: station data from CPCB's report export.
* `compute_us_aqi()` gives no AQI, with a warning, for 8-hour O3 above 0.200 ppm
  without a 1-hour value, and gives SO2 200 for a 1-hour SO2 from 305 ppb with
  no 24-hour value.
* `us_aqi_sub_index("PM2.5 (mg/m3)", x)` converts mg to ug.
* PM2.5 polygon statistics count cells whose centres fall inside, falling back
  to the cells a small polygon touches; a polygon outside the grid is an error.
* Added `plot_aqi_radial()` to draw daily AQI as a radial calendar
* New `plot_aqi_radial_hourly()`: hourly AQI on a 24-hour clock in IST.
* CPCB repository downloads retry timeouts and 5xx errors.
* `cpcb_get_live_aqi_data()` returns a numeric `airQualityIndex`, `NA` when
  CPCB has no AQI for the hour.
* New article "PM2.5 by hour of the day: Mumbai and Bengaluru (2023)".
* `cpcb_city_daily()` returns `year` and `date` columns and takes several
  years at once.
* Added `aqi_color()` for CPCB colour of an AQI value.
* `cpcb_city_daily()` fetches each city's file list once and downloads
  uncached workbooks in parallel. 
* Imports curl (>= 5.0.0).

# vayuayan 0.3.0

## Breaking changes

* CPCB station lists come from a bundled directory and work offline.
* Live AQI holds only the latest hour: `date`, `hour` and `date_time` are
  ignored with a warning; `last_hours` is removed.
* `pm25_download_netcdf()` fetches V6.GL.03 (1998-2024) from the AWS
  `satpmdata` bucket; the `v6.gl.02.04` bucket is gone.
* Downloads are cached in `vayuayan_cache_dir()`; files in the Python
  package's cache are reused.
* `pm25_v5gl04_monthly()` is now `pm25_monthly(version = "V5GL04")`.
* `cpcb_get_file_path()` returns CPCB's entries as sent: `filepath` (was
  `filePath`) and `year` as CPCB gives it.

## New features

* `theme_vayuayan()` (the ggplot2 theme of the package's figures) and
  `plot_sensor_vs_reference()`.
* `compute_us_aqi()`, `us_aqi_sub_index()`, `us_aqi_category()`,
  `us_aqi_color()` and `us_aqi_pollutant_name()` calculate the US EPA AQI with the May 2024 EPA
  tables. Labels with a mass unit, such as `"O3 (ug/m3)"`, are converted to
  ppm or ppb at 25 degrees C.
* CPCB National AQI: `compute_aqi()`, `aqi_sub_index()`, `daily_aqi()`. Above
  the Severe band the sub-index continues on the same slope, as in CPCB's AQI
  calculator, and the AQI is rounded half up.
* Raw and hourly CPCB data: `cpcb_download_raw_station_data()`,
  `cpcb_download_hourly_city_data()`, `cpcb_download_hourly_station_data()`,
  `cpcb_raw_to_long()`, `cpcb_station_daily_aqi()`.
* Daily data in long form: `cpcb_tidy_daily()`, `cpcb_city_daily()`,
  `cpcb_station_daily()`.
* Stations can be given by name or a unique part of it
  (`"Anand Vihar, Delhi"`), not just ID.
* `cpcb_get_nearest_stations()` and `stations_to_city_summary()`.
* PM2.5 functions take `version` (`"V6GL03"`, `"V6"`, `"V5"`, `"V5GL04"`)
  and `region` (`"AS"` for the smaller Asia files).
* `pm25_get_point()`, `pm25_get_stats_by_polygon()`, `pm25_monthly()`.
* `india_boundary()` and `pm25_map()`.
* `oaq_stations_table()`; `oaq_fetch_monthly_stations()` takes several
  providers.
* OAQ sensor tools: `oaq_sensors()`, `oaq_readings()`, `oaq_daily_means()`,
  `oaq_daily_records()`, `oaq_check_daily_records()`, `oaq_nearest_cpcb()`,
  `oaq_city_tally()`; `cpcb_raw_readings()` for several stations.
* OAQ daily records: `compare_daily_records()`, `daily_record_summary()`,
  `oaq_audit_daily_records()` and the `plot_daily_record_*()` figures
  (ggplot2).
* Sensor quality checks against the US EPA targets for PM2.5 sensors:
  `readings_mean()`, `sensor_completeness()`, `sensor_plausibility()`,
  `collocated_precision()`, `peer_ratio()`, `sensor_accuracy()`,
  `ratio_by_humidity()`.
* `aqi_health_impact()`, `aqi_pollutant_category()`, `cpcb_live_to_long()`
  and `cpcb_live_metrics()`.

## Bug fixes

* OAQ responses with bare `NaN` values (some daily files of 2025) are read with
  `NA`; before, `oaq_readings()` and the functions that use it left those days
  out.
* `oaq_fetch_monthly_stations()` failed when providers return different
  columns or id types; `oaq_get_city_latest()` needs a lower-case city in
  OAQ's paths and now lower-cases it; OAQ data requests are retried after
  network errors and 5xx statuses. The OAQ examples use real sensors.
* `get_aqi_categories()` returns `character(0)` for empty input.
* `analyze_station_data()` counted columns instead of cities.
* Interrupted PM2.5 downloads no longer leave partial files in the cache.

## Other changes

* Dropped geosphere, glue and lubridate, and the startup message.
* Station, state and city lists sort in C-locale order; cities of the live
  feed sort by share of live stations, then name. Hourly readings are
  numeric. PM2.5 `std` divides by n (population standard deviation of the
  grid cells).
* Analysis vignettes moved to pkgdown articles.
