#' Daily National AQI from tidy data
#'
#' @description
#' Daily NAQI of each station from long data, such as 15-minute raw data from
#' \code{cpcb_raw_to_long()}. Values are first averaged by hour. PM10, PM2.5,
#' NO2, SO2, NH3 and Pb use the daily mean of the hourly values; CO and O3
#' use the highest 8-hour running mean (of at least 6 hourly values, or
#' \code{min_hours} when that is smaller). A sub-index needs data in at least
#' \code{min_hours} hours of the day. Each calendar day is taken in the time
#' zone of the timestamps. Readings repeated at one time are averaged once;
#' negative and non-finite readings are dropped.
#'
#' CPCB's daily bulletin reports the AQI at 4 PM from the 24 hours before it;
#' \code{day_ends_at = 16} computes the same window. CPCB validates its data
#' before publishing, so results can differ from the published AQI.
#'
#' @param long Data frame with columns \code{timestamp}, \code{pollutant},
#'   \code{value}, and optionally \code{station_id} and \code{unit}. Without
#'   a \code{unit} column, a unit in the \code{pollutant} label is used. Values
#'   in ug/m3 or mg/m3 are converted to the NAQI unit of each pollutant; values
#'   in ppb or ppm are treated as missing, with a warning.
#' @param min_hours Minimum hours with data for a sub-index (CPCB: 16).
#' @param day_ends_at Hour (1--24) at which each day's 24 hours end. 24 means
#'   calendar days. A row is dated by the day its window ends.
#' @return One row per station and date: \code{station_id}, \code{date},
#'   \code{aqi}, \code{category}, \code{dominant_pollutant},
#'   \code{n_pollutants}, \code{aqi_status} and one
#'   \code{<pollutant>_sub_index} column per pollutant with data. \code{aqi},
#'   \code{category} and \code{dominant_pollutant} are \code{NA} when the data
#'   are insufficient. \code{aqi_status} says why: \code{"too_few_hours"} when
#'   a pollutant with readings fell short of \code{min_hours}, else
#'   \code{"no_pm"}, else \code{"too_few_pollutants"}; \code{"ok"} when there
#'   is an AQI.
#' @inherit compute_aqi references
#' @examples
#' hours <- seq(as.POSIXct("2024-01-01", tz = "UTC"), by = "hour", length.out = 24)
#' long <- data.frame(
#'   timestamp = rep(hours, 3),
#'   pollutant = rep(c("PM2.5", "PM10", "NO2"), each = 24),
#'   value = rep(c(45, 80, 30), each = 24)
#' )
#' daily_aqi(long)
#' @export
daily_aqi <- function(long, min_hours = .aqi_min_hours, day_ends_at = 24) {
  .aqi_check_day_ends_at(day_ends_at)
  hourly <- .aqi_hourly_means(long)
  if (nrow(hourly) == 0) {
    return(.aqi_empty_daily())
  }

  shift <- (24 - day_ends_at) * 3600
  short_days <- character()
  # fixed order so ties match Python
  parts <- lapply(intersect(names(.aqi_pollutants), unique(hourly$pollutant)), function(name) {
    group <- hourly[hourly$pollutant == name, , drop = FALSE]
    group <- group[order(group$station_id, group$hour), , drop = FALSE]
    eight_hour <- .aqi_pollutants[[name]]$hours == 8
    if (eight_hour) {
      rows <- split(seq_len(nrow(group)), group$station_id)
      for (i in rows) {
        group$value[i] <- .aqi_rolling_8h(group$hour[i], group$value[i], min(6, min_hours))
      }
    }
    out <- .aqi_by_day(group, if (eight_hour) "max" else "mean", min_hours, shift, count = "rows")
    short_days <<- c(short_days, .aqi_short_days(out))
    out$value <- .aqi_interp(name, out$value)
    names(out)[3] <- paste0(name, "_sub_index")
    out
  })
  daily <- Reduce(function(a, b) merge(a, b, by = c("station_id", "date"), all = TRUE), parts)

  subs <- as.matrix(daily[grepl("_sub_index$", names(daily))])
  present <- !is.na(subs)
  pm_cols <- colnames(subs) %in% c("PM2.5_sub_index", "PM10_sub_index")
  daily$n_pollutants <- rowSums(present)
  daily$aqi_status <- .aqi_status(daily$n_pollutants, rowSums(present[, pm_cols, drop = FALSE]) > 0)
  ok <- daily$aqi_status == "ok"
  daily$aqi_status[!ok & .aqi_day_key(daily) %in% short_days] <- "too_few_hours"
  daily$aqi <- NA_integer_
  daily$aqi[ok] <- as.integer(.round_half_up(apply(subs[ok, , drop = FALSE], 1, max, na.rm = TRUE)))
  dominant <- colnames(subs)[max.col(replace(subs, is.na(subs), -Inf), ties.method = "first")]
  daily$dominant_pollutant <- ifelse(ok, sub("_sub_index$", "", dominant), NA_character_)
  daily$category <- ifelse(is.na(daily$aqi), NA_character_, get_aqi_categories(daily$aqi))

  daily <- daily[order(daily$station_id, daily$date), c(.aqi_daily_columns, colnames(subs))]
  rownames(daily) <- NULL
  daily
}

.aqi_daily_columns <- c("station_id", "date", "aqi", "category", "dominant_pollutant", "n_pollutants", "aqi_status")

.aqi_day_key <- function(frame) paste(frame$station_id, frame$date, sep = "\r")

# days of one pollutant with readings but too few hours, from .aqi_by_day
.aqi_short_days <- function(by_day) .aqi_day_key(by_day)[is.na(by_day$value)]

.aqi_empty_daily <- function() {
  as.data.frame(stats::setNames(
    replicate(length(.aqi_daily_columns), logical(0), simplify = FALSE),
    .aqi_daily_columns
  ))
}

.aqi_check_day_ends_at <- function(day_ends_at) {
  if (day_ends_at < 1 || day_ends_at > 24) {
    stop("day_ends_at must be an hour from 1 to 24", call. = FALSE)
  }
}

# Daily mean or maximum; count is "rows" or non-missing "values", which differ for 8-hour windows
.aqi_by_day <- function(frame, how, min_hours, shift, count) {
  # an hour is labelled by its start, so the hour starting at day_ends_at belongs to the next day
  frame$date <- .local_date(frame$hour + shift)
  key <- paste(frame$station_id, frame$date, sep = "\r")
  key <- factor(key, unique(key))
  summarise <- if (how == "max") {
    function(v) if (all(is.na(v))) NA_real_ else max(v, na.rm = TRUE)
  } else {
    function(v) mean(v, na.rm = TRUE)
  }
  value <- vapply(split(frame$value, key), summarise, numeric(1))
  n <- tabulate(if (count == "values") key[!is.na(frame$value)] else key, nlevels(key))
  value[n < min_hours] <- NA_real_
  first <- !duplicated(key)
  data.frame(station_id = frame$station_id[first], date = frame$date[first], value = unname(value))
}

# mean over (t - 8 h, t]; NA below min_values; hours without a reading still get windows
.aqi_rolling_8h <- function(hour, value, min_values, at = hour) {
  t <- as.numeric(hour)
  at <- as.numeric(at)
  first <- findInterval(at - 8 * 3600, t) + 1
  last <- findInterval(at, t)
  cs <- c(0, cumsum(value))
  n <- last - first + 1
  out <- (cs[last + 1] - cs[first]) / n
  out[n < min_values] <- NA_real_
  out
}

# Unit of each row: the unit column when filled, else the unit in the label
.aqi_row_units <- function(long) {
  label_unit <- .aqi_label_unit(as.character(long$pollutant))
  if (!"unit" %in% names(long)) {
    return(label_unit)
  }
  unit <- as.character(long$unit)
  blank <- is.na(unit) | !nzchar(trimws(unit))
  unit[blank] <- label_unit[blank]
  unit
}

.aqi_hourly_means <- function(long, name_of = aqi_pollutant_name, factor_of = .aqi_unit_factor) {
  names_found <- name_of(long$pollutant)
  factors <- factor_of(.aqi_row_units(long), names_found)
  .aqi_warn_volume(names_found, factors)
  data <- data.frame(
    station_id = if ("station_id" %in% names(long)) as.character(long$station_id) else rep("", nrow(long)),
    pollutant = names_found,
    value = suppressWarnings(as.numeric(long$value)) * factors,
    timestamp = .parse_timestamp(long$timestamp),
    stringsAsFactors = FALSE
  )
  keep <- !is.na(data$pollutant) & is.finite(data$value) & data$value >= 0 & !is.na(data$timestamp)
  data <- data[keep, , drop = FALSE]
  if (nrow(data) == 0) {
    return(data.frame(
      station_id = character(0), pollutant = character(0),
      hour = as.POSIXct(character(0), tz = "UTC"), value = numeric(0)
    ))
  }
  data <- .average_duplicates(data, c("station_id", "pollutant"), "timestamp", "value")
  hour <- as.POSIXct(trunc(data$timestamp, "hours"))
  out <- stats::aggregate(
    data$value,
    by = list(station_id = data$station_id, pollutant = data$pollutant, hour = hour),
    FUN = mean
  )
  names(out)[4] <- "value"
  out
}

# ug <-> mg factor to the NAQI unit; NA for ppb or ppm, which need temperature and pressure
.aqi_unit_factor <- function(unit, pollutant) {
  key <- paste(pollutant, unit, sep = "\r")
  first <- !duplicated(key)
  unit_once <- unit[first]
  name_once <- pollutant[first]
  mass <- .aqi_mass_unit(unit_once)
  target <- vapply(name_once, function(p) {
    if (is.na(p)) NA_character_ else .aqi_pollutants[[p]]$unit
  }, character(1))
  factor <- rep(1, length(unit_once))
  factor[which(mass == "ug" & target == "mg")] <- 1e-3
  factor[which(mass == "mg" & target == "ug")] <- 1e3
  factor[which(.aqi_volume_unit(unit_once) != "" & !is.na(name_once))] <- NA_real_
  factor[match(key, key[first])]
}
