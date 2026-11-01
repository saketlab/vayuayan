test_that("plot_aqi_radial puts each day on its year ring in its CPCB category", {
  skip_if_not_installed("ggplot2")
  daily <- data.frame(
    city = "A", year = c(2023, 2024, 2024), month = c(1, 12, 2),
    day = c(1, 31, 29), value = c(40, 450, NA)
  )
  p <- plot_aqi_radial(daily)
  d <- p$data
  expect_equal(nrow(d), 365 + 366) # full calendar, gaps included
  jan1 <- d[d$date == as.Date("2023-01-01"), ]
  dec31 <- d[d$date == as.Date("2024-12-31"), ]
  expect_equal(as.character(jan1$category), "Good")
  expect_equal(as.character(dec31$category), "Severe")
  expect_lt(jan1$ring, dec31$ring)
  expect_true(jan1$angle > 0 && dec31$angle < 12)
  expect_true(is.na(d$category[d$date == as.Date("2024-02-29")]))
  expect_s3_class(ggplot2::ggplot_build(p), "ggplot_built")
})

test_that("plot_aqi_radial takes another theme and keeps its radial layout", {
  skip_if_not_installed("ggplot2")
  daily <- data.frame(date = as.Date("2024-03-01"), value = 120)
  p <- plot_aqi_radial(daily, theme = ggplot2::theme_dark())
  expect_equal(p$theme$panel.background$fill, ggplot2::theme_dark()$panel.background$fill)
  expect_s3_class(p$theme$panel.grid.major, "element_blank")
  expect_s3_class(plot_aqi_radial(daily)$theme$panel.grid.major, "element_blank")
  expect_s3_class(ggplot2::ggplot_build(p), "ggplot_built")
})


test_that("plot_aqi_radial_hourly bins hours into month rings by CPCB category", {
  skip_if_not_installed("ggplot2")
  hourly <- data.frame(
    city = c("A", "A", "A", "B"),
    timestamp = c("2023-01-01 05:00", "2024-01-09 05:30", "2023-12-31 23:00", "2024-06-01 12:00"),
    value = c(40, 80, 450, 120)
  )
  p <- plot_aqi_radial_hourly(hourly)
  d <- p$data
  cell <- function(panel, k, h) as.character(d$category[d$panel == panel & d$k == k & d$hour == h])
  expect_equal(cell("A", 1, 5), "Satisfactory") # mean of 40 and 80
  expect_equal(cell("A", 12, 23), "Severe")
  expect_true(all(is.na(d$category[d$panel == "A" & d$k %in% 2:11])))
  b <- ggplot2::ggplot_build(p)
  expect_equal(length(unique(b$layout$layout$PANEL)), 2)
  expect_equal(nrow(b$data[[3]]), 2 * 12) # ring labels in each panel
})

test_that("plot_aqi_radial_hourly draws one ring per day", {
  skip_if_not_installed("ggplot2")
  hourly <- data.frame(date = c("2024-03-01 01:00", "2024-03-03 02:00"), value = c(30, 330))
  d <- plot_aqi_radial_hourly(hourly, rings = "day")$data
  expect_equal(max(d$k), 3)
  expect_equal(as.character(d$category[d$k == 1 & d$hour == 1]), "Good")
  expect_equal(as.character(d$category[d$k == 3 & d$hour == 2]), "Very Poor")
  expect_true(all(is.na(d$category[d$k == 2])))
  expect_error(plot_aqi_radial_hourly(hourly, rings = "week"))
})

test_that("plot_aqi_radial_hourly draws times of other zones in IST", {
  skip_if_not_installed("ggplot2")
  # 23:00 UTC on 31 Dec is 04:30 IST on 1 Jan; times in UTC are IST clock times
  instant <- as.POSIXct("2023-12-31 23:00", tz = "UTC")
  attr(instant, "tzone") <- "America/New_York" # same instant, another zone
  aware <- data.frame(timestamp = instant, value = 450)
  clock <- data.frame(timestamp = as.POSIXct("2023-01-01 04:00", tz = "UTC"), value = 450)
  for (df in list(aware, clock)) {
    d <- plot_aqi_radial_hourly(df)$data
    expect_equal(as.character(d$category[d$k == 1 & d$hour == 4]), "Severe")
    expect_equal(sum(!is.na(d$category)), 1)
  }
})
