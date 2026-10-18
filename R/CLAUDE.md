# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`vayuayan` (in `R/` of the saketlab/vayuayan repo) is an R package for downloading and analyzing air quality data from three sources: CPCB CAAQMS stations (India), OAQ low-cost sensor networks (India), and WUSTL ACAG satellite PM2.5 (global NetCDF). It is the R port of the Python package [vayuayan](https://github.com/saketlab/vayuayan); keep function behaviour aligned with it where practical.

## Commands

```r
devtools::document()                 # regenerate man/ and NAMESPACE from roxygen (never edit NAMESPACE by hand)
devtools::load_all()                 # load package for interactive work
devtools::test()                     # run all tests
devtools::test(filter = "utills")    # run one file: tests/testthat/test_utills.R
testthat::test_file("tests/testthat/test_CPCBhistorical.R")
withr::with_envvar(c(NOT_CRAN = "false"), devtools::check(args = c("--no-manual", "--as-cran")))  # mirrors CI
```

CI (`.github/workflows/R-CMD-check.yaml`) runs `R CMD check --as-cran` with the CRAN vignette built and `NOT_CRAN=false`, on macOS, Windows (release, oldrel-1) and Ubuntu (devel, release, oldrel-1); warnings fail the job.

## Architecture

All code is in `R/`, one file per data source, functions prefixed by source:

- `cpcb_directory.R` (internal): CPCB's base64 `dataRepository`/`aqi_dashboard` endpoints return 404; do not call them. Station metadata comes from `inst/extdata/cpcb_station_directory.json`, a snapshot copied from the Python package (`../python/vayuayan/data/`; refresh both together). `.cpcb_directory_stations()` and `.cpcb_rss_stations()` are flat station tables (snapshot / live feed) that every lookup goes through via `.cpcb_match()` (case-insensitive). The snapshot is cached in `.cpcb_cache` for the session and the feed (`/caaqms/iit_rss_feed_with_coordinates`) for 5 minutes, so one user call downloads it at most once. `.cpcb_rss_cities()` keeps the cities data frame with a `stationsInCity` list-column that `cpcb_get_all_india()` returns. The feed's AQI field is `airQualityIndexValue`.
- `cpcb_historical.R` (`cpcb_*`): station lists, `cpcb_get_complete_list` and `cpcb_add_coords` read the snapshot and work offline. Downloads POST JSON to `/caaqms-common/dataRepository/file-path` (frequency codes `1D`/`1H`/`1M`/`15M`) with CPCB's exact names from the resolvers, then GET `download-excel-file?file_name=` (`.cpcb_save_year`).
- `cache.R`: `vayuayan_cache_dir()` (option `vayuayan.cache_dir`, then env `VAYUAYAN_CACHE_DIR`, then `tools::R_user_dir()`). Layout matches the Python package: `pm25/<WUSTL file name>` and `cpcb/<repository path>` (past years only). Reads also look in the Python default cache (`~/.cache/vayuayan`, `./pm25_data`), so a Python user's downloads are reused.
- `cpcb_raw.R`: raw 15-minute station files, hourly city/station workbooks, `cpcb_station_daily_aqi()`.
- `aqi.R`, `aqi_daily.R`: CPCB National AQI (`compute_aqi`, `aqi_sub_index`, `daily_aqi`), a port of `vayuayan/aqi.py`; `tests/testthat/fixtures/daily_aqi_python.csv` is Python output the tests compare against.
- `cpcb_tidy.R`: `cpcb_tidy_daily()` turns a CPCB Day x month sheet into long rows; `cpcb_city_daily()` / `cpcb_station_daily()` download, cache (`<city>_aqi_<year>.csv`, `<id>_<year>.csv`) and reshape. Vignettes use these instead of `pivot_longer` code.
- `geo.R`: `india_boundary()` (BharatViz LGD districts, cached per session) and `pm25_map()` (needs suggested ggplot2 + tidyterra). Vignettes call package functions and define none of their own.
- `cpcb_live.R`: live readings come from the feed only. It holds just the latest hour, so the `date`/`hour`/`date_time` arguments are accepted but ignored with a warning.
- `oaq.R` (`oaq_*`): two-step auth. `oaq_session()` exchanges `OAQ_API_KEY` (env var, kept in gitignored `.Renviron`/`.oaqapi_key`) for a signed query string, valid for 24h. Every other `oaq_*` function takes that `session` as its first argument and builds URLs through `.oaq_url()`.
- `pm25_client.R` (`pm25_*`): two separate paths.
  - `pm25_versions.R` lists the products in the public `satpmdata` bucket (us-east-1), as `PM25_VERSIONS` in Python plus V5GL04: `V6GL03` (default), `V6` (`archive/V6GL0204`), `V5` (`archive/V5GL0502`), `V5GL04` (`archive/V5GL04`). V5 products name regions `Global/Asia/...`; the R API always takes `GL/AS/EU/NA`. Global files are large, so use `region = "AS"`. A cached file counts as complete only if it is >1 MB.
  - `pm25_extract.R`: `pm25_get_point`, `pm25_get_stats_by_polygon`, `pm25_monthly`. `pm25_read_netcdf_bbox` / `pm25_load_netcdf_bbox` read a NetCDF file and need the suggested `ncdf4`.
- `utils.R`: AQI categorization, haversine/`nearest_stations` geospatial matching, `stations_to_dataframe`, and the package-internal `%||%` (defined here because `Depends: R >= 4.0.0` predates base `%||%`).

Conventions: internal helpers are dot-prefixed and unexported. User-facing messages go through `cli::cli_alert_*`, never `cat()`/`print()`. Examples that need the network use `@examplesIf interactive()`, and OAQ ones use `@examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))`. Never use `\dontrun{}` (CRAN reviewers reject it). By default nothing may write outside `tempdir()`, `tools::R_user_dir()` or a user-supplied path.

## Tests

`tests/testthat/test_offline.R` covers the snapshot lookups, URL builders and argument checks without network. Tests that hit live APIs are guarded with `skip_on_cran()` + `skip_if_offline()`; expect flaky failures when CPCB is down rather than assuming a code bug. CRAN target: `R CMD check --as-cran` with only the "New submission" NOTE (see `cran-comments.md`).

## Vignettes and site

`vignettes/introduction.Rmd` is the only CRAN vignette. Network chunks run only when `NOT_CRAN == "true"` (unset counts as CRAN) and the CPCB feed answers. The analysis articles live in `vignettes/articles/` (Rbuildignored, pkgdown-only); they download real data (V5GL04 into the gitignored `vignettes/data/pm25`), and the OAQ ones need `OAQ_API_KEY`, so they are built on the author's machine. The pkgdown workflow (on push to main) copies pre-built HTML from `inst/doc/` into `docs/articles/` without knitting, rsyncs `docs/` to `/var/www/r-pkgdown/vayuayan/docs/R` (served as https://vayuayan.saketlab.org/R/, mirrored at vayuayanr.saketlab.org) with the org `HOSTINGER_*` secrets, as `../varunayanR` does. The Python package in `../python` deploys `/python/` and the site root (`docs-hostinger.yml`). All workflows live in the repo-root `.github/workflows/` and run in `R/` or `python/` with path filters. Site config: `_pkgdown.yml`.
