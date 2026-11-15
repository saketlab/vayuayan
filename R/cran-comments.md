## Test environments

* local macOS 27.0, R 4.6.1: `R CMD check --as-cran` on the built tarball,
  with the CRAN incoming checks (`_R_CHECK_CRAN_INCOMING_REMOTE_=true`)
* GitHub Actions: macOS (release), Windows (devel, release, oldrel-1),
  Ubuntu (devel, release, oldrel-1)
* win-builder: R-devel, R-release

## Submission

This is an update of vayuayan 0.3.0 (on CRAN since 2026-11-03). It comes soon
after that release because CPCB retired the file route that 0.3.0 downloads
from: `cpcb_city_daily()`, `cpcb_station_daily()` and the other CPCB download
functions of 0.3.0 now fail with HTTP 404. This version uses CPCB's new
route. It also adds fire detections (NASA FIRMS, INSAT) and DPCC's hourly
station data; see NEWS.md.

## R CMD check results

0 errors | 0 warnings | 0 notes

The incoming checks may list CPCB, OAQ, DPCC, FIRMS and INSAT as possibly
misspelled: they are names of the data providers, spelled out in the
Description.

The CPCB portal (airquality.cpcb.gov.in) refuses connections from outside
India, so the Description does not link to it.

URLs were checked with `urlchecker::url_check()` and spelling with
`spelling::spell_check_package()`.

## Internet resources

The package wraps public web services (CPCB, OAQ, DPCC, NASA FIRMS, MOSDAC and
the WUSTL ACAG bucket on the AWS Open Data registry). Examples that need the network use
`@examplesIf interactive()`, or `@examplesIf` on the `OAQ_API_KEY`
environment variable for the key-protected OAQ API. Network tests call
`skip_on_cran()` and `skip_if_offline()`. The vignette evaluates network
chunks only when `NOT_CRAN` is `"true"` and CPCB answers.

The station lookup functions read a bundled directory file and run offline
in examples and tests.

Downloads are cached only in `tools::R_user_dir("vayuayan", "cache")`, or in
a directory the user sets with the `vayuayan.cache_dir` option, the
`VAYUAYAN_CACHE_DIR` environment variable or a `cache_dir` argument. Nothing
is written during examples, tests or the vignette on CRAN.
