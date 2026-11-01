# Radial calendar of daily AQI (ggplot2).

utils::globalVariables(c("ring", "angle", "width", "category"))

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
  hole <- 1.5
  levels <- names(.aqi_colours)
  cal$category <- factor(get_aqi_categories(cal$value), levels = levels)
  cal$ring <- year - years[1] + 1 + hole

  ranges <- paste0(.aqi_bands[c(TRUE, FALSE)], "-", .aqi_bands[c(FALSE, TRUE)])
  p <- ggplot2::ggplot(cal, ggplot2::aes(angle, ring, fill = category)) +
    ggplot2::geom_tile(ggplot2::aes(width = width), height = 0.9, show.legend = TRUE) +
    ggplot2::scale_fill_manual(
      values = .aqi_colours, limits = levels,
      labels = paste0(levels, "\n", ranges), na.value = "#d9d9d9",
      guide = ggplot2::guide_legend(nrow = 1)
    ) +
    ggplot2::scale_x_continuous(
      limits = c(0, 12), breaks = 0:11 + 0.5, labels = month.abb, expand = c(0, 0)
    ) +
    ggplot2::scale_y_continuous(limits = c(0, max(cal$ring) + 0.5), expand = c(0, 0)) +
    ggplot2::coord_polar(start = 0, clip = "off") +
    ggplot2::labs(
      title = "Daily Air Quality Index",
      subtitle = sprintf("One ring per year: %d at the centre, %d at the edge", years[1], years[2])
    ) +
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
  if (length(unique(cal$panel)) > 1) {
    p <- p + ggplot2::facet_wrap(~panel, ncol = ncol)
  }
  p
}
