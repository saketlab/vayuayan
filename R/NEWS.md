# vayuayan 0.3.0

## Breaking changes

* CPCB station lists come from a bundled directory and work offline.
* Live AQI holds only the latest hour: `date`, `hour` and `date_time` are
  ignored with a warning; `last_hours` is removed.
* `pm25_download_netcdf()` fetches V6.GL.03 (1998-2024) from the AWS
  `satpmdata` bucket; the `v6.gl.02.04` bucket is gone.
* Downloads are cached in `vayuayan_cache_dir()` and reuse the Python
  package's cache.
* `pm25_v5gl04_monthly()` is now `pm25_monthly(version = "V5GL04")`.

## New features

* CPCB National AQI: `compute_aqi()`, `aqi_sub_index()`, `daily_aqi()`.
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

## Bug fixes

* `get_aqi_categories()` returns `character(0)` for empty input.
* `analyze_station_data()` counted columns instead of cities.
* Interrupted PM2.5 downloads no longer leave partial files in the cache.

## Other changes

* Dropped geosphere, glue and lubridate, and the startup message.
* Analysis vignettes moved to pkgdown articles.
