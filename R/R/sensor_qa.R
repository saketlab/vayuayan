# Quality checks of air sensor readings. Targets: US EPA, Duvall et al.
# (2021), "Performance Testing Protocols, Metrics, and Target Values for Fine
# Particulate Matter Air Sensors", EPA/600/R-20/280.

.epa_pm25_targets <- list(
  completeness = 0.75, sd = 5, cv_pct = 30, slope = c(0.65, 1.35),
  intercept = c(-5, 5), r2 = 0.70, rmse = 7, nrmse_pct = 30
)
.readings_per_day <- 96

# Readings with a time and a finite value, one row per sensor and time
.usable_readings <- function(readings, value, id_col, time_col) {
  df <- readings[!is.na(readings[[time_col]]) & .has_value(readings[[value]]), , drop = FALSE]
  .average_duplicates(df, id_col, time_col, value)
}

#' Daily or hourly means of sensor readings
#'
#' @param readings Data frame with one row per reading, such as
#'   \code{oaq_readings()} or \code{cpcb_raw_to_long()} (with
#'   \code{id_col = "station_id"}, \code{value = "value"}).
#' @param value Column to average.
#' @param by \code{"day"} or \code{"hour"}.
#' @param min_readings Fewest readings for a mean. \code{NULL} uses 75 \% of
#'   the 15-minute readings of the period (72 a day, 3 an hour), the EPA
#'   completeness rule.
#' @param id_col,time_col Sensor and time columns.
#' @return Data frame with \code{id_col}, \code{date} (\code{Date}) or
#'   \code{hour} (POSIXct), \code{value} and \code{n}, for the periods with
#'   enough readings. Days are taken in the time zone of \code{time_col}, and
#'   readings repeated at one time are averaged and count once.
#' @examples
#' r <- data.frame(
#'   sensor_id = "s1",
#'   timestamp = as.POSIXct("2026-01-01", tz = "UTC") + 900 * 0:95,
#'   pm25 = 1:96
#' )
#' readings_mean(r)
#' @export
readings_mean <- function(readings, value = "pm25", by = "day", min_readings = NULL,
                          id_col = "sensor_id", time_col = "timestamp") {
  if (!by %in% c("day", "hour")) stop('by must be "day" or "hour"', call. = FALSE)
  per <- if (by == "day") .readings_per_day else .readings_per_day / 24
  need <- min_readings %||% ceiling(.epa_pm25_targets$completeness * per)
  df <- .usable_readings(readings, value, id_col, time_col)
  key <- if (by == "day") "date" else "hour"
  period <- if (by == "day") {
    .local_date(df[[time_col]])
  } else {
    as.POSIXct(trunc(df[[time_col]], "hours"))
  }
  group <- paste(df[[id_col]], format(period), sep = "\r")
  first <- !duplicated(group)
  out <- data.frame(id = df[[id_col]][first], stringsAsFactors = FALSE)
  out[[key]] <- period[first]
  out[[value]] <- as.numeric(tapply(df[[value]], group, mean)[group[first]])
  out$n <- as.integer(tapply(df[[value]], group, length)[group[first]])
  names(out)[1] <- id_col
  out <- out[out$n >= need, , drop = FALSE]
  out <- out[order(out[[id_col]], out[[key]], method = "radix"), , drop = FALSE]
  rownames(out) <- NULL
  out
}

#' Completeness of sensor readings
#'
#' @description
#' Share of the expected 15-minute readings, and of days with a valid
#' 24-hour average (75 \% of the readings, the EPA rule), per sensor. Days are
#' taken in the time zone of \code{time_col}, and a repeated time counts once.
#'
#' @inheritParams readings_mean
#' @param start,end First and last day of the period (inclusive).
#' @param ids Sensors to report, also those without readings. \code{NULL}:
#'   the sensors in \code{readings}.
#' @return Data frame with \code{id_col}, \code{readings_pct},
#'   \code{valid_days} and \code{valid_days_pct}, sorted by \code{id_col}.
#' @examples
#' r <- data.frame(
#'   sensor_id = "s1",
#'   timestamp = as.POSIXct("2026-01-01", tz = "UTC") + 900 * 0:95,
#'   pm25 = 10
#' )
#' sensor_completeness(r, "2026-01-01", "2026-01-02")
#' @export
sensor_completeness <- function(readings, start, end, value = "pm25", ids = NULL,
                                id_col = "sensor_id", time_col = "timestamp") {
  days <- seq(as.Date(start), as.Date(end), by = "day")
  df <- .usable_readings(readings, value, id_col, time_col)
  day <- .local_date(df[[time_col]])
  df <- df[day >= min(days) & day <= max(days), , drop = FALSE]
  day <- .local_date(df[[time_col]])
  ids <- sort(unique(as.character(ids %||% df[[id_col]])), method = "radix")
  need <- ceiling(.epa_pm25_targets$completeness * .readings_per_day)
  per_day <- table(factor(df[[id_col]], levels = ids), day)
  total <- if (length(per_day)) rowSums(per_day) else stats::setNames(rep(0, length(ids)), ids)
  valid <- if (length(per_day)) rowSums(per_day >= need) else total
  out <- data.frame(
    id = ids,
    readings_pct = 100 * as.numeric(total[ids]) / (.readings_per_day * length(days)),
    valid_days = as.integer(valid[ids]),
    stringsAsFactors = FALSE
  )
  out$valid_days_pct <- 100 * out$valid_days / length(days)
  names(out)[1] <- id_col
  out
}

#' Plausibility flags of sensor readings
#'
#' @description
#' Screening flags per sensor: negative, zero and extreme readings, stuck
#' runs and spikes. These are screening rules, not EPA targets: a flag marks
#' readings to examine, not proof of a fault. A repeated time counts once.
#'
#' @inheritParams readings_mean
#' @param value Column to check, such as \code{"pm25"} or \code{"temp"}.
#' @param max_value Readings above it are flagged.
#' @param stuck_run Runs of at least this many equal consecutive readings
#'   are flagged as stuck (8 readings are 2 hours).
#' @param spike_factor,spike_min A reading above \code{spike_factor} times
#'   the median of the \code{spike_window} readings around it, and above
#'   \code{spike_min}, is a spike.
#' @param spike_window Readings in the centered window (odd); the median needs
#'   at least half of them.
#' @return Data frame with \code{id_col}, \code{readings},
#'   \code{negative_pct}, \code{zero_pct}, \code{above_max_pct},
#'   \code{stuck_pct} and \code{spikes_pct}.
#' @examples
#' r <- data.frame(
#'   sensor_id = "s1",
#'   timestamp = as.POSIXct("2026-01-01", tz = "UTC") + 900 * 0:19,
#'   pm25 = c(rep(5, 10), 900, 6:14)
#' )
#' sensor_plausibility(r)
#' @export
sensor_plausibility <- function(readings, value = "pm25", max_value = 1000, stuck_run = 8,
                                spike_factor = 10, spike_min = 100, spike_window = 9,
                                id_col = "sensor_id", time_col = "timestamp") {
  df <- .usable_readings(readings, value, id_col, time_col)
  ids <- sort(unique(as.character(df[[id_col]])), method = "radix")
  rows <- lapply(ids, function(id) {
    g <- df[df[[id_col]] == id, , drop = FALSE]
    v <- g[[value]][order(g[[time_col]], method = "radix")]
    runs <- rle(v)
    run <- rep(runs$lengths, runs$lengths)
    around <- .centred_median(v, spike_window)
    spikes <- !is.na(around) & v > spike_factor * around & v > spike_min
    data.frame(
      id = id, readings = length(v), negative_pct = 100 * mean(v < 0),
      zero_pct = 100 * mean(v == 0), above_max_pct = 100 * mean(v > max_value),
      stuck_pct = 100 * mean(run >= stuck_run), spikes_pct = 100 * mean(spikes),
      stringsAsFactors = FALSE
    )
  })
  out <- do.call(rbind, c(list(data.frame(
    id = character(), readings = integer(), negative_pct = numeric(), zero_pct = numeric(),
    above_max_pct = numeric(), stuck_pct = numeric(), spikes_pct = numeric()
  )), rows))
  names(out)[1] <- id_col
  out
}

# Median of the window around each value, NA with under half a window, as pandas rolling(center = TRUE)
.centred_median <- function(v, window) {
  before <- window %/% 2
  after <- window - before - 1
  n <- length(v)
  around <- rep(NA_real_, n)
  ends <- seq_len(n)
  # runmed takes only odd windows and leaves the first and last half window
  if (window %% 2 == 1 && n >= window) {
    inner <- (before + 1):(n - after)
    around[inner] <- as.numeric(stats::runmed(v, window, endrule = "keep"))[inner]
    ends <- setdiff(ends, inner)
  }
  around[ends] <- vapply(ends, function(i) {
    w <- v[max(1, i - before):min(n, i + after)]
    if (length(w) >= before + 1) stats::median(w) else NA_real_
  }, numeric(1))
  around
}

#' Precision of collocated sensors
#'
#' @description
#' Spread across collocated sensors on each day, as in the EPA protocol.
#'
#' @param daily Daily means of sensors at one place (\code{readings_mean()}).
#' @param value Column of the daily means.
#' @param min_sensors Fewest sensors with a mean on a day.
#' @param date_col Day column.
#' @return Data frame with \code{date_col}, \code{sensors}, \code{mean},
#'   \code{sd} (sample standard deviation across the sensors) and
#'   \code{cv_pct}, per day with enough sensors.
#' @examples
#' daily <- data.frame(
#'   sensor_id = rep(c("a", "b", "c"), 2), date = rep(as.Date("2026-01-01") + 0:1, each = 3),
#'   pm25 = c(10, 12, 14, 20, 20, 26)
#' )
#' collocated_precision(daily)
#' @export
collocated_precision <- function(daily, value = "pm25", min_sensors = 3, date_col = "date") {
  df <- daily[.has_value(daily[[value]]), , drop = FALSE]
  days <- sort(unique(df[[date_col]]))
  rows <- lapply(seq_along(days), function(i) {
    v <- df[[value]][df[[date_col]] == days[i]]
    data.frame(sensors = length(v), mean = mean(v), sd = if (length(v) > 1) stats::sd(v) else NA_real_)
  })
  out <- do.call(rbind, c(list(data.frame(sensors = integer(), mean = numeric(), sd = numeric())), rows))
  out <- cbind(stats::setNames(data.frame(days), date_col), out)
  out$cv_pct <- 100 * out$sd / out$mean
  out <- out[out$sensors >= min_sensors, , drop = FALSE]
  rownames(out) <- NULL
  out
}

#' Departure of each collocated sensor from the others
#'
#' @description
#' On days with at least \code{min_sensors} sensors, each sensor's daily mean
#' over the median of the other sensors.
#'
#' @inheritParams collocated_precision
#' @param tolerance Ratios within \code{1 +/- tolerance} count as agreeing.
#' @param id_col Sensor column.
#' @return Data frame with \code{id_col}, \code{days}, \code{median_ratio}
#'   and \code{within_pct}, sorted by \code{median_ratio}. Non-finite ratios,
#'   such as against a peer median of 0, are left out.
#' @examples
#' daily <- data.frame(
#'   sensor_id = rep(c("a", "b", "c"), 2), date = rep(as.Date("2026-01-01") + 0:1, each = 3),
#'   pm25 = c(10, 12, 24, 20, 20, 40)
#' )
#' peer_ratio(daily)
#' @export
peer_ratio <- function(daily, value = "pm25", min_sensors = 3, tolerance = 0.3,
                       id_col = "sensor_id", date_col = "date") {
  df <- daily[.has_value(daily[[value]]), , drop = FALSE]
  ids <- sort(unique(as.character(df[[id_col]])), method = "radix")
  days <- sort(unique(df[[date_col]]))
  # a sensor with several rows on a day takes their arithmetic mean
  wide <- unname(tapply(
    df[[value]],
    list(factor(df[[date_col]], levels = days), factor(as.character(df[[id_col]]), levels = ids)),
    mean
  ))
  wide <- wide[rowSums(!is.na(wide)) >= min_sensors, , drop = FALSE]
  rows <- lapply(seq_along(ids), function(j) {
    others <- apply(wide[, -j, drop = FALSE], 1, stats::median, na.rm = TRUE)
    ratio <- wide[, j] / others
    ratio <- ratio[is.finite(ratio)]
    data.frame(
      id = ids[j], days = length(ratio),
      median_ratio = if (length(ratio)) stats::median(ratio) else NA_real_,
      within_pct = if (length(ratio)) 100 * mean(abs(ratio - 1) <= tolerance) else NA_real_,
      stringsAsFactors = FALSE
    )
  })
  out <- do.call(rbind, c(list(data.frame(
    id = character(), days = integer(), median_ratio = numeric(), within_pct = numeric()
  )), rows))
  out <- out[order(out$median_ratio, out$id, method = "radix"), , drop = FALSE]
  names(out)[1] <- id_col
  rownames(out) <- NULL
  out
}

#' Accuracy of sensors against a reference
#'
#' @description
#' Per sensor: least-squares slope and intercept of the sensor on the
#' reference, R squared, RMSE and NRMSE, and which EPA targets are met.
#'
#' @param paired Data frame with one row per sensor and day, with the sensor
#'   and the reference daily means.
#' @param sensor,reference Columns of the sensor and reference values.
#' @param min_days Fewest paired days for a sensor to be reported.
#' @param id_col Sensor column.
#' @return Data frame with \code{id_col}, \code{days}, \code{slope},
#'   \code{intercept}, \code{r2}, \code{rmse}, \code{nrmse_pct},
#'   \code{slope_ok}, \code{intercept_ok}, \code{r2_ok}, \code{error_ok}
#'   (RMSE or NRMSE), which are never \code{NA}, and \code{targets_met} (0 to
#'   4).
#' @examples
#' paired <- data.frame(sensor_id = "s1", reference = 1:40, pm25 = 2 + 1.1 * (1:40))
#' sensor_accuracy(paired)
#' @export
sensor_accuracy <- function(paired, sensor = "pm25", reference = "reference",
                            min_days = 30, id_col = "sensor_id") {
  t <- .epa_pm25_targets
  df <- .finite_rows(paired, c(sensor, reference))
  ids <- sort(unique(as.character(df[[id_col]])), method = "radix")
  rows <- lapply(ids, function(id) {
    g <- df[df[[id_col]] == id, , drop = FALSE]
    if (nrow(g) < min_days) {
      return(NULL)
    }
    x <- g[[reference]]
    y <- g[[sensor]]
    slope <- sum((x - mean(x)) * (y - mean(y))) / sum((x - mean(x))^2)
    rmse <- sqrt(mean((y - x)^2))
    out <- data.frame(
      id = id, days = nrow(g), slope = slope, intercept = mean(y) - slope * mean(x),
      r2 = stats::cor(x, y)^2, rmse = rmse, nrmse_pct = 100 * rmse / mean(x),
      stringsAsFactors = FALSE
    )
    # an undefined fit (constant sensor or reference) meets no target
    out$slope_ok <- isTRUE(out$slope >= t$slope[1] && out$slope <= t$slope[2])
    out$intercept_ok <- isTRUE(out$intercept >= t$intercept[1] && out$intercept <= t$intercept[2])
    out$r2_ok <- isTRUE(out$r2 >= t$r2)
    out$error_ok <- isTRUE(rmse <= t$rmse || out$nrmse_pct <= t$nrmse_pct)
    out$targets_met <- as.integer(out$slope_ok + out$intercept_ok + out$r2_ok + out$error_ok)
    out
  })
  out <- do.call(rbind, c(list(data.frame(
    id = character(), days = integer(), slope = numeric(), intercept = numeric(),
    r2 = numeric(), rmse = numeric(), nrmse_pct = numeric(), slope_ok = logical(),
    intercept_ok = logical(), r2_ok = logical(), error_ok = logical(), targets_met = integer()
  )), rows))
  names(out)[1] <- id_col
  rownames(out) <- NULL
  out
}

#' Sensor-to-reference ratio by relative humidity
#'
#' @description
#' Low-cost optical sensors can read high in humid air. Hours with a
#' reference value below \code{min_reference} are left out, as the ratio is
#' unstable there.
#'
#' @param hourly Data frame with hourly sensor, reference and humidity
#'   values.
#' @param sensor,reference,rh Their columns.
#' @param breaks Humidity band limits (bands are \code{(lower, upper]}, and
#'   the first band also includes its lower limit).
#' @param min_reference Smallest reference value used.
#' @return Data frame with \code{band} (\code{"40-50"} for 40 < RH <= 50),
#'   \code{hours}, \code{median_ratio}, \code{q25} and \code{q75}.
#' @examples
#' hourly <- data.frame(sensor = c(20, 30, 45), reference = c(20, 20, 30), rh = c(35, 65, 95))
#' ratio_by_humidity(hourly)
#' @export
ratio_by_humidity <- function(hourly, sensor = "sensor", reference = "reference", rh = "rh",
                              breaks = c(0, 40, 50, 60, 70, 80, 90, 100), min_reference = 5) {
  df <- .finite_rows(hourly, c(sensor, reference, rh))
  df <- df[df[[reference]] >= min_reference, , drop = FALSE]
  labels <- sprintf("%g-%g", utils::head(breaks, -1), utils::tail(breaks, -1))
  band <- cut(df[[rh]], breaks, labels = labels, include.lowest = TRUE)
  ratio <- df[[sensor]] / df[[reference]]
  rows <- lapply(labels, function(b) {
    r <- ratio[!is.na(band) & band == b]
    if (!length(r)) {
      return(NULL)
    }
    q <- stats::quantile(r, c(0.25, 0.75), names = FALSE)
    data.frame(band = b, hours = length(r), median_ratio = stats::median(r), q25 = q[1], q75 = q[2])
  })
  do.call(rbind, c(list(data.frame(
    band = character(), hours = integer(), median_ratio = numeric(), q25 = numeric(), q75 = numeric()
  )), rows))
}
