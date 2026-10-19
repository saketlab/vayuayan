test_that("oaq_audit_daily_records leaves out today and adds the provider", {
  asked <- NULL
  local_mocked_bindings(
    oaq_daily_records = function(session, provider, sensor_id, years) {
      data.frame(sensor_id = sensor_id, date = as.Date(c("2026-03-01", "2026-03-02")), pm25 = 10)
    },
    oaq_check_daily_records = function(session, provider, sensor_id, dates, value, tolerance) {
      asked <<- dates
      readings <- data.frame(
        sensor_id = sensor_id, timestamp = as.POSIXct("2026-03-01", tz = "UTC") + 900 * 0:3, pm25 = 10
      )
      compare_daily_records(readings, data.frame(sensor_id = sensor_id, date = as.Date("2026-03-01"), pm25 = 10))
    }
  )
  out <- oaq_audit_daily_records(list(), data.frame(provider = "cpcb", sensor_id = "1"), 2026,
    until = "2026-03-02"
  )
  expect_equal(asked, as.Date("2026-03-01"))
  expect_equal(out$provider, "cpcb")
  expect_equal(out$class, "both")
})

test_that("the daily record plots build", {
  skip_if_not_installed("ggplot2")
  skip_if_not_installed("scales")
  days <- as.Date("2026-02-20") + 0:18
  audit <- data.frame(
    provider = "cpcb", sensor_id = "103", date = days,
    class = ifelse(days < as.Date("2026-03-01"), "mean", "last"),
    mean = 50, last = 80
  )
  audit$record <- ifelse(audit$class == "mean", 50, 80)
  labels <- c("cpcb 103" = "cpcb 103 - Delhi")
  plots <- list(
    plot_daily_record_timeline(audit, "2026-03-01", labels),
    plot_daily_record_scatter(audit),
    plot_daily_record_share(audit, "2026-03-01"),
    plot_daily_record_series(audit, "103", "2026-03-01"),
    plot_daily_record_difference(audit, "2026-03-01", labels)
  )
  for (p in plots) {
    expect_s3_class(p, "ggplot")
    expect_silent(ggplot2::ggplot_build(p))
  }
  readings <- data.frame(
    sensor_id = "103", timestamp = as.POSIXct("2026-03-07", tz = "UTC") + 900 * 0:95,
    pm25 = c(rep(100, 60), rep(20, 35), 197.39)
  )
  check <- compare_daily_records(readings, data.frame(sensor_id = "103", date = as.Date("2026-03-07"), pm25 = 197.39))
  day <- plot_daily_record_day(readings, check)
  built <- ggplot2::ggplot_build(day)$data
  labels <- Filter(function(d) "label" %in% names(d), built)[[1]]$label
  expect_match(labels[1], "^OAQ daily value 197.39 = last reading")
  expect_match(labels[2], "^Mean ")
})
