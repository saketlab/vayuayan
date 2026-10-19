# Same figure as python/vayuayan/sensor_plots.py.

utils::globalVariables(c("reference", "sensor", "group"))

#' Daily sensor values against their reference station
#'
#' @description
#' The left panel plots each sensor-day against the reference, with the 1:1
#' line. The right panel plots the median of the sensors and of the reference
#' over time. With \code{change}, the days from that date are orange in the
#' left panel and a line marks the date in the right panel.
#'
#' @param paired Data frame with one row per sensor and day: columns
#'   \code{date}, \code{value} and \code{reference} (for example the output of
#'   \code{readings_mean()} merged with the daily means of the nearest
#'   reference station).
#' @param value Column of the sensor values.
#' @param reference Column of the reference values.
#' @param change Optional date to split the days at, such as
#'   \code{"2026-03-01"}.
#' @param sensor_label Name of the sensors in the legends.
#' @param reference_label Name of the reference in the axis label and legend.
#' @param unit Quantity and unit, for the axis labels.
#' @return A patchwork of two ggplot2 panels.
#' @examplesIf requireNamespace("ggplot2", quietly = TRUE) && requireNamespace("patchwork", quietly = TRUE)
#' paired <- data.frame(
#'   date = rep(seq(as.Date("2026-01-01"), by = "day", length.out = 90), 2),
#'   pm25 = c(runif(90, 20, 60), runif(90, 20, 60)), reference = runif(180, 20, 60)
#' )
#' plot_sensor_vs_reference(paired, change = "2026-03-01")
#' @export
plot_sensor_vs_reference <- function(paired, value = "pm25", reference = "reference",
                                     change = NULL, sensor_label = "Sensors",
                                     reference_label = "Reference",
                                     unit = "PM2.5 (\u00b5g/m\u00b3)") {
  .need_ggplot()
  if (!requireNamespace("patchwork", quietly = TRUE)) {
    stop("Package 'patchwork' is required for plot_sensor_vs_reference().", call. = FALSE)
  }
  d <- data.frame(day = as.Date(paired$date), sensor = paired[[value]], reference = paired[[reference]])
  d <- d[stats::complete.cases(d), , drop = FALSE]
  if (is.null(change)) {
    d$group <- sensor_label
    colours <- stats::setNames(.record_palette[["mean"]], sensor_label)
  } else {
    when <- as.Date(change)
    groups <- c(paste("Before", .day_label(when)), paste("From", .day_label(when)))
    # legend lists only groups with days
    d$group <- droplevels(factor(ifelse(d$day >= when, groups[2], groups[1]), levels = groups))
    colours <- stats::setNames(unname(.record_palette[c("mean", "last")]), groups)
  }
  top <- max(c(d$sensor, d$reference, 1))
  scatter <- ggplot2::ggplot(d, ggplot2::aes(reference, sensor, colour = group)) +
    ggplot2::geom_abline(slope = 1, intercept = 0, colour = .ink[["ink2"]], linetype = "dashed", linewidth = 0.4) +
    ggplot2::geom_point(size = 0.9, alpha = 0.55) +
    ggplot2::annotate("text", x = top, y = top, label = "1:1", hjust = 1.2, vjust = 1.5, size = 3.2, colour = .ink[["ink2"]]) +
    ggplot2::scale_colour_manual(values = colours) +
    ggplot2::coord_cartesian(xlim = c(0, top * 1.03), ylim = c(0, top * 1.03), expand = FALSE) +
    ggplot2::labs(x = paste(reference_label, "daily", unit), y = paste(sensor_label, "daily", unit)) +
    theme_vayuayan() +
    ggplot2::guides(colour = ggplot2::guide_legend(override.aes = list(size = 2.5, alpha = 1)))

  median <- stats::aggregate(cbind(sensor, reference) ~ day, d, stats::median)
  series_names <- c(sensor_label, reference_label)
  series <- ggplot2::ggplot(median, ggplot2::aes(day)) +
    ggplot2::geom_line(ggplot2::aes(y = reference, colour = reference_label), linewidth = 0.7) +
    ggplot2::geom_line(ggplot2::aes(y = sensor, colour = sensor_label), linewidth = 0.7) +
    ggplot2::scale_colour_manual(
      values = stats::setNames(c(.record_palette[["mean"]], .ink[["ink"]]), series_names),
      breaks = series_names
    ) +
    ggplot2::labs(title = "Median of the sensors, day by day", x = NULL, y = unit) +
    theme_vayuayan()
  patchwork::wrap_plots(scatter, .mark_change(series, change), widths = c(1, 1.6))
}
