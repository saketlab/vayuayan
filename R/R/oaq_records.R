# OAQ's daily records against the 15-minute readings of the same day. Since
# about March 2026 the daily value is often the last reading of the day
# instead of its mean.

.record_statistics <- c("mean", "last", "max", "median", "last_2_mean", "last_4_mean")
.record_columns <- c(
  "sensor_id", "date", "record", "n", .record_statistics,
  paste0("record_is_", .record_statistics), "class"
)

#' Compare OAQ daily records with the day's 15-minute readings
#'
#' @description
#' Each daily record against statistics of the same day's readings: the
#' mean, last, maximum and median reading and the mean of the last 2 and last
#' 4 readings.
#'
#' @param readings 15-minute readings (\code{oaq_readings()}):
#'   \code{sensor_id}, \code{timestamp} and the value column.
#' @param records Daily records (\code{oaq_daily_records()}):
#'   \code{sensor_id}, \code{date} and the value column.
#' @param value Parameter to compare.
#' @param tolerance Values within it count as equal (0.005: the daily
#'   records have 2 decimals).
#' @return Data frame with \code{sensor_id}, \code{date}, \code{record},
#'   \code{n}, the statistics, \code{record_is_<statistic>} for each, and
#'   \code{class}: \code{"mean"}, \code{"last"}, \code{"both"} (equal to the
#'   mean and to the last reading) or \code{"neither"}. One row per
#'   sensor-day with a record and readings; missing readings are left out.
#' @examples
#' readings <- data.frame(
#'   sensor_id = "s1",
#'   timestamp = as.POSIXct("2026-03-10", tz = "UTC") + 900 * 0:3,
#'   pm25 = c(10, 10, 10, 300)
#' )
#' records <- data.frame(sensor_id = "s1", date = as.Date("2026-03-10"), pm25 = 300)
#' compare_daily_records(readings, records)
#' @export
compare_daily_records <- function(readings, records, value = "pm25", tolerance = 0.005) {
  r <- readings[!is.na(readings$timestamp) & !is.na(readings[[value]]), , drop = FALSE]
  r <- r[order(r$sensor_id, r$timestamp, method = "radix"), , drop = FALSE]
  rec <- records[!is.na(records[[value]]), , drop = FALSE]
  if (nrow(r) == 0 || nrow(rec) == 0) {
    return(.empty_records())
  }
  r$date <- as.Date(r$timestamp, tz = "UTC")
  groups <- split(r[[value]], list(r$sensor_id, format(r$date)), drop = TRUE, sep = "\r")
  keys <- do.call(rbind, strsplit(names(groups), "\r", fixed = TRUE))
  stats <- data.frame(
    sensor_id = keys[, 1], date = as.Date(keys[, 2]),
    n = vapply(groups, length, integer(1)),
    mean = vapply(groups, mean, numeric(1)),
    last = vapply(groups, function(v) v[length(v)], numeric(1)),
    max = vapply(groups, max, numeric(1)),
    median = vapply(groups, stats::median, numeric(1)),
    last_2_mean = vapply(groups, function(v) mean(utils::tail(v, 2)), numeric(1)),
    last_4_mean = vapply(groups, function(v) mean(utils::tail(v, 4)), numeric(1)),
    stringsAsFactors = FALSE, row.names = NULL
  )
  rec <- data.frame(
    sensor_id = as.character(rec$sensor_id), date = as.Date(rec$date),
    record = as.numeric(rec[[value]]), stringsAsFactors = FALSE
  )
  out <- merge(rec, stats, by = c("sensor_id", "date"))
  for (s in .record_statistics) {
    out[[paste0("record_is_", s)]] <- abs(out$record - out[[s]]) <= tolerance
  }
  out$class <- ifelse(out$record_is_mean & out$record_is_last, "both",
    ifelse(out$record_is_last, "last", ifelse(out$record_is_mean, "mean", "neither"))
  )
  out <- out[order(out$sensor_id, out$date, method = "radix"), .record_columns, drop = FALSE]
  rownames(out) <- NULL
  out
}

.empty_records <- function() {
  out <- data.frame(
    sensor_id = character(), date = as.Date(character()), record = numeric(), n = integer()
  )
  for (s in .record_statistics) out[[s]] <- numeric()
  for (s in .record_statistics) out[[paste0("record_is_", s)]] <- logical()
  out$class <- character()
  out
}

#' Audit OAQ daily records of several sensors
#'
#' @description
#' \code{oaq_check_daily_records()} for every day of some years of several
#' sensors. Today (in India) is left out by default, as its values are still
#' being written.
#'
#' @param session List returned by \code{\link{oaq_session}}.
#' @param sensors Data frame with \code{provider} and \code{sensor_id}.
#' @param years Integer years.
#' @param value Parameter to compare.
#' @param tolerance Values within it count as equal.
#' @param until First day left out (default: today in India, IST).
#' @return Data frame as \code{compare_daily_records()} with a
#'   \code{provider} column.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' audit <- oaq_audit_daily_records(
#'   oaq_session(), data.frame(provider = "cpcb", sensor_id = "103"), 2026
#' )
#' daily_record_summary(audit)
#' @export
oaq_audit_daily_records <- function(session, sensors, years, value = "pm25",
                                    tolerance = 0.005, until = NULL) {
  stop_day <- if (is.null(until)) {
    as.Date(format(Sys.time(), tz = "Asia/Kolkata", "%Y-%m-%d"))
  } else {
    as.Date(until)
  }
  frames <- lapply(seq_len(nrow(sensors)), function(i) {
    provider <- sensors$provider[i]
    sensor <- as.character(sensors$sensor_id[i])
    days <- oaq_daily_records(session, provider, sensor, years)$date
    out <- oaq_check_daily_records(
      session, provider, sensor, days[days < stop_day], value, tolerance
    )
    if (nrow(out)) cbind(provider = provider, out, stringsAsFactors = FALSE) else NULL
  })
  out <- do.call(rbind, frames)
  if (is.null(out)) {
    return(cbind(provider = character(), .empty_records()))
  }
  rownames(out) <- NULL
  out
}

#' When OAQ daily records changed from the mean to the last reading
#'
#' @description
#' Per sensor and year, how many days the daily record equals the mean, the
#' last reading or neither, counting only days whose mean and last reading
#' differ by more than \code{min_gap} (so that a record cannot match both by
#' chance), with the first day equal to only the last reading and the last
#' day equal to only the mean before it.
#'
#' @param audit Output of \code{compare_daily_records()} or
#'   \code{oaq_audit_daily_records()}.
#' @param min_gap Smallest difference between the mean and the last reading.
#' @return Data frame with (\code{provider},) \code{sensor_id}, \code{year},
#'   \code{days}, \code{clear_days}, \code{mean}, \code{last},
#'   \code{neither}, \code{last_mean_day} and \code{first_last_day}.
#' @examples
#' audit <- data.frame(
#'   sensor_id = "s", date = as.Date("2026-02-27") + 0:3,
#'   class = c("mean", "mean", "last", "last"), mean = 30, last = 90
#' )
#' daily_record_summary(audit)
#' @export
daily_record_summary <- function(audit, min_gap = 1) {
  keys <- c(if ("provider" %in% names(audit)) "provider", "sensor_id", "year")
  a <- audit
  a$sensor_id <- as.character(a$sensor_id)
  a$date <- as.Date(a$date)
  a$year <- as.integer(format(a$date, "%Y"))
  groups <- split(a, a[keys], drop = TRUE, lex.order = TRUE)
  rows <- lapply(groups, function(g) {
    clear <- g[abs(g$mean - g$last) > min_gap, , drop = FALSE]
    last_days <- clear$date[clear$class == "last"]
    first_last <- if (length(last_days)) min(last_days) else as.Date(NA)
    mean_days <- clear$date[clear$class == "mean"]
    if (!is.na(first_last)) mean_days <- mean_days[mean_days < first_last]
    out <- g[1, keys, drop = FALSE]
    out$days <- nrow(g)
    out$clear_days <- nrow(clear)
    out$mean <- sum(clear$class == "mean")
    out$last <- sum(clear$class == "last")
    out$neither <- sum(clear$class == "neither")
    out$last_mean_day <- if (length(mean_days)) max(mean_days) else as.Date(NA)
    out$first_last_day <- first_last
    out
  })
  out <- do.call(rbind, rows)
  out <- out[do.call(order, c(unname(as.list(out[keys])), method = "radix")), , drop = FALSE]
  rownames(out) <- NULL
  out
}
