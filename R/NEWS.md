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
