#' Daily National AQI from tidy data
#'
#' @description
#' Daily NAQI of each station from long data, such as 15-minute raw data from
#' \code{cpcb_raw_to_long()}. Values are first averaged by hour. PM10, PM2.5,
#' NO2, SO2, NH3 and Pb use the daily mean of the hourly values; CO and O3
#' use the highest 8-hour running mean (of at least 6 hourly values). A
#' sub-index needs data in at least \code{min_hours} hours of the day.
#'
#' CPCB's daily bulletin reports the AQI at 4 PM from the 24 hours before it;
#' \code{day_ends_at = 16} computes the same window. CPCB validates its data
#' before publishing, so results can differ from the published AQI.
#'
#' @param long Data frame with columns \code{timestamp}, \code{pollutant},
#'   \code{value}, and optionally \code{station_id} and \code{unit}. Values in
#'   ug/m3 or mg/m3 are converted to the NAQI unit of each pollutant.
#' @param min_hours Minimum hours with data for a sub-index (CPCB: 16).
#' @param day_ends_at Hour (1--24) at which each day's 24 hours end. 24 means
#'   calendar days. A row is dated by the day its window ends.
#' @return One row per station and date: \code{station_id}, \code{date},
#'   \code{aqi}, \code{category}, \code{dominant_pollutant},
#'   \code{n_pollutants} and one \code{<pollutant>_sub_index} column per
#'   pollutant with data. \code{aqi}, \code{category} and
#'   \code{dominant_pollutant} are \code{NA} when the data are insufficient.
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
  if (day_ends_at < 1 || day_ends_at > 24) {
    stop("day_ends_at must be an hour from 1 to 24", call. = FALSE)
  }
  columns <- c("station_id", "date", "aqi", "category", "dominant_pollutant", "n_pollutants")
  hourly <- .aqi_hourly_means(long)
  if (nrow(hourly) == 0) {
    out <- as.data.frame(stats::setNames(replicate(length(columns), logical(0), simplify = FALSE), columns))
    return(out)
  }

  shift <- (24 - day_ends_at) * 3600
  # fixed order so ties match Python
  parts <- lapply(intersect(names(.aqi_pollutants), unique(hourly$pollutant)), function(name) {
    group <- hourly[hourly$pollutant == name, , drop = FALSE]
    group <- group[order(group$station_id, group$hour), , drop = FALSE]
    eight_hour <- .aqi_pollutants[[name]]$hours == 8
    if (eight_hour) {
      rows <- split(seq_len(nrow(group)), group$station_id)
      for (i in rows) {
        group$value[i] <- .aqi_rolling_8h(group$hour[i], group$value[i])
      }
    }
    # an hour is labelled by its start, so the hour starting at day_ends_at
    # belongs to the next day
    group$date <- as.Date(group$hour + shift, tz = "UTC")
    key <- paste(group$station_id, group$date, sep = "\r")
    agg <- if (eight_hour) {
      function(v) if (all(is.na(v))) NA_real_ else max(v, na.rm = TRUE)
    } else {
      function(v) mean(v, na.rm = TRUE)
    }
    first <- !duplicated(key)
    value <- vapply(split(group$value, factor(key, unique(key))), agg, numeric(1))
    hours <- as.vector(table(factor(key, unique(key))))
    value[hours < min_hours] <- NA_real_
    out <- data.frame(
      station_id = group$station_id[first],
      date = group$date[first],
      sub = .aqi_interp(name, unname(value))
    )
    names(out)[3] <- paste0(name, "_sub_index")
    out
  })
  daily <- Reduce(function(a, b) merge(a, b, by = c("station_id", "date"), all = TRUE), parts)

  subs <- as.matrix(daily[grepl("_sub_index$", names(daily))])
  present <- !is.na(subs)
  pm_cols <- colnames(subs) %in% c("PM2.5_sub_index", "PM10_sub_index")
  daily$n_pollutants <- rowSums(present)
  ok <- daily$n_pollutants >= .aqi_min_pollutants & rowSums(present[, pm_cols, drop = FALSE]) > 0
  daily$aqi <- NA_integer_
  daily$aqi[ok] <- as.integer(.round_half_up(apply(subs[ok, , drop = FALSE], 1, max, na.rm = TRUE)))
  dominant <- colnames(subs)[max.col(replace(subs, is.na(subs), -Inf), ties.method = "first")]
  daily$dominant_pollutant <- ifelse(ok, sub("_sub_index$", "", dominant), NA_character_)
  daily$category <- ifelse(is.na(daily$aqi), NA_character_, get_aqi_categories(daily$aqi))

  daily <- daily[order(daily$station_id, daily$date), c(columns, colnames(subs))]
  rownames(daily) <- NULL
  daily
}

# Mean of the hourly values in the window (t - 8 h, t], NA with < 6 values
.aqi_rolling_8h <- function(hour, value) {
  t <- as.numeric(hour)
  start <- findInterval(t - 8 * 3600, t) + 1
  cs <- c(0, cumsum(value))
  n <- seq_along(t) - start + 1
  out <- (cs[seq_along(t) + 1] - cs[start]) / n
  out[n < 6] <- NA_real_
  out
}

.aqi_hourly_means <- function(long) {
  names_naqi <- aqi_pollutant_name(long$pollutant)
  data <- data.frame(
    station_id = if ("station_id" %in% names(long)) as.character(long$station_id) else "",
    pollutant = names_naqi,
    value = suppressWarnings(as.numeric(long$value)),
    timestamp = long$timestamp,
    stringsAsFactors = FALSE
  )
  if ("unit" %in% names(long)) {
    data$value <- data$value * .aqi_unit_factor(long$unit, names_naqi)
  }
  data <- data[!is.na(data$pollutant) & !is.na(data$value), , drop = FALSE]
  if (nrow(data) == 0) {
    return(data.frame(
      station_id = character(0), pollutant = character(0),
      hour = as.POSIXct(character(0), tz = "UTC"), value = numeric(0)
    ))
  }
  hour <- as.POSIXct(trunc(.parse_timestamp(data$timestamp), "hours"))
  out <- stats::aggregate(
    data$value,
    by = list(station_id = data$station_id, pollutant = data$pollutant, hour = hour),
    FUN = mean
  )
  names(out)[4] <- "value"
  out
}

# factor from each row's unit to the NAQI unit of its pollutant (ug <-> mg)
.aqi_unit_factor <- function(unit, pollutant) {
  mass <- .aqi_mass_unit(unit)
  target <- vapply(pollutant, function(p) {
    if (is.na(p)) NA_character_ else .aqi_pollutants[[p]]$unit
  }, character(1))
  factor <- rep(1, length(unit))
  factor[mass == "ug" & target == "mg"] <- 1e-3
  factor[mass == "mg" & target == "ug"] <- 1e3
  factor[is.na(factor)] <- 1
  factor
}
