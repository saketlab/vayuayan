# Figures of OAQ's daily records against the 15-minute readings (ggplot2).
# Blue is the daily mean of the readings, orange the last reading of the day,
# greys the days that match both or neither (a colour-blind-safe pair, CVD
# Delta E 24.7).

.record_palette <- c(mean = "#2a78d6", last = "#eb6834", both = "#c3c2b7", neither = "#52514e")
.record_labels <- c(
  mean = "Daily value = mean of the readings",
  last = "Daily value = last reading of the day",
  both = "Matches both (mean and last reading equal)",
  neither = "Matches neither"
)
.ink <- c(
  surface = "#fcfcfb", ink = "#0b0b0b", ink2 = "#52514e", muted = "#898781",
  grid = "#e1e0d9", axis = "#c3c2b7"
)

utils::globalVariables(c(
  "timestamp", "value", "day", "label", "class", "x", "y", "panel", "month",
  "share", "n", "series", "difference", "period", "record", "vjust"
))

.need_ggplot <- function() {
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("Package 'ggplot2' is required for the plot_daily_record_* functions.", call. = FALSE)
  }
}

.record_theme <- function() {
  ggplot2::theme_minimal(base_size = 10.5) +
    ggplot2::theme(
      plot.background = ggplot2::element_rect(fill = .ink[["surface"]], colour = NA),
      panel.background = ggplot2::element_rect(fill = .ink[["surface"]], colour = NA),
      panel.grid.major = ggplot2::element_line(colour = .ink[["grid"]], linewidth = 0.3),
      panel.grid.minor = ggplot2::element_blank(),
      axis.line = ggplot2::element_line(colour = .ink[["axis"]], linewidth = 0.4),
      axis.text = ggplot2::element_text(colour = .ink[["ink2"]]),
      axis.title = ggplot2::element_text(colour = .ink[["ink2"]]),
      plot.title = ggplot2::element_text(face = "bold", colour = .ink[["ink"]]),
      plot.title.position = "plot",
      legend.position = "bottom",
      legend.title = ggplot2::element_blank()
    )
}

.record_fill <- function() {
  ggplot2::scale_fill_manual(values = .record_palette, labels = .record_labels, drop = FALSE)
}

.day_label <- function(when) paste(as.integer(format(when, "%d")), format(when, "%B %Y"))

.with_key <- function(audit, labels) {
  a <- audit
  key <- paste0(if ("provider" %in% names(a)) paste0(a$provider, " ") else "", a$sensor_id)
  a$label <- ifelse(key %in% names(labels), unname(labels[key]), key)
  a$label <- factor(a$label, levels = unique(a$label))
  a$day <- as.Date(a$date)
  a$class <- factor(a$class, levels = names(.record_palette))
  a
}

#' Plot one day's readings with their mean and OAQ's daily record
#'
#' @param readings Readings of one sensor on one day (\code{oaq_readings()}).
#' @param check The day's row of \code{compare_daily_records()} or
#'   \code{oaq_check_daily_records()}.
#' @param value Parameter plotted.
#' @param title Plot title (default: sensor and date).
#' @return A ggplot object.
#' @examples
#' readings <- data.frame(
#'   sensor_id = "s1",
#'   timestamp = as.POSIXct("2026-03-10", tz = "UTC") + 900 * 0:95,
#'   pm25 = c(rep(40, 95), 120)
#' )
#' records <- data.frame(sensor_id = "s1", date = as.Date("2026-03-10"), pm25 = 120)
#' if (requireNamespace("ggplot2", quietly = TRUE)) {
#'   plot_daily_record_day(readings, compare_daily_records(readings, records))
#' }
#' @export
plot_daily_record_day <- function(readings, check, value = "pm25", title = NULL) {
  .need_ggplot()
  row <- check[1, , drop = FALSE]
  r <- readings[!is.na(readings[[value]]), , drop = FALSE]
  r <- r[order(r$timestamp), , drop = FALSE]
  r$value <- r[[value]]
  start <- as.POSIXct(format(as.Date(row$date)), tz = "UTC")
  top <- max(c(r$value, row$record, row$mean), na.rm = TRUE) * 1.15
  last_time <- if (nrow(r)) format(r$timestamp[nrow(r)], "%H:%M") else ""
  record_text <- paste0(
    "OAQ daily value ", format(row$record),
    if (isTRUE(row$record_is_last) && nrow(r)) paste0(" = last reading (", last_time, ")") else ""
  )
  mean_text <- sprintf("Mean %.2f (%d readings)", row$mean, as.integer(row$n))
  labels <- do.call(rbind, lapply(
    list(list(row$record, record_text), list(row$mean, mean_text)),
    function(l) .place_label(r$timestamp, r$value, l[[1]], l[[2]], start, top)
  ))
  lines <- data.frame(
    y = c(row$mean, row$record),
    series = factor(c("Mean of the readings", "OAQ daily value"),
      levels = c("15-minute readings", "Mean of the readings", "OAQ daily value")
    )
  )
  ggplot2::ggplot(r, ggplot2::aes(timestamp, value)) +
    ggplot2::geom_hline(data = lines, ggplot2::aes(yintercept = y, colour = series), linewidth = 0.9) +
    ggplot2::geom_line(ggplot2::aes(colour = "15-minute readings"), linewidth = 0.5) +
    ggplot2::geom_point(colour = .ink[["ink2"]], size = 0.8) +
    ggplot2::geom_point(data = utils::tail(r, 1), colour = .record_palette[["last"]], size = 3.5) +
    ggplot2::geom_text(
      data = labels, ggplot2::aes(x, y, label = label, vjust = vjust),
      hjust = 0, size = 3.4, colour = .ink[["ink"]], inherit.aes = FALSE
    ) +
    ggplot2::scale_colour_manual(
      values = c(
        "15-minute readings" = .ink[["ink2"]], "Mean of the readings" = .record_palette[["mean"]],
        "OAQ daily value" = .record_palette[["last"]]
      ),
      breaks = c("15-minute readings", "Mean of the readings", "OAQ daily value")
    ) +
    ggplot2::scale_x_datetime(
      limits = c(start, start + 86340), date_labels = "%H:%M", date_breaks = "4 hours",
      expand = c(0, 0)
    ) +
    ggplot2::scale_y_continuous(limits = c(0, top), expand = c(0, 0)) +
    ggplot2::labs(
      title = title %||% paste0("Sensor ", row$sensor_id, ", ", .day_label(as.Date(row$date))),
      x = NULL, y = paste0(value, " (\u00b5g/m\u00b3)")
    ) +
    .record_theme()
}

# Where a label for a horizontal line at level fits: the start time (15-minute
# steps) and side where the fewest readings run through the label box, then
# the widest gap; the width is estimated from the number of characters.
.place_label <- function(times, values, level, text, start, top) {
  width <- nchar(text) * 0.26 * 3600
  height <- 0.065 * top
  t <- as.numeric(times)
  best <- list(score = c(-Inf, -Inf), x = start + 900, above = TRUE)
  for (lo in seq(as.numeric(start) + 900, as.numeric(start) + 86400 - width - 900, by = 900)) {
    near <- values[t >= lo - 900 & t <= lo + width + 900]
    for (above in c(TRUE, FALSE)) {
      band <- if (above) c(level, level + height) else c(level - height, level)
      hits <- sum(near >= band[1] & near <= band[2])
      gap <- if (length(near)) min(abs(near - band[1]), abs(near - band[2])) else Inf
      score <- c(-hits, gap)
      if (score[1] > best$score[1] || (score[1] == best$score[1] && score[2] > best$score[2])) {
        best <- list(score = score, x = as.POSIXct(lo, origin = "1970-01-01", tz = "UTC"), above = above)
      }
    }
  }
  data.frame(
    x = best$x, y = level, label = text, vjust = if (best$above) -0.6 else 1.6,
    stringsAsFactors = FALSE
  )
}

#' Plot which statistic each day's OAQ record equals
#'
#' @param audit Output of \code{oaq_audit_daily_records()} or
#'   \code{compare_daily_records()}.
#' @param change Optional date to mark with a vertical line.
#' @param labels Optional named character vector of row labels by sensor key
#'   (\code{"provider sensor_id"}).
#' @return A ggplot object.
#' @examples
#' audit <- data.frame(
#'   provider = "cpcb", sensor_id = "103", date = as.Date("2026-02-25") + 0:9,
#'   class = rep(c("mean", "last"), each = 5), mean = 50, last = 80, record = 50
#' )
#' if (requireNamespace("ggplot2", quietly = TRUE)) {
#'   plot_daily_record_timeline(audit, change = "2026-03-01")
#' }
#' @export
plot_daily_record_timeline <- function(audit, change = NULL, labels = NULL) {
  .need_ggplot()
  a <- .with_key(audit, labels)
  p <- ggplot2::ggplot(a, ggplot2::aes(day, label, fill = class)) +
    ggplot2::geom_tile(height = 0.68, width = 1, colour = .ink[["surface"]], linewidth = 0.1) +
    .record_fill() +
    ggplot2::scale_y_discrete(limits = rev(levels(a$label))) +
    ggplot2::scale_x_date(date_breaks = "1 month", date_labels = "%b\n%Y") +
    ggplot2::labs(
      title = "Which statistic of the day's 15-minute readings OAQ's daily value equals",
      x = NULL, y = NULL
    ) +
    .record_theme() +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_blank())
  .mark_change(p, change)
}

#' Plot OAQ's daily record against the daily mean and the last reading
#'
#' @inheritParams plot_daily_record_timeline
#' @return A ggplot object with two panels.
#' @examples
#' audit <- data.frame(
#'   sensor_id = "103", date = as.Date("2026-02-25") + 0:9,
#'   class = rep(c("mean", "last"), each = 5), mean = 50, last = 80,
#'   record = rep(c(50, 80), each = 5)
#' )
#' if (requireNamespace("ggplot2", quietly = TRUE)) plot_daily_record_scatter(audit)
#' @export
plot_daily_record_scatter <- function(audit) {
  .need_ggplot()
  panels <- c(mean = "Against the daily mean", last = "Against the last reading")
  long <- do.call(rbind, lapply(names(panels), function(stat) {
    data.frame(
      x = audit[[stat]], record = audit$record,
      class = factor(audit$class, levels = names(.record_palette)),
      panel = factor(panels[[stat]], levels = panels)
    )
  }))
  top <- max(c(long$x, long$record), na.rm = TRUE) * 1.03
  ggplot2::ggplot(long, ggplot2::aes(x, record, colour = class)) +
    ggplot2::geom_abline(slope = 1, intercept = 0, colour = .ink[["axis"]]) +
    ggplot2::geom_point(size = 1.4, alpha = 0.75) +
    ggplot2::facet_wrap(~panel) +
    ggplot2::scale_colour_manual(values = .record_palette, labels = .record_labels, drop = FALSE) +
    ggplot2::coord_equal(xlim = c(0, top), ylim = c(0, top), expand = FALSE) +
    ggplot2::labs(x = "Statistic of the day's 15-minute readings", y = "OAQ daily value") +
    ggplot2::guides(colour = ggplot2::guide_legend(nrow = 2, override.aes = list(size = 3))) +
    .record_theme() +
    ggplot2::theme(strip.text = ggplot2::element_text(face = "bold", hjust = 0, size = 11))
}

#' Plot the share of days by month that OAQ's record equals each statistic
#'
#' @inheritParams plot_daily_record_timeline
#' @return A ggplot object.
#' @examples
#' audit <- data.frame(
#'   sensor_id = "103", date = as.Date("2026-02-20") + 0:19,
#'   class = rep(c("mean", "last"), each = 10), mean = 50, last = 80, record = 50
#' )
#' if (requireNamespace("ggplot2", quietly = TRUE)) plot_daily_record_share(audit, "2026-03-01")
#' @export
plot_daily_record_share <- function(audit, change = NULL) {
  .need_ggplot()
  a <- audit
  a$month <- factor(format(as.Date(a$date), "%Y-%m"))
  a$class <- factor(a$class, levels = names(.record_palette))
  counts <- as.data.frame(table(month = a$month, class = a$class), responseName = "n")
  totals <- tapply(counts$n, counts$month, sum)
  counts$share <- 100 * counts$n / totals[counts$month]
  month_labels <- format(as.Date(paste0(levels(a$month), "-01")), "%b\n%Y")
  p <- ggplot2::ggplot(counts, ggplot2::aes(month, share, fill = class)) +
    ggplot2::geom_col(
      width = 0.72, colour = .ink[["surface"]], linewidth = 0.6,
      position = ggplot2::position_stack(reverse = TRUE)
    ) +
    ggplot2::annotate("text",
      x = seq_along(totals), y = 102.5, label = totals,
      size = 2.9, colour = .ink[["muted"]]
    ) +
    .record_fill() +
    ggplot2::scale_x_discrete(labels = month_labels) +
    ggplot2::scale_y_continuous(limits = c(0, 106), expand = c(0, 0)) +
    ggplot2::labs(
      title = "Share of days by month (number of days above each bar)",
      x = NULL, y = "Share of days (%)"
    ) +
    .record_theme() +
    ggplot2::theme(panel.grid.major.x = ggplot2::element_blank())
  if (!is.null(change)) {
    i <- match(format(as.Date(change), "%Y-%m"), levels(a$month))
    if (!is.na(i)) p <- p + ggplot2::geom_vline(xintercept = i - 0.5, colour = .ink[["ink"]])
  }
  p
}

#' Plot a sensor's OAQ daily record and daily mean over time
#'
#' @inheritParams plot_daily_record_timeline
#' @param sensor_id Sensor to plot.
#' @param title Plot title.
#' @param value Parameter name for the axis label.
#' @return A ggplot object.
#' @examples
#' audit <- data.frame(
#'   sensor_id = "103", date = as.Date("2026-02-25") + 0:9,
#'   class = "last", mean = 50 + 0:9, last = 80, record = 80 - 0:9
#' )
#' if (requireNamespace("ggplot2", quietly = TRUE)) plot_daily_record_series(audit, "103")
#' @export
plot_daily_record_series <- function(audit, sensor_id, change = NULL, title = NULL,
                                     value = "pm25") {
  .need_ggplot()
  a <- audit[as.character(audit$sensor_id) == as.character(sensor_id), , drop = FALSE]
  series_names <- c("Daily mean of the 15-minute readings", "OAQ daily value")
  long <- rbind(
    data.frame(day = as.Date(a$date), y = a$mean, series = series_names[1]),
    data.frame(day = as.Date(a$date), y = a$record, series = series_names[2])
  )
  long$series <- factor(long$series, levels = series_names)
  p <- ggplot2::ggplot(long, ggplot2::aes(day, y, colour = series, linewidth = series)) +
    ggplot2::geom_line() +
    ggplot2::scale_colour_manual(values = stats::setNames(unname(.record_palette[c("mean", "last")]), series_names)) +
    ggplot2::scale_linewidth_manual(values = stats::setNames(c(0.9, 0.6), series_names)) +
    ggplot2::scale_x_date(date_breaks = "1 month", date_labels = "%b\n%Y") +
    ggplot2::labs(
      title = title %||% paste0("Sensor ", sensor_id, ": OAQ's daily value against the daily mean"),
      x = NULL, y = paste0(value, " (\u00b5g/m\u00b3)")
    ) +
    .record_theme()
  .mark_change(p, change)
}

#' Plot how far OAQ's daily record is from the daily mean
#'
#' @description
#' Record minus mean per day and sensor, before and from the change date,
#' with the median absolute difference of each under the sensor's label.
#'
#' @inheritParams plot_daily_record_timeline
#' @param change Date that splits the days.
#' @return A ggplot object.
#' @examples
#' audit <- data.frame(
#'   provider = "cpcb", sensor_id = "103", date = as.Date("2026-02-25") + 0:9,
#'   class = rep(c("mean", "last"), each = 5), mean = 50, last = 80,
#'   record = rep(c(50, 80), each = 5)
#' )
#' if (requireNamespace("ggplot2", quietly = TRUE)) {
#'   plot_daily_record_difference(audit, "2026-03-01")
#' }
#' @export
plot_daily_record_difference <- function(audit, change, labels = NULL) {
  .need_ggplot()
  if (!requireNamespace("scales", quietly = TRUE)) {
    stop("Package 'scales' is required for plot_daily_record_difference().", call. = FALSE)
  }
  when <- as.Date(change)
  a <- .with_key(audit, labels)
  a$difference <- a$record - a$mean
  periods <- c(paste("Days before", .day_label(when)), paste("Days from", .day_label(when)))
  a$period <- factor(ifelse(a$day >= when, periods[2], periods[1]), levels = periods)
  tick <- vapply(levels(a$label), function(l) {
    med <- vapply(periods, function(p) {
      d <- a$difference[a$label == l & a$period == p]
      if (length(d)) sprintf("%.2f", stats::median(abs(d))) else "\u2013"
    }, character(1))
    paste0(l, "\nmedian absolute difference\n", paste(med, collapse = " \u2192 "))
  }, character(1))
  ggplot2::ggplot(a, ggplot2::aes(label, difference, colour = period)) +
    ggplot2::geom_hline(yintercept = 0, colour = .ink[["axis"]]) +
    ggplot2::geom_point(
      position = ggplot2::position_jitterdodge(jitter.width = 0.25, dodge.width = 0.7, seed = 1),
      size = 0.9, alpha = 0.6
    ) +
    ggplot2::scale_colour_manual(values = stats::setNames(unname(.record_palette[c("mean", "last")]), periods)) +
    ggplot2::scale_x_discrete(labels = tick) +
    ggplot2::scale_y_continuous(
      transform = scales::pseudo_log_trans(sigma = 1, base = 10),
      breaks = c(-100, -10, -1, 0, 1, 10, 100)
    ) +
    ggplot2::labs(
      title = paste("How far OAQ's daily value is from the daily mean, before and from", .day_label(when)),
      x = NULL, y = "OAQ daily value \u2212 daily mean (symlog)"
    ) +
    ggplot2::guides(colour = ggplot2::guide_legend(override.aes = list(size = 3, alpha = 1))) +
    .record_theme() +
    ggplot2::theme(panel.grid.major.x = ggplot2::element_blank())
}

.mark_change <- function(p, change) {
  if (is.null(change)) {
    return(p)
  }
  when <- as.Date(change)
  p +
    ggplot2::geom_vline(xintercept = when, colour = .ink[["ink"]]) +
    ggplot2::annotate("text",
      x = when, y = Inf, label = paste0("  ", .day_label(when)),
      hjust = 0, vjust = 1.5, size = 3.4, colour = .ink[["ink"]]
    )
}
