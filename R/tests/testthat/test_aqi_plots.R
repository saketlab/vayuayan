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

