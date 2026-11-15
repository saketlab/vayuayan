# Hourly data of the Delhi Pollution Control Committee's stations from DPCC's own website (as Python's vayuayan.dpcc)

.dpcc_url <- "https://www.dpccairdata.com/dpccairdata/display/%s.php?stName=%s"
.dpcc_first_day <- as.Date("2025-01-01") # the site refuses earlier start dates
.dpcc_max_days <- 6 # the site refuses a 7-day window
.dpcc_state <- new.env() # last: elapsed time of the last request to the site
.dpcc_state$last <- -Inf
.dpcc_ua <- "Mozilla/5.0 (compatible; vayuayan; +https://vayuayan.saketlab.org)"
.dpcc_stations <- c(
  AnandVihar = "Anand Vihar", Alipur = "Alipur", AshokVihar = "Ashok Vihar",
  CwgSports = "CWG Sports Complex, Akshardham", DwarkaSectro8 = "Dwarka, Sector 8",
  Ignou = "IGNOU", JLNStadium = "Jawaharlal Nehru Stadium", Jahangirpuri = "Jahangirpuri", Jnu = "JNU",
  KarniSinghShootingRange = "Dr. Karni Singh Shooting Range", Mandirmarg = "Mandir Marg", Mundka = "Mundka",
  Najafgarh = "Najafgarh", Narela = "Narela", NationalStadium = "Major Dhyan Chand National Stadium",
  NehruNagar = "Nehru Nagar", Nsut = "NSUT (West Campus)", OkhlaPhase2 = "Okhla Phase-2",
  Patparganj = "Patparganj", PoothKhurdBawana = "Pooth Khurd, Bawana", PunjabiBagh = "Punjabi Bagh",
  Pusa = "Pusa", RKPuram = "R.K. Puram", RohiniSector16 = "Rohini", SbvDelhi = "SBV Delhi Cantt",
  SoniaVihar = "Sonia Vihar", SpmSpc = "SPM-SPC Talkatora Garden", SriAurbindoMarg = "Sri Aurobindo Marg",
  Supersite = "Supersite (Rouse Avenue)", VivekVihar = "Vivek Vihar", Wazirpur = "Wazirpur"
)
# site parameter code -> page, pollutant name as in CPCB data, unit
.dpcc_parameters <- local({
  met <- "AallAdvanceSearchMet"
  gas <- "AallAdvanceSearchCconc"
  p <- rbind(
    c("PM25", met, "PM2.5", "\u00b5g/m\u00b3"), c("PM10", met, "PM10", "\u00b5g/m\u00b3"),
    c("AT1", met, "AT", "\u00b0C"), c("BP", met, "BP", "mmHg"), c("RH", met, "RH", "%"),
    c("SR", met, "SR", "W/mt2"), c("WS", met, "WS", "m/s"), c("WD", met, "WD", "deg"),
    c("NH3", gas, "NH3", "\u00b5g/m\u00b3"), c("BEN", gas, "Benzene", "\u00b5g/m\u00b3"),
    c("CO", gas, "CO", "mg/m\u00b3"), c("NO2", gas, "NO2", "\u00b5g/m\u00b3"), c("NO1", gas, "NO", "\u00b5g/m\u00b3"),
    c("NOX", gas, "NOx", "ppb"), c("O3", gas, "Ozone", "\u00b5g/m\u00b3"), c("pXy", gas, "p-Xylene", "\u00b5g/m\u00b3"),
    c("SO2", gas, "SO2", "\u00b5g/m\u00b3"), c("Tol", gas, "Toluene", "\u00b5g/m\u00b3")
  )
  data.frame(code = p[, 1], page = p[, 2], pollutant = p[, 3], unit = p[, 4], stringsAsFactors = FALSE)
})

#' DPCC stations
#'
#' The Delhi Pollution Control Committee's stations on its website, with the code
#' \code{\link{dpcc_hourly}} accepts (station names work too).
#'
#' @return A data frame with \code{station_id} (the site's code) and \code{station_name}.
#' @examples
#' head(dpcc_stations())
#' @export
dpcc_stations <- function() {
  data.frame(station_id = names(.dpcc_stations), station_name = unname(.dpcc_stations), stringsAsFactors = FALSE)
}

#' Hourly data of DPCC stations from DPCC's website
#'
#' CPCB's copies of DPCC's stations drop every 15-minute value above 1,000
#' \eqn{\mu}g/m\eqn{^3}; DPCC's site keeps them. The site serves hourly averages from
#' 2025-01-01, at most 6 days per request, and its pages prohibit scraping. Requests go
#' one at a time, at least \code{getOption("vayuayan.dpcc_pause", 3)} seconds apart, and
#' finished windows are cached.
#'
#' @param stations Station codes or names (see \code{\link{dpcc_stations}}).
#' @param start First day, 2025-01-01 or later, a \code{Date} or \code{"YYYY-MM-DD"}.
#' @param end Last day (inclusive).
#' @param parameters Pollutant names as in CPCB data (\code{"PM2.5"}, \code{"NO2"}, \code{"Ozone"})
#'   or DPCC's codes (\code{"PM25"}, \code{"O3"}).
#' @return A data frame with the tidy columns (\code{station_id}, \code{station_name}, \code{city},
#'   \code{state}, \code{timestamp}, \code{pollutant}, \code{unit}, \code{value}), one row per hour with a
#'   value; \code{timestamp} is the start of the hour in local time, stored as UTC like
#'   CPCB data.
#' @examplesIf interactive()
#' dpcc_hourly(c("Mundka", "JNU"), "2026-11-08", "2026-11-09")
#' @export
dpcc_hourly <- function(stations, start, end = start, parameters = "PM2.5") {
  codes <- vapply(stations, .dpcc_station_code, character(1), USE.NAMES = FALSE)
  pars <- vapply(parameters, .dpcc_parameter_code, character(1), USE.NAMES = FALSE)
  first <- as.Date(start)
  last <- as.Date(end)
  if (first < .dpcc_first_day) stop("DPCC's site has data from ", format(.dpcc_first_day), " only", call. = FALSE)
  if (last < first) stop("end is before start", call. = FALSE)
  rows <- list()
  for (code in codes) {
    for (par in pars) {
      info <- .dpcc_parameters[.dpcc_parameters$code == par, ]
      for (w in .dpcc_windows(first, last)) {
        got <- parse_dpcc_page(.dpcc_fetch(code, par, info$page, w[[1]], w[[2]]))
        if (nrow(got)) {
          rows[[length(rows) + 1]] <- data.frame(
            station_id = code, station_name = unname(.dpcc_stations[code]), hour = got$hour,
            pollutant = info$pollutant, unit = info$unit, value = got$value, stringsAsFactors = FALSE
          )
        }
      }
    }
  }
  if (!length(rows)) {
    return(data.frame(
      station_id = character(0), station_name = character(0), city = character(0),
      state = character(0), timestamp = as.POSIXct(character(0), tz = "UTC"),
      pollutant = character(0), unit = character(0), value = numeric(0)
    ))
  }
  cols <- c("station_id", "station_name", "city", "state", "timestamp", "pollutant", "unit", "value")
  out <- do.call(rbind, rows)
  out$timestamp <- .parse_timestamp(out$hour)
  day0 <- as.POSIXct(paste(first, "00:00:00"), tz = "UTC")
  day1 <- as.POSIXct(paste(last + 1, "00:00:00"), tz = "UTC")
  out <- out[out$timestamp >= day0 & out$timestamp < day1, ]
  out <- out[!duplicated(out[c("station_id", "pollutant", "timestamp")]), ]
  out$city <- "Delhi"
  out$state <- "Delhi"
  out <- out[order(out$station_id, out$pollutant, out$timestamp, method = "radix"), cols]
  rownames(out) <- NULL
  out
}

#' Read a DPCC search result page
#'
#' The hourly values in a DPCC "Advance Search" result page, read from its chart.
#'
#' @param page The page's HTML, one string.
#' @return A data frame with \code{hour} (as the site writes it) and \code{value}; hours
#'   without a value are left out.
#' @examples
#' page <- "Search Result <script>categories: ['2026-11-09 02:00:00'], data: [3744.0]</script>"
#' parse_dpcc_page(page)
#' @export
parse_dpcc_page <- function(page) {
  if (!grepl("Search Result", page, fixed = TRUE)) {
    stop("not a DPCC search result page; the site may have changed", call. = FALSE)
  }
  empty <- data.frame(hour = character(0), value = numeric(0), stringsAsFactors = FALSE)
  cats <- regmatches(page, regexpr("categories:\\s*\\[[^]]*\\]", page))
  data <- regmatches(page, gregexpr("data:\\s*\\[[^]]*\\]", page))[[1]]
  if (!length(cats) || !length(data)) {
    return(empty)
  }
  hours <- regmatches(cats, gregexpr("'[^']+'", cats))[[1]]
  hours <- gsub("'", "", hours, fixed = TRUE)
  inner <- sub("^data:\\s*\\[", "", sub("\\]$", "", data[length(data)])) # the last array is the series
  values <- trimws(strsplit(inner, ",", fixed = TRUE)[[1]])
  if (!length(values) && !length(hours)) {
    return(empty)
  }
  if (length(values) != length(hours)) stop("DPCC chart has different numbers of hours and values", call. = FALSE)
  num <- suppressWarnings(as.numeric(values))
  keep <- !is.na(num)
  data.frame(hour = hours[keep], value = num[keep], stringsAsFactors = FALSE)
}

# Request windows; the site returns the hours after the start time up to the end time
.dpcc_windows <- function(first, last) {
  w0 <- as.POSIXct(paste(first, "00:00:00"), tz = "UTC") - 3600
  stop_at <- as.POSIXct(paste(last, "23:00:00"), tz = "UTC")
  out <- list()
  while (w0 < stop_at) {
    w1 <- min(w0 + .dpcc_max_days * 86400, stop_at)
    out[[length(out) + 1]] <- list(w0, w1)
    w0 <- w1
  }
  out
}

# One result page; windows that ended more than two days ago are cached (shared with Python)
.dpcc_fetch <- function(code, par, page, w0, w1) {
  name <- sprintf("%s_%s_%s_%s.html", code, par, format(w0, "%Y%m%d%H", tz = "UTC"), format(w1, "%Y%m%d%H", tz = "UTC"))
  cached <- .cache_lookup(.cache_dirs("dpcc"), name)
  if (!is.null(cached)) {
    return(paste(readLines(cached, warn = FALSE, encoding = "UTF-8"), collapse = "\n"))
  }
  url <- sprintf(.dpcc_url, page, utils::URLencode(jsonlite::base64_enc(code), reserved = TRUE))
  form <- list(
    parameters = par, fDate = format(w0, "%Y-%m-%d %H:%M", tz = "UTC"),
    eDate = format(w1, "%Y-%m-%d %H:%M", tz = "UTC"), duration = "1", graphType = "Line",
    submit = "Search"
  )
  Sys.sleep(max(0, .dpcc_state$last + getOption("vayuayan.dpcc_pause", 3) - proc.time()[["elapsed"]]))
  on.exit(.dpcc_state$last <- proc.time()[["elapsed"]])
  resp <- httr::RETRY("POST", url,
    body = form, encode = "form", httr::user_agent(.dpcc_ua), httr::timeout(90),
    times = 3, quiet = TRUE, terminate_on = 400:499
  )
  httr::stop_for_status(resp, task = "download DPCC data")
  text <- httr::content(resp, as = "text", encoding = "UTF-8")
  local_now <- as.POSIXct(format(Sys.time(), tz = "Asia/Kolkata"), tz = "UTC")
  if (w1 < local_now - 2 * 86400 && grepl("Search Result", text, fixed = TRUE)) {
    .cache_write(file.path(vayuayan_cache_dir(), "dpcc", name), function(p) writeLines(text, p, useBytes = TRUE))
  }
  text
}

.dpcc_squash <- function(x) gsub("[^a-z0-9]", "", tolower(x))

.dpcc_station_code <- function(station) {
  key <- .dpcc_squash(station)
  hit <- names(.dpcc_stations)[.dpcc_squash(names(.dpcc_stations)) == key | .dpcc_squash(.dpcc_stations) == key]
  if (!length(hit)) stop("unknown DPCC station '", station, "'; see dpcc_stations()", call. = FALSE)
  hit[1]
}

.dpcc_parameter_code <- function(parameter) {
  key <- .dpcc_squash(parameter)
  p <- .dpcc_parameters
  hit <- p$code[.dpcc_squash(p$code) == key | .dpcc_squash(p$pollutant) == key]
  if (!length(hit)) {
    stop("unknown DPCC parameter '", parameter, "'; one of ", paste(sort(p$code), collapse = ", "), call. = FALSE)
  }
  hit[1]
}
