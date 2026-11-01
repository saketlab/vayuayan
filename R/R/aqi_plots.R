# Radial AQI plots (ggplot2): daily calendar and 24-hour clock.

utils::globalVariables(c("ring", "angle", "width", "category", "hour", "y", "label", "x"))

.radial_hole <- 1.5 # empty centre, in rings, so the inner ring is not a point

# CPCB category colours, with the band in each legend label
.aqi_radial_fill <- function() {
  levels <- names(.aqi_colours)
  ranges <- paste0(.aqi_bands[c(TRUE, FALSE)], "-", .aqi_bands[c(FALSE, TRUE)])
  ggplot2::scale_fill_manual(
    values = .aqi_colours, limits = levels,
    labels = paste0(levels, "\n", ranges), na.value = "#d9d9d9",
    guide = ggplot2::guide_legend(nrow = 1)
  )
}

.aqi_radial_theme <- function(theme) {
  theme +
    ggplot2::theme(
      panel.grid.major = ggplot2::element_blank(),
      panel.grid.minor = ggplot2::element_blank(),
      axis.line = ggplot2::element_blank(),
      axis.ticks = ggplot2::element_blank(),
      axis.title = ggplot2::element_blank(),
      axis.text.y = ggplot2::element_blank(),
      strip.text = ggplot2::element_text(face = "bold", size = ggplot2::rel(1.3)),
      legend.position = "top",
      legend.title = ggplot2::element_blank(),
      legend.text = ggplot2::element_text(lineheight = 0.9),
      legend.key.width = ggplot2::unit(2.5, "lines"),
      plot.title = ggplot2::element_text(face = "bold", size = ggplot2::rel(2))
    )
}

#' Radial calendar of daily AQI
#'
#' @description
#' Draws each day as a coloured cell on a circle. Each year is one ring, with
#' the first year at the centre and the last at the edge. January is at 12
#' o'clock and the months run clockwise. Cells take the colour of the CPCB AQI
#' category (Good to Severe). Days without a value are grey. With a
#' \code{city} column there is one circle per city.
#'
#' @param daily Data frame with a numeric \code{value} column (daily AQI) and
#'   either a \code{date} column or \code{year}, \code{month} and \code{day}
#'   columns. An optional \code{city} column gives one panel per city.
#' @param ncol Number of panel columns when there is more than one city.
#' @param theme A complete ggplot2 theme, such as \code{ggplot2::theme_dark()}.
#'   The radial layout (no grid, axis lines or ring labels; legend on top) is
#'   applied over it. Add \code{ggplot2::theme()} to the result to
#'   change single elements.
#' @return A ggplot object.
#' @examplesIf interactive() && requireNamespace("ggplot2", quietly = TRUE)
#' daily <- cpcb_city_daily(c("Hyderabad", "Chennai"), 2017:2025)
#' plot_aqi_radial(daily)
#' plot_aqi_radial(daily, theme = ggplot2::theme_dark(base_size = 12))
#' @export
plot_aqi_radial <- function(daily, ncol = 2, theme = theme_vayuayan()) {
  .need_ggplot()
  if (is.null(daily$date)) {
    daily$date <- as.Date(sprintf(
      "%d-%02d-%02d", as.integer(daily$year), as.integer(daily$month), as.integer(daily$day)
    ), optional = TRUE)
  }
  daily <- daily[!is.na(daily$date), , drop = FALSE]
  if (nrow(daily) == 0) stop("No dated rows in `daily`.", call. = FALSE)
  daily$panel <- if (is.null(daily$city)) "" else as.character(daily$city)

  # full calendar, so missing days show grey
  years <- as.integer(format(range(daily$date), "%Y"))
  days <- seq(as.Date(sprintf("%d-01-01", years[1])), as.Date(sprintf("%d-12-31", years[2])), "day")
  cal <- expand.grid(date = days, panel = unique(daily$panel), stringsAsFactors = FALSE)
  cal$value <- daily$value[match(paste(cal$panel, cal$date), paste(daily$panel, daily$date))]

  # angle in months; leap years also span 0-12
  lt <- as.POSIXlt(cal$date)
  year <- lt$year + 1900L
  leap <- (year %% 4 == 0 & year %% 100 != 0) | year %% 400 == 0
  cal$width <- 12 / (365 + leap)
  cal$angle <- (lt$yday + 0.5) * cal$width
  levels <- names(.aqi_colours)
  cal$category <- factor(get_aqi_categories(cal$value), levels = levels)
  cal$ring <- year - years[1] + 1 + .radial_hole

  p <- ggplot2::ggplot(cal, ggplot2::aes(angle, ring, fill = category)) +
    ggplot2::geom_tile(ggplot2::aes(width = width), height = 0.9, show.legend = TRUE) +
    .aqi_radial_fill() +
    ggplot2::scale_x_continuous(
      limits = c(0, 12), breaks = 0:11 + 0.5, labels = month.abb, expand = c(0, 0)
    ) +
    ggplot2::scale_y_continuous(limits = c(0, max(cal$ring) + 0.5), expand = c(0, 0)) +
    ggplot2::coord_polar(start = 0, clip = "off") +
    ggplot2::labs(
      title = "Daily Air Quality Index",
      subtitle = sprintf("One ring per year: %d at the centre, %d at the edge", years[1], years[2])
    ) +
    .aqi_radial_theme(theme)
  if (length(unique(cal$panel)) > 1) {
    p <- p + ggplot2::facet_wrap(~panel, ncol = ncol)
  }
  p
}

#' Hourly AQI as a 24-hour clock
#'
#' @description
#' The angle is the hour of the day: midnight at 12 o'clock and noon at 6
#' o'clock, running clockwise like a clock face. With \code{rings = "month"}
#' each ring is a calendar month (January at the centre, December at the edge)
#' and each cell is the mean AQI for that hour over all days of that month in
#' all years. With \code{rings = "day"} each ring is one date. Cells take the colour of
#' the CPCB AQI category; cells without a value are grey. With a \code{city}
#' column there is one clock per city.
#'
#' @param hourly Data frame with a numeric \code{value} column (hourly AQI)
#'   and a \code{timestamp} (or \code{date}) column with the time of day.
#'   The clock is always in IST. Times in UTC, the package convention for
#'   CPCB and OAQ data, are IST clock times; times in any other time zone
#'   are converted to IST. An optional \code{city} column gives one panel per
#'   city.
#' @param rings \code{"month"} or \code{"day"}.
#' @inheritParams plot_aqi_radial
#' @return A ggplot object.
#' @examplesIf requireNamespace("ggplot2", quietly = TRUE)
#' t <- seq(as.POSIXct("2024-01-01", tz = "UTC"), by = "hour", length.out = 24 * 366)
#' hr <- as.numeric(format(t, "%H"))
#' doy <- as.numeric(format(t, "%j"))
#' hourly <- data.frame(
#'   timestamp = t,
#'   value = 150 + 120 * cos(2 * pi * (doy - 15) / 366) + 60 * cos(2 * pi * (hr - 23) / 24)
#' )
#' plot_aqi_radial_hourly(hourly)
#' @export
plot_aqi_radial_hourly <- function(hourly, rings = c("month", "day"), ncol = 2,
                                   theme = theme_vayuayan()) {
  .need_ggplot()
  rings <- match.arg(rings)
  column <- if (is.null(hourly$timestamp)) "date" else "timestamp"
  t <- .parse_timestamp(hourly[[column]])
  # UTC-labelled times are IST clock times (CPCB, OAQ); other zones convert to IST
  if (!(attr(t, "tzone") %||% "") %in% c("UTC", "GMT", "Etc/UTC")) {
    t <- as.POSIXct(format(t, "%Y-%m-%d %H:%M:%S", tz = "Asia/Kolkata"), tz = "UTC")
  }
  ok <- !is.na(t)
  if (!any(ok)) stop(sprintf("No timestamped rows in `hourly$%s`.", column), call. = FALSE)
  t <- t[ok]
  lt <- as.POSIXlt(t, tz = "UTC")
  panel <- if (is.null(hourly$city)) rep("", sum(ok)) else as.character(hourly$city[ok])
  value <- as.numeric(hourly$value[ok])
  hour <- lt$hour
  if (rings == "month") {
    key <- lt$mon + 1L
    keys <- 1:12
    starts <- keys
    label <- month.abb
    what <- "One ring per month, January at the centre; each cell is the mean AQI of that hour"
  } else {
    key <- as.Date(t)
    keys <- seq(min(key), max(key), "day")
    yearly <- length(keys) > 366 # one label per year, not per month
    starts <- which(format(keys, "%d") == "01" & (!yearly | format(keys, "%m") == "01"))
    if (length(starts) == 0) starts <- 1
    label <- format(keys[starts], if (yearly) "%Y" else "%b")
    what <- "One ring per day, first day at the centre"
  }
  cells <- tapply(value, paste(panel, key, hour), mean, na.rm = TRUE)
  centres <- seq_along(keys) - 0.5 + .radial_hole
  labels <- data.frame(y = centres[starts], label = label)

  grid <- expand.grid(hour = 0:23, k = seq_along(keys), panel = sort(unique(panel)), stringsAsFactors = FALSE)
  grid$value <- as.numeric(cells[paste(grid$panel, keys[grid$k], grid$hour)])
  grid$category <- factor(get_aqi_categories(grid$value), levels = names(.aqi_colours))
  grid$ring <- centres[grid$k]
  top <- length(keys) + .radial_hole
  p <- ggplot2::ggplot(grid, ggplot2::aes(hour + 0.5, ring, fill = category)) +
    ggplot2::geom_tile(width = 1, height = 1, show.legend = TRUE) +
    # quarter-day spokes as a data layer; annotate() fails with facets
    ggplot2::geom_segment(
      data = data.frame(x = c(0, 6, 12, 18)),
      ggplot2::aes(x = x, xend = x, y = .radial_hole, yend = top), inherit.aes = FALSE,
      colour = "white", linewidth = 0.4
    ) +
    # ring labels on the midnight spoke; coord_polar draws no radial axis text
    ggplot2::geom_text(
      data = labels, ggplot2::aes(x = 0.1, y = y, label = label), inherit.aes = FALSE,
      size = 2.6, hjust = 0, colour = "grey15"
    ) +
    .aqi_radial_fill() +
    ggplot2::scale_x_continuous(
      limits = c(0, 24), breaks = seq(0, 21, 3), labels = sprintf("%02d:00", seq(0, 21, 3)),
      expand = c(0, 0)
    ) +
    ggplot2::scale_y_continuous(limits = c(0, top), expand = c(0, 0)) +
    ggplot2::coord_polar(start = 0, clip = "off") +
    ggplot2::labs(
      title = "Hourly Air Quality Index",
      subtitle = paste0("Hour of day (IST) clockwise from midnight at the top. ", what)
    ) +
    .aqi_radial_theme(theme)
  if (length(unique(grid$panel)) > 1) {
    p <- p + ggplot2::facet_wrap(~panel, ncol = ncol)
  }
  p
}
