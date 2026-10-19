# Outputs of the Python package on the same inputs, written by
# python/scripts/make_parity_fixtures.py into fixtures/parity_python.json.
# Regenerate that file when the Python side changes on purpose.

parity <- jsonlite::read_json(test_path("fixtures", "parity_python.json"))

# JSON list with nulls -> atomic vector with NA
.vec <- function(x) unlist(lapply(x, function(v) if (is.null(v)) NA else v))

test_that("the R and Python APIs map onto each other", {
  exports <- getNamespaceExports("vayuayan")
  mapped <- unique(unlist(parity$api))
  # every mapped name exists, and every export is mapped or listed as R-only
  expect_equal(setdiff(mapped, exports), character(0))
  expect_equal(sort(setdiff(exports, c(mapped, names(parity$r_only)))), character(0))
})

test_that("NAQI breakpoints and bands match", {
  expect_setequal(names(.aqi_pollutants), names(parity$pollutants))
  for (name in names(parity$pollutants)) {
    py <- parity$pollutants[[name]]
    r <- .aqi_pollutants[[name]]
    expect_equal(r$bp, as.numeric(unlist(py$breakpoints)), info = name)
    expect_equal(r$hours, py$hours, info = name)
    expect_equal(r$unit, substr(sub("µ", "u", py$unit), 1, 2), info = name)
  }
  expect_equal(.aqi_bands, as.numeric(unlist(parity$aqi_categories)))
})

test_that("pollutant labels resolve like Python", {
  cases <- parity$pollutant_name
  got <- aqi_pollutant_name(vapply(cases, `[[`, "", "label"))
  expect_equal(got, .vec(lapply(cases, `[[`, "name")))
})

test_that("sub-indices match Python at every breakpoint", {
  for (case in parity$sub_index) {
    expect_equal(
      aqi_sub_index(case$pollutant, case$concentration), case$sub_index,
      tolerance = 1e-9, info = paste(case$pollutant, case$concentration)
    )
  }
})

test_that("compute_aqi matches Python", {
  for (case in parity$compute_aqi) {
    input <- lapply(case$input, function(v) if (is.null(v)) NA_real_ else v)
    got <- compute_aqi(input)
    info <- jsonlite::toJSON(case$input, auto_unbox = TRUE, null = "null")
    expect_equal(got$aqi, case$aqi %||% NA_integer_, info = info)
    expect_equal(got$category, case$category %||% NA_character_, info = info)
    expect_equal(got$dominant_pollutant, case$dominant_pollutant %||% NA_character_, info = info)
    want <- unlist(case$sub_indices)
    expect_equal(got$sub_indices[names(want)], want, tolerance = 1e-9, info = info)
    expect_setequal(names(got$sub_indices), names(want))
  }
})

test_that("AQI categories match Python", {
  values <- .vec(lapply(parity$aqi_category, `[[`, "aqi"))
  want <- vapply(parity$aqi_category, `[[`, "", "category")
  expect_equal(get_aqi_categories(values), want)
})

test_that("haversine distances match Python", {
  for (case in parity$haversine) {
    expect_equal(do.call(haversine_distance, unname(case$args)), case$km, tolerance = 1e-9)
  }
})

test_that("clean_station_name matches Python", {
  for (case in parity$clean_station_name) {
    expect_equal(clean_station_name(case$name), case$clean, info = case$name)
  }
})

test_that("frequency names map to the same CPCB codes", {
  for (case in parity$frequency) {
    expect_equal(.cpcb_normalize_frequency(case$frequency), case$code, info = case$frequency)
  }
})

test_that("CPCB cache paths match the Python cache layout", {
  for (case in parity$cache_path) {
    expect_equal(.cpcb_cache_name(case$filepath), case$cache, info = case$filepath)
  }
})

test_that("PM2.5 versions build the same S3 keys", {
  for (case in parity$pm25) {
    spec <- .pm25_spec(case$version)
    info <- paste(case$version, case$region, case$year, case$month %||% "annual")
    expect_equal(spec$years, as.integer(unlist(case$years)), info = info)
    expect_equal(spec$variable, case$variable, info = info)
    expect_setequal(names(spec$regions), unlist(case$regions))
    url <- .pm25_get_aws_url(case$year, case$month, case$region, case$version)
    expect_equal(sub(.pm25_bucket_url, "", url, fixed = TRUE), case$key, info = info)
  }
})

test_that("cpcb_raw_to_long matches Python", {
  case <- parity$raw_to_long
  raw <- as.data.frame(lapply(case$raw, .vec), check.names = FALSE)
  got <- cpcb_raw_to_long(raw, station = case$station)
  want <- case$out

  expect_equal(got$station_id, .vec(want$station_id))
  expect_equal(got$city, .vec(want$city))
  expect_equal(format(got$timestamp, "%Y-%m-%d %H:%M:%S"), .vec(want$timestamp))
  expect_equal(got$pollutant, .vec(want$pollutant))
  expect_equal(got$unit, .vec(want$unit))
  expect_equal(got$value, .vec(want$value))
})

test_that("cpcb_tidy_daily matches daily_aqi_workbook_to_long", {
  case <- parity$workbook_to_long
  sheet <- as.data.frame(lapply(case$workbook, .vec), check.names = FALSE)
  got <- cpcb_tidy_daily(sheet, year = case$year)

  expect_equal(as.character(got$date), .vec(case$out$date))
  expect_equal(got$value, as.numeric(.vec(case$out$aqi)))
})

test_that("health impacts and pollutant categories match Python", {
  values <- .vec(lapply(parity$health_impact, `[[`, "aqi"))
  expect_equal(aqi_health_impact(values), vapply(parity$health_impact, `[[`, "", "impact"))
  for (case in parity$pollutant_category) {
    expect_equal(aqi_pollutant_category(case$pollutant, case$concentration), case$category)
  }
})

test_that("US AQI breakpoints match Python", {
  expect_setequal(names(.us_aqi_pollutants), names(parity$us_pollutants))
  for (name in names(parity$us_pollutants)) {
    py <- parity$us_pollutants[[name]]
    expect_equal(.us_aqi_pollutants[[name]]$bands, as.numeric(unlist(py$bands)), info = name)
    expect_equal(.us_aqi_pollutants[[name]]$decimals, py$decimals, info = name)
  }
})

test_that("US AQI labels, sub-indices and categories match Python", {
  cases <- parity$us_pollutant_name
  got <- us_aqi_pollutant_name(vapply(cases, `[[`, "", "label"))
  expect_equal(got, .vec(lapply(cases, `[[`, "name")))
  for (case in parity$us_sub_index) {
    expect_equal(
      us_aqi_sub_index(case$pollutant, case$concentration), case$sub_index %||% NA_real_,
      tolerance = 1e-9, info = paste(case$pollutant, case$concentration)
    )
  }
  values <- .vec(lapply(parity$us_aqi_category, `[[`, "aqi"))
  expect_equal(us_aqi_category(values), vapply(parity$us_aqi_category, `[[`, "", "category"))
  expect_equal(us_aqi_color(values), .vec(lapply(parity$us_aqi_category, `[[`, "color")))
  expect_equal(
    us_aqi_color(values, color_vision_assist = TRUE),
    .vec(lapply(parity$us_aqi_category, `[[`, "color_assist"))
  )
})

test_that("compute_us_aqi matches Python", {
  for (case in parity$compute_us_aqi) {
    input <- lapply(case$input, function(v) if (is.null(v)) NA_real_ else v)
    got <- compute_us_aqi(input)
    info <- jsonlite::toJSON(case$input, auto_unbox = TRUE, null = "null")
    expect_equal(got$aqi, case$aqi %||% NA_integer_, info = info)
    expect_equal(got$category, case$category %||% NA_character_, info = info)
    expect_equal(got$dominant_pollutant, case$dominant_pollutant %||% NA_character_, info = info)
    want <- unlist(case$sub_indices)
    if (is.null(want)) {
      expect_length(got$sub_indices, 0)
      next
    }
    expect_equal(got$sub_indices[names(want)], want, tolerance = 1e-9, info = info)
    expect_setequal(names(got$sub_indices), names(want))
  }
})

# Data frame against the JSON columns of a Python one
.expect_columns <- function(got, want, info = NULL) {
  expect_setequal(names(got), names(want))
  for (col in names(want)) {
    value <- got[[col]]
    if (inherits(value, "POSIXt")) value <- format(value, "%Y-%m-%d %H:%M:%S", tz = "UTC")
    if (inherits(value, "Date")) value <- as.character(value)
    expect_equal(value, .vec(want[[col]]) %||% value[0], info = paste(info, col))
  }
}

test_that("live data reshape like Python", {
  case <- parity$live
  data <- case$data
  data$metrics <- do.call(rbind, lapply(data$metrics, function(m) {
    as.data.frame(lapply(m, function(v) if (is.null(v)) NA else v))
  }))
  .expect_columns(cpcb_live_to_long(data), case$long, "long")
  .expect_columns(cpcb_live_metrics(data), case$metrics, "metrics")
})

test_that("nearest_stations matches Python", {
  case <- parity$nearest_stations
  from <- as.data.frame(lapply(case$from, .vec))
  to <- as.data.frame(lapply(case$to, .vec))
  for (k in names(case$out)) {
    .expect_columns(nearest_stations(from, to, k = as.integer(k)), case$out[[k]], k)
  }
})

test_that("cpcb_tidy_daily matches Python's", {
  case <- parity$tidy_daily
  sheet <- as.data.frame(lapply(parity$workbook_to_long$workbook, .vec), check.names = FALSE)
  .expect_columns(cpcb_tidy_daily(sheet), case$no_year, "no year")
  .expect_columns(cpcb_tidy_daily(sheet, year = 2024), case$year, "2024")
})

test_that("OAQ nearest CPCB stations and city tally match Python", {
  case <- parity$oaq
  sensors <- as.data.frame(lapply(case$sensors, .vec))
  .expect_columns(oaq_nearest_cpcb(sensors, k = 2), case$nearest, "nearest")
  .expect_columns(oaq_city_tally(sensors), case$tally, "tally")
})

test_that("sensor quality checks match Python", {
  q <- parity$sensor_qa
  readings <- data.frame(
    sensor_id = .vec(q$readings$sensor_id),
    timestamp = as.POSIXct(.vec(q$readings$timestamp), tz = "UTC"),
    pm25 = as.numeric(.vec(q$readings$pm25))
  )
  daily <- readings_mean(readings, min_readings = 40)
  .expect_columns(readings_mean(readings), q$daily, "daily")
  .expect_columns(daily, q$daily_40, "daily_40")
  .expect_columns(readings_mean(readings, by = "hour"), q$hourly_mean, "hourly")
  .expect_columns(
    sensor_completeness(readings, "2026-01-01", "2026-01-05", ids = c("a", "b", "c", "d", "e")),
    q$completeness, "completeness"
  )
  .expect_columns(sensor_plausibility(readings), q$plausibility, "plausibility")
  .expect_columns(collocated_precision(daily), q$precision, "precision")
  .expect_columns(peer_ratio(daily), q$peer_ratio, "peer_ratio")
  ref <- daily[daily$sensor_id == "a", c("date", "pm25")]
  names(ref)[2] <- "reference"
  paired <- merge(daily[daily$sensor_id != "a", ], ref, by = "date")
  .expect_columns(sensor_accuracy(paired, min_days = 2), q$accuracy, "accuracy")
  hourly <- as.data.frame(lapply(q$humidity_input, .vec))
  .expect_columns(ratio_by_humidity(hourly), q$humidity, "humidity")
})

test_that("compare_daily_records and daily_record_summary match Python", {
  case <- parity$daily_records
  readings <- data.frame(
    sensor_id = .vec(case$readings$sensor_id),
    timestamp = as.POSIXct(.vec(case$readings$timestamp), tz = "UTC"),
    pm25 = as.numeric(.vec(case$readings$pm25))
  )
  records <- data.frame(
    sensor_id = .vec(case$records$sensor_id), date = as.Date(.vec(case$records$date)),
    pm25 = as.numeric(.vec(case$records$pm25))
  )
  compared <- compare_daily_records(readings, records)
  .expect_columns(compared, case$compared, "compared")
  .expect_columns(daily_record_summary(compared), case$summary, "summary")
})
