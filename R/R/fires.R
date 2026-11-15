#' Fire detections from NASA FIRMS
#'
#' @description
#' Active fire detections from the MODIS and VIIRS satellites, served by NASA
#' FIRMS, for setting beside PM2.5. For each day asked, the function reads:
#'
#' * a past year: FIRMS's yearly country archives for India and the
#'   neighbouring countries whose box meets \code{bbox} (Pakistan, Nepal,
#'   Bangladesh, Bhutan, Sri Lanka, Myanmar, Afghanistan, China; no key;
#'   cached under \code{vayuayan_cache_dir()/fires}, and also read from the Python
#'   package's cache),
#' * the last 7 days: FIRMS's South Asia near-real-time files (no key),
#' * other days of the current year: the FIRMS area API, which needs a free
#'   MAP_KEY from <https://firms.modaps.eosdis.nasa.gov/api/map_key/>.
#'
#' @param start First day (UTC), a \code{Date} or \code{"YYYY-MM-DD"}.
#' @param end Last day (UTC), inclusive.
#' @param bbox \code{c(west, south, east, north)} in degrees; \code{NULL} for a box
#'   around India (with parts of its neighbours).
#' @param source \code{"modis"} (2000 on), \code{"viirs-snpp"} (2012 on, 375 m),
#'   \code{"viirs-noaa20"} (2018 on) or \code{"viirs-noaa21"} (2023 on; FIRMS has no
#'   yearly archive for it, so past years need \code{map_key}).
#' @param map_key FIRMS MAP_KEY. Needed only for days of the current year
#'   older than 7 days.
#' @return A data frame with \code{latitude}, \code{longitude}, \code{date} (UTC day),
#'   \code{datetime} (UTC overpass time), \code{satellite}, \code{confidence} (0-100 for
#'   MODIS, \code{low}/\code{nominal}/\code{high} for VIIRS), \code{frp} (fire radiative power,
#'   MW) and \code{daynight}, sorted by \code{datetime}. FIRMS answering with a
#'   message (such as an invalid MAP_KEY) instead of fire data is an error.
#' @examplesIf interactive()
#' punjab <- firms_fires("2023-11-01", "2023-11-10", bbox = c(73, 29, 78, 32.5), source = "modis")
#' @export
firms_fires <- function(start, end = start, bbox = NULL, source = "viirs-snpp",
                        map_key = Sys.getenv("FIRMS_MAP_KEY")) {
  if (!source %in% names(.firms_sources)) {
    stop("source must be one of ", paste(sort(names(.firms_sources)), collapse = ", "), call. = FALSE)
  }
  first <- as.Date(start)
  last <- as.Date(end)
  if (last < first) stop("end is before start", call. = FALSE)
  box <- if (is.null(bbox)) .india_bbox else as.numeric(bbox)

  today <- as.Date(format(Sys.time(), tz = "UTC", "%Y-%m-%d"))
  nrt_from <- today - (.firms_nrt_days - 1)
  this_year <- as.integer(format(today, "%Y"))
  frames <- list()
  api_days <- as.Date(character(0))
  for (year in seq(as.integer(format(first, "%Y")), as.integer(format(last, "%Y")))) {
    if (year < this_year) {
      texts <- list()
      for (country in .firms_countries(box)) {
        text <- .firms_archive_csv(source, year, country)
        if (is.null(text)) { # a year without an archive goes to the API
          texts <- list()
          break
        }
        texts[[length(texts) + 1]] <- text
      }
      if (length(texts)) {
        frames <- c(frames, lapply(texts, .firms_parse))
        next
      }
    }
    days <- seq(max(first, as.Date(sprintf("%d-01-01", year))), min(last, as.Date(sprintf("%d-12-31", year))), by = "day")
    if (any(days >= nrt_from)) {
      frames[[length(frames) + 1]] <- .firms_parse(.firms_get_text(paste0(.firms_url, "/data/active_fire/", .firms_sources[[source]][[2]])))
    }
    api_days <- c(api_days, days[days < nrt_from])
  }
  if (length(api_days)) frames <- c(frames, .firms_api_frames(source, api_days, box, map_key))

  frames <- Filter(nrow, frames) # an empty frame would turn confidence to character
  fires <- if (length(frames)) do.call(rbind, frames) else .firms_parse("")
  keep <- fires$date >= first & fires$date <= last &
    fires$longitude >= box[1] & fires$longitude <= box[3] &
    fires$latitude >= box[2] & fires$latitude <= box[4]
  fires <- unique(fires[keep, , drop = FALSE])
  fires <- fires[order(fires$datetime, method = "radix"), , drop = FALSE]
  rownames(fires) <- NULL
  fires
}

#' Daily fire counts near a point
#'
#' @description
#' Counts the fires of \code{\link{firms_fires}} within \code{radius_km} of a point, such as
#' a CPCB station, and sums their fire radiative power, for each local day.
#'
#' @param fires Output of \code{\link{firms_fires}}.
#' @param lat,lon The point.
#' @param radius_km Great-circle distance from the point.
#' @param start,end Days to report; the first and last day in \code{fires} if
#'   \code{NULL}. Days without fires have \code{n_fires} 0 and \code{frp_sum} 0.
#' @param tz Time zone of the days: IST by default, to match CPCB's daily
#'   PM2.5; \code{"UTC"} for FIRMS's own \code{acq_date}.
#' @return A data frame with \code{date} (day in \code{tz}), \code{n_fires} and \code{frp_sum} (MW).
#' @examples
#' fires <- data.frame(
#'   latitude = c(28.7, 30.2), longitude = c(77.1, 76.5),
#'   datetime = as.POSIXct(c("2023-11-01 05:00", "2023-11-03 20:10"), tz = "UTC"),
#'   frp = c(12, 30)
#' )
#' fire_daily_counts(fires, 28.6, 77.2, radius_km = 300)
#' @export
fire_daily_counts <- function(fires, lat, lon, radius_km = 100, start = NULL, end = NULL,
                              tz = "Asia/Kolkata") {
  if (nrow(fires) == 0 && (is.null(start) || is.null(end))) {
    return(data.frame(date = as.Date(character(0)), n_fires = integer(0), frp_sum = numeric(0)))
  }
  local <- as.Date(format(fires$datetime, "%Y-%m-%d", tz = tz))
  first <- if (is.null(start)) min(local) else as.Date(start)
  last <- if (is.null(end)) max(local) else as.Date(end)
  if (last < first) stop("end is before start", call. = FALSE)
  near <- which(haversine_distance(lat, lon, fires$latitude, fires$longitude) <= radius_km)
  dates <- seq(first, last, by = "day")
  key <- match(local[near], dates)
  n <- tabulate(key, nbins = length(dates))
  frp <- vapply(split(fires$frp[near], factor(key, levels = seq_along(dates))), sum, numeric(1))
  data.frame(date = dates, n_fires = n, frp_sum = unname(frp))
}

.firms_url <- "https://firms.modaps.eosdis.nasa.gov"
# source -> archive folder, 7-day file path, API source prefix (as Python's FIRMS_SOURCES)
.firms_sources <- list(
  "modis" = list("modis", "modis-c6.1/csv/MODIS_C6_1_South_Asia_7d.csv", "MODIS"),
  "viirs-snpp" = list("viirs-snpp", "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_Asia_7d.csv", "VIIRS_SNPP"),
  "viirs-noaa20" = list("viirs-jpss1", "noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_Asia_7d.csv", "VIIRS_NOAA20"),
  # no country archive (404), so past years go to the API; science data starts March 2023
  "viirs-noaa21" = list("viirs-jpss2", "noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_Asia_7d.csv", "VIIRS_NOAA21")
)
.india_bbox <- c(68, 6.5, 97.5, 37.5)
# FIRMS archive name -> rough c(west, south, east, north), as Python's ARCHIVE_COUNTRIES
.firms_archive_countries <- list(
  India = c(68.1, 6.7, 97.4, 35.7), Pakistan = c(60.8, 23.6, 77.9, 37.1),
  Nepal = c(80, 26.3, 88.2, 30.5), Bangladesh = c(88, 20.6, 92.7, 26.7),
  Bhutan = c(88.7, 26.7, 92.2, 28.3), Sri_Lanka = c(79.6, 5.9, 81.9, 9.9),
  Myanmar = c(92.2, 9.8, 101.2, 28.6), Afghanistan = c(60.5, 29.3, 75, 38.5),
  China = c(73.5, 18.1, 134.8, 53.6)
)
.firms_api_days <- 5
.firms_nrt_days <- 7
.viirs_confidence <- c(l = "low", n = "nominal", h = "high")

# FIRMS CSV (archive, 7-day file or API) -> the firms_fires columns
.firms_parse <- function(text) {
  head <- sub("\n.*", "", trimws(text, "left"))
  if (nzchar(head) && !grepl("latitude", head, fixed = TRUE)) {
    .vayuayan_abort("vayuayan_parse", sprintf("FIRMS answered '%s' instead of fire data", substr(head, 1, 200)))
  }
  if (!nzchar(head)) {
    return(data.frame(
      latitude = numeric(0), longitude = numeric(0), date = as.Date(character(0)),
      datetime = as.POSIXct(character(0), tz = "UTC"), satellite = character(0),
      confidence = character(0), frp = numeric(0), daynight = character(0)
    ))
  }
  raw <- utils::read.csv(
    text = text, colClasses = c(acq_time = "character", satellite = "character", daynight = "character"),
    stringsAsFactors = FALSE
  )
  when <- as.POSIXct(
    paste(raw$acq_date, formatC(as.integer(raw$acq_time), width = 4, flag = "0")),
    format = "%Y-%m-%d %H%M", tz = "UTC"
  )
  conf <- raw$confidence
  if (!is.numeric(conf)) conf <- unname(.viirs_confidence[tolower(substr(conf, 1, 1))])
  data.frame(
    latitude = as.numeric(raw$latitude), longitude = as.numeric(raw$longitude),
    date = as.Date(format(when, "%Y-%m-%d", tz = "UTC")), datetime = when,
    satellite = raw$satellite, confidence = conf, frp = as.numeric(raw$frp),
    daynight = raw$daynight, stringsAsFactors = FALSE
  )
}

# Response text; NULL on 404 when missing_ok
.firms_get_text <- function(url, missing_ok = FALSE) {
  # API URLs carry the MAP_KEY and are sent once, as in Python
  times <- if (grepl("/api/", url, fixed = TRUE)) 1 else 3
  resp <- httr::RETRY("GET", url, times = times, httr::timeout(300), quiet = TRUE, terminate_on = 400:499)
  if (missing_ok && httr::status_code(resp) == 404) {
    return(NULL)
  }
  if (httr::status_code(resp) %in% c(401, 403)) {
    .vayuayan_abort("vayuayan_auth", sprintf("FIRMS refused the MAP_KEY (HTTP %d)", httr::status_code(resp)))
  }
  httr::stop_for_status(resp, task = "download FIRMS data")
  httr::content(resp, as = "text", encoding = "UTF-8")
}

# .firms_archive_countries whose box meets bbox
.firms_countries <- function(bbox) {
  meets <- vapply(.firms_archive_countries, function(b) {
    b[1] <= bbox[3] && b[3] >= bbox[1] && b[2] <= bbox[4] && b[4] >= bbox[2]
  }, logical(1))
  names(.firms_archive_countries)[meets]
}

# Yearly country archive text, cached; NULL if FIRMS has no file yet
.firms_archive_csv <- function(source, year, country) {
  folder <- .firms_sources[[source]][[1]]
  name <- sprintf("%s_%d_%s.csv", folder, year, country)
  cached <- .cache_lookup(.cache_dirs("fires"), name)
  if (!is.null(cached)) {
    return(paste(readLines(cached, encoding = "UTF-8", warn = FALSE), collapse = "\n"))
  }
  cli::cli_alert_info("Downloading FIRMS {source} {year} {country} archive")
  text <- .firms_get_text(sprintf("%s/data/country/%s/%d/%s", .firms_url, folder, year, name), missing_ok = TRUE)
  if (is.null(text)) {
    return(NULL)
  }
  .cache_write(file.path(vayuayan_cache_dir(), "fires", name), function(p) writeLines(text, p, useBytes = TRUE))
  text
}

.firms_api_frames <- function(source, days, bbox, map_key) {
  if (is.null(map_key) || !nzchar(map_key)) {
    .vayuayan_abort("vayuayan_auth", sprintf(
      "FIRMS has %s to %s only through its API: set FIRMS_MAP_KEY (free at https://firms.modaps.eosdis.nasa.gov/api/map_key/)",
      min(days), max(days)
    ))
  }
  prefix <- .firms_sources[[source]][[3]]
  sp_until <- .firms_sp_max_date(map_key, paste0(prefix, "_SP"))
  is_sp <- if (is.na(sp_until)) rep(FALSE, length(days)) else days <= sp_until
  area <- paste(format(bbox, trim = TRUE, drop0trailing = TRUE), collapse = ",")
  frames <- list()
  groups <- list("_SP" = days[is_sp], "_NRT" = days[!is_sp])
  for (product in names(groups)) {
    for (run in .firms_day_runs(groups[[product]], .firms_api_days)) {
      url <- sprintf("%s/api/area/csv/%s/%s%s/%s/%d/%s", .firms_url, map_key, prefix, product, area, run$n, format(run$first))
      frames[[length(frames) + 1]] <- .firms_parse(.firms_get_text(url))
    }
  }
  frames
}

# Last day of the standard (science) product; NRT covers the days after
.firms_sp_max_date <- function(map_key, product) {
  text <- .firms_get_text(sprintf("%s/api/data_availability/csv/%s/%s", .firms_url, map_key, product))
  lines <- strsplit(trimws(text), "\n", fixed = TRUE)[[1]]
  if (length(lines) < 2 || !grepl("max_date", lines[1], fixed = TRUE)) {
    return(as.Date(NA))
  }
  header <- strsplit(lines[1], ",", fixed = TRUE)[[1]]
  as.Date(strsplit(lines[2], ",", fixed = TRUE)[[1]][match("max_date", header)])
}

# Consecutive days as list(first, n) runs of at most size days
.firms_day_runs <- function(days, size) {
  runs <- list()
  for (d in as.list(sort(days))) {
    k <- length(runs)
    if (k && runs[[k]]$n < size && runs[[k]]$first + runs[[k]]$n == d) {
      runs[[k]]$n <- runs[[k]]$n + 1L
    } else {
      runs[[k + 1]] <- list(first = d, n = 1L)
    }
  }
  runs
}
