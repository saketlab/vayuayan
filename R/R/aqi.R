# CPCB's About NAQI page; the 2014 report differs in places (Pb 0.6-1.0)
# Severe has no upper limit; extended by the Very Poor width, at that slope
.aqi_pollutants <- list(
  PM10 = list(unit = "ug", hours = 24, bp = c(0, 50, 51, 100, 101, 250, 251, 350, 351, 430, 430, 510)),
  PM2.5 = list(unit = "ug", hours = 24, bp = c(0, 30, 31, 60, 61, 90, 91, 120, 121, 250, 250, 380)),
  NO2 = list(unit = "ug", hours = 24, bp = c(0, 40, 41, 80, 81, 180, 181, 280, 281, 400, 400, 520)),
  O3 = list(unit = "ug", hours = 8, bp = c(0, 50, 51, 100, 101, 168, 169, 208, 209, 748, 748, 1288)),
  CO = list(unit = "mg", hours = 8, bp = c(0, 1.0, 1.1, 2.0, 2.1, 10, 10, 17, 17, 34, 34, 51)),
  SO2 = list(unit = "ug", hours = 24, bp = c(0, 40, 41, 80, 81, 380, 381, 800, 801, 1600, 1600, 2400)),
  NH3 = list(unit = "ug", hours = 24, bp = c(0, 200, 201, 400, 401, 800, 801, 1200, 1200, 1800, 1800, 2400)),
  Pb = list(unit = "ug", hours = 24, bp = c(0, 0.5, 0.5, 1.0, 1.1, 2.0, 2.1, 3.0, 3.1, 3.5, 3.5, 3.9))
)

.aqi_bands <- c(0, 50, 51, 100, 101, 200, 201, 300, 301, 400, 401, 500)

.aqi_min_hours <- 16
.aqi_min_pollutants <- 3

# (concentration, sub-index) interpolation points; a shared band boundary
# (Pb 0.5, CO 10) belongs to the lower band
.aqi_points <- function(bp) {
  xs <- bp
  for (i in seq(3, length(xs), by = 2)) {
    if (xs[i] <= xs[i - 1]) xs[i] <- xs[i - 1] + 1e-9
  }
  list(x = xs, y = .aqi_bands)
}

.aqi_interp <- function(pollutant, concentration) {
  pts <- .aqi_points(.aqi_pollutants[[pollutant]]$bp)
  out <- rep(NA_real_, length(concentration))
  ok <- !is.na(concentration)
  out[ok] <- stats::approx(pts$x, pts$y, xout = concentration[ok], rule = 2)$y
  # no cap at 500, as in CPCB's AQI-Calculator.xls
  n <- length(pts$x)
  above <- ok & concentration > pts$x[n]
  slope <- (pts$y[n] - pts$y[n - 1]) / (pts$x[n] - pts$x[n - 1])
  out[above] <- pts$y[n] + (concentration[above] - pts$x[n]) * slope
  out
}

# round() rounds half to even; CPCB's calculator shows half up
.round_half_up <- function(x) floor(x + 0.5)

.aqi_split_label <- function(label, part = 1) {
  m <- regmatches(label, regexec("^\\s*(.*?)\\s*(?:\\((.*?)\\))?\\s*$", label, perl = TRUE))
  vapply(m, function(x) if (length(x)) x[part + 1] else NA_character_, character(1))
}

# Unit of a label such as "PM2.5 (ug/m3)", "" when it has none
.aqi_label_unit <- function(label) .aqi_split_label(label, part = 2)

# A label without its unit, case or punctuation: "PM2.5 (ug/m3)" -> "pm25"
.aqi_key <- function(label) {
  key <- tolower(.aqi_split_label(as.character(label)))
  gsub("[^a-z0-9]", "", sub("2.5", "25", key, fixed = TRUE))
}

# "ug" or "mg" for a concentration unit such as "ug/m3" or "\u00b5g/m3", else ""
.aqi_mass_unit <- function(unit) {
  mass <- substr(gsub("\u03bc|\u00b5", "u", tolower(trimws(as.character(unit)))), 1, 2)
  ifelse(mass %in% c("ug", "mg"), mass, "")
}

#' NAQI name of a pollutant label
#'
#' @description
#' Match a pollutant label such as \code{"PM2.5 (ug/m3)"}, \code{"pm25"} or
#' \code{"Ozone"} to its National AQI name.
#'
#' @param label Character vector of labels.
#' @return Character vector of NAQI names (\code{"PM10"}, \code{"PM2.5"},
#'   \code{"NO2"}, \code{"O3"}, \code{"CO"}, \code{"SO2"}, \code{"NH3"},
#'   \code{"Pb"}), \code{NA} for labels that are not NAQI pollutants.
#' @examples
#' aqi_pollutant_name(c("PM2.5 (ug/m3)", "Ozone", "Benzene"))
#' @export
aqi_pollutant_name <- function(label) {
  names_by_key <- c(stats::setNames(names(.aqi_pollutants), .aqi_key(names(.aqi_pollutants))), ozone = "O3", lead = "Pb")
  unname(names_by_key[.aqi_key(label)])
}

#' National AQI sub-index of concentrations
#'
#' @description
#' The CPCB National AQI sub-index of one pollutant, by linear interpolation
#' within its breakpoint band.
#'
#' @param pollutant A pollutant label (see \code{aqi_pollutant_name()}).
#' @param concentration Numeric vector of 24-hour averages (8-hour for CO and
#'   O3), in mg/m3 for CO and ug/m3 for the others.
#' @return Numeric vector of sub-indices; above the last breakpoint the
#'   slope of the Severe band continues, so a sub-index can be more than 500.
#'   \code{NA} stays \code{NA}.
#' @examples
#' aqi_sub_index("PM2.5", c(25, 45, 300))
#' @export
aqi_sub_index <- function(pollutant, concentration) {
  name <- aqi_pollutant_name(pollutant)
  if (length(name) != 1 || is.na(name)) {
    stop(sprintf(
      "'%s' is not a NAQI pollutant: %s", pollutant,
      paste(names(.aqi_pollutants), collapse = ", ")
    ), call. = FALSE)
  }
  .aqi_interp(name, as.numeric(concentration))
}

#' Overall National AQI of a set of concentrations
#'
#' @description
#' The overall AQI is the highest sub-index. CPCB requires at least three
#' pollutants, one of them PM2.5 or PM10.
#'
#' @param concentrations Named numeric vector or list: pollutant label to
#'   averaged concentration. Labels that are not NAQI pollutants and missing
#'   values are ignored.
#' @return List with \code{aqi} (integer, \code{NA} when the data are
#'   insufficient), \code{category}, \code{dominant_pollutant} and the named
#'   \code{sub_indices}.
#' @examples
#' compute_aqi(c("PM2.5" = 45, PM10 = 80, NO2 = 30))$aqi
#' @export
compute_aqi <- function(concentrations) {
  values <- unlist(concentrations)
  names_naqi <- aqi_pollutant_name(names(values))
  keep <- !is.na(names_naqi) & !is.na(values)
  subs <- stats::setNames(
    mapply(.aqi_interp, names_naqi[keep], as.numeric(values[keep])),
    names_naqi[keep]
  )
  # a repeated label counts once; ties go to the first in .aqi_pollutants
  order <- intersect(names(.aqi_pollutants), names(subs))
  subs <- vapply(order, function(n) max(subs[names(subs) == n]), numeric(1))
  if (!.aqi_sufficient(names(subs))) {
    return(list(
      aqi = NA_integer_, category = NA_character_,
      dominant_pollutant = NA_character_, sub_indices = subs
    ))
  }
  dominant <- names(subs)[which.max(subs)]
  aqi <- as.integer(.round_half_up(max(subs)))
  list(
    aqi = aqi, category = get_aqi_category(aqi),
    dominant_pollutant = dominant, sub_indices = subs
  )
}

.aqi_sufficient <- function(pollutants) {
  length(pollutants) >= .aqi_min_pollutants &&
    any(c("PM2.5", "PM10") %in% pollutants)
}

# health texts of CPCB's AQI-Calculator.xls
.aqi_health_impacts <- c(
  Good = "Minimal impact",
  Satisfactory = "Minor breathing discomfort to sensitive people",
  Moderate = paste(
    "Breathing discomfort to the people with lung, heart disease,",
    "children and older adults"
  ),
  Poor = "Breathing discomfort to people on prolonged exposure",
  "Very Poor" = "Respiratory illness to the people on prolonged exposure",
  Severe = "Respiratory effects even on healthy people"
)

#' Possible health impact of an AQI value
#'
#' @description
#' CPCB's "possible health impacts" text for the category of each AQI value.
#'
#' @param aqi_value Numeric vector of AQI values.
#' @return Character vector, \code{"No Data"} for missing values.
#' @examples
#' aqi_health_impact(c(250, NA))
#' @export
aqi_health_impact <- function(aqi_value) {
  out <- unname(.aqi_health_impacts[get_aqi_categories(aqi_value)])
  out[is.na(out)] <- "No Data"
  out
}

#' AQI category of a pollutant concentration
#'
#' @description
#' The category of the sub-index of each concentration, for example of a
#' PM2.5 mean from satellite data. The breakpoints are for 24-hour averages
#' (8-hour for CO and O3), so for an annual or monthly mean the category is an
#' indication only.
#'
#' @inheritParams aqi_sub_index
#' @return Character vector of AQI categories.
#' @examples
#' aqi_pollutant_category("PM2.5", c(20, 75))
#' @export
aqi_pollutant_category <- function(pollutant, concentration) {
  get_aqi_categories(.round_half_up(aqi_sub_index(pollutant, concentration)))
}
