# Pollutants of the daily AQI, in the order of the EPA tables
.us_daily_pollutants <- c("PM2.5", "PM10", "O3", "CO", "SO2", "NO2")

# 40 CFR 50 App U 3(b) and 50.8(c): an 8-hour mean needs 6 of its 8 hours
.us_daily_window_min_hours <- 6

# Averaged labels such as O3_1h are not readings
.us_daily_name <- function(label) {
  name <- us_aqi_pollutant_name(label)
  name[!name %in% .us_daily_pollutants] <- NA_character_
  name
}

# Factor from each row's unit to the unit of the US table of its pollutant
.us_daily_factor <- function(unit, pollutant) {
  key <- paste(pollutant, unit, sep = "\r")
  first <- !duplicated(key)
  factors <- mapply(function(p, u) {
    if (is.na(p)) NA_real_ else .us_aqi_to_epa_unit(.us_aqi_pollutants[[p]], u, 1)
  }, pollutant[first], unit[first], USE.NAMES = FALSE)
  factors[match(key, key[first])]
}

# Running means on a full hourly grid, so a missing hour still ends a window
.us_daily_windows <- function(group) {
  stations <- lapply(split(group, group$station_id), function(rows) {
    grid <- seq(min(rows$hour), max(rows$hour), by = 3600)
    data.frame(
      station_id = rows$station_id[1], hour = grid,
      value = .aqi_rolling_8h(rows$hour, rows$value, .us_daily_window_min_hours, at = grid)
    )
  })
  do.call(rbind, stations)
}

# Sub-index of one column; SO2 counts its 24-hour bands too
.us_daily_sub_index <- function(sub_indices, name) {
  keys <- if (name == "SO2") c("SO2", "SO2_24h") else name
  values <- sub_indices[intersect(keys, names(sub_indices))]
  if (length(values)) max(values) else NA_real_
}

#' Daily US EPA AQI from tidy data
#'
#' @description
#' Daily US EPA AQI of each station from long data, such as 15-minute raw
#' data from \code{cpcb_raw_to_long()}. Readings are averaged by hour as in
#' \code{daily_aqi()}: negative and non-finite readings are dropped, readings
#' repeated at one time are averaged once, and each calendar day is taken in
#' the time zone of the timestamps.
#'
#' For each station and day:
#' \itemize{
#'   \item PM2.5 and PM10 use the 24-hour mean (EPA TAD p.2).
#'   \item O3 and CO use the highest 8-hour running mean (EPA TAD p.2, p.24).
#'     A window is placed at its last hour, needs 6 of its 8 hours (40 CFR 50
#'     App U 3(b), section 50.8(c)), and a day needs \code{min_hours} of its 24
#'     windows.
#'   \item SO2 and NO2 use the highest 1-hour value (EPA TAD p.2), and the
#'     24-hour SO2 mean decides the bands above 304 ppb as in
#'     \code{compute_us_aqi()}.
#'   \item PM, the 1-hour pollutants and the 24-hour SO2 mean need
#'     \code{min_hours} hours.
#' }
#'
#' Assumptions: the EPA sets no completeness rule for a daily AQI, so 18 of 24
#' (75 percent) applies the NAAQS data handling of 40 CFR 50 App K, N, S, T
#' and U. Values in ug/m3 or mg/m3 are converted to ppb or ppm at 25 degrees C
#' and 760 mm Hg (40 CFR 50.3), which is an assumption for CPCB data: CPCB
#' states no reference conditions. The window \code{day_ends_at} is a vayuayan
#' option, not an EPA rule. There is no minimum number of pollutants (EPA TAD
#' p.22): the AQI is the highest sub-index of the pollutants available.
#'
#' @param long Data frame with columns \code{timestamp}, \code{pollutant},
#'   \code{value}, and optionally \code{station_id} and \code{unit}, as for
#'   \code{daily_aqi()}. A row with neither a unit nor a unit in its label is
#'   taken to be in the unit of the US table.
#' @param day_ends_at Hour (1--24) at which each day's 24 hours end. 24 means
#'   calendar days. A row is dated by the day its window ends.
#' @param min_hours Minimum hours, or 8-hour windows, a pollutant needs in a
#'   day.
#' @return One row per station and date: \code{station_id}, \code{date},
#'   \code{aqi}, \code{category} (US names), \code{dominant_pollutant},
#'   \code{n_pollutants}, \code{aqi_status} and one
#'   \code{<pollutant>_sub_index} column per pollutant with data. \code{aqi},
#'   \code{category} and \code{dominant_pollutant} are \code{NA} if no
#'   pollutant has a sub-index, and, with one warning, on days when 8-hour O3
#'   is above 0.200 ppm, which the 8-hour table does not cover (40 CFR 58 App G
#'   note 2). \code{aqi_status} says why: \code{"too_few_hours"} when a
#'   pollutant with readings fell short of \code{min_hours}, else
#'   \code{"o3_beyond_table"} or \code{"no_sub_index"}; \code{"ok"} when there
#'   is an AQI.
#' @inherit compute_us_aqi references
#' @examples
#' hours <- seq(as.POSIXct("2024-01-01", tz = "UTC"), by = "hour", length.out = 24)
#' long <- data.frame(
#'   timestamp = rep(hours, 2),
#'   pollutant = rep(c("PM2.5 (ug/m3)", "O3 (ppm)"), each = 24),
#'   value = rep(c(30, 0.05), each = 24)
#' )
#' daily_us_aqi(long)
#' @export
daily_us_aqi <- function(long, day_ends_at = 24, min_hours = 18) {
  .aqi_check_day_ends_at(day_ends_at)
  hourly <- .aqi_hourly_means(long, .us_daily_name, .us_daily_factor)
  if (nrow(hourly) == 0) {
    return(.aqi_empty_daily())
  }
  shift <- (24 - day_ends_at) * 3600
  present <- intersect(.us_daily_pollutants, unique(hourly$pollutant))
  values <- list()
  for (name in present) {
    group <- hourly[hourly$pollutant == name, , drop = FALSE]
    group <- group[order(group$station_id, group$hour), , drop = FALSE]
    hours <- .us_aqi_pollutants[[name]]$hours
    if (hours == 8) group <- .us_daily_windows(group)
    values[[name]] <- .aqi_by_day(group, if (hours == 24) "mean" else "max", min_hours, shift, count = "values")
    if (name == "SO2") values[["SO2_24h"]] <- .aqi_by_day(group, "mean", min_hours, shift, count = "values")
  }
  # only days with a reading; the 8-hour grid also holds the hours of a gap
  days <- data.frame(station_id = hourly$station_id, date = .local_date(hourly$hour + shift))
  days <- days[!duplicated(days), , drop = FALSE]
  wide <- days
  for (name in names(values)) {
    column <- values[[name]]
    names(column)[3] <- name
    wide <- merge(wide, column, by = c("station_id", "date"), all.x = TRUE)
  }

  # the rules are per row in .us_aqi_compute, so evaluate each distinct row once; match() is exact on doubles
  codes <- lapply(wide[names(values)], function(v) match(v, unique(v)))
  row_key <- do.call(paste, c(unname(codes), sep = "\r"))
  once <- which(!duplicated(row_key))
  results <- lapply(once, function(i) .us_aqi_compute(unlist(wide[i, names(values), drop = FALSE])))
  results <- results[match(row_key, row_key[once])]
  o3_days <- sum(vapply(results, `[[`, FALSE, "o3_above_table"))
  if (o3_days > 0) {
    warning(sprintf(
      "8-hour O3 above 0.200 ppm on %d day(s) has no US AQI without a 1-hour O3 value", o3_days
    ), call. = FALSE)
  }

  sub_columns <- paste0(present, "_sub_index")
  subs <- vapply(present, function(name) {
    vapply(results, function(r) .us_daily_sub_index(r$sub_indices, name), numeric(1))
  }, numeric(nrow(wide)))
  subs <- matrix(subs, nrow = nrow(wide), dimnames = list(NULL, sub_columns))
  daily <- wide[c("station_id", "date")]
  daily$aqi <- vapply(results, `[[`, NA_integer_, "aqi")
  daily$category <- vapply(results, `[[`, NA_character_, "category")
  daily$dominant_pollutant <- sub("_24h$", "", vapply(results, `[[`, NA_character_, "dominant_pollutant"))
  daily$n_pollutants <- rowSums(!is.na(subs))
  daily$aqi_status <- vapply(results, `[[`, "", "status")
  short_days <- unlist(lapply(values, .aqi_short_days))
  # more hours would not fix O3 beyond the table
  fixable <- !daily$aqi_status %in% c("ok", "o3_beyond_table")
  daily$aqi_status[fixable & .aqi_day_key(daily) %in% short_days] <- "too_few_hours"
  daily <- cbind(daily, subs, stringsAsFactors = FALSE)
  daily <- daily[order(daily$station_id, daily$date), c(.aqi_daily_columns, sub_columns)]
  rownames(daily) <- NULL
  daily
}
