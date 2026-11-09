# Band tops of CPCB's AQI-Calculator.xls and CUPS/82/2014-15 p.37; a band starts at the previous top
# Severe has no upper limit; extended by the Very Poor width, at that slope
.aqi_pollutants <- list(
  PM10 = list(unit = "ug", hours = 24, tops = c(50, 100, 250, 350, 430, 510)),
  PM2.5 = list(unit = "ug", hours = 24, tops = c(30, 60, 90, 120, 250, 380)),
  NO2 = list(unit = "ug", hours = 24, tops = c(40, 80, 180, 280, 400, 520)),
  O3 = list(unit = "ug", hours = 8, tops = c(50, 100, 168, 208, 748, 1288)),
  CO = list(unit = "mg", hours = 8, tops = c(1, 2, 10, 17, 34, 51)),
  SO2 = list(unit = "ug", hours = 24, tops = c(40, 80, 380, 800, 1600, 2400)),
  NH3 = list(unit = "ug", hours = 24, tops = c(200, 400, 800, 1200, 1800, 2400)),
  Pb = list(unit = "ug", hours = 24, tops = c(0.5, 1, 2, 3, 3.5, 4))
)

# Upper AQI limit of each category, also the sub-index at each band top
.aqi_categories <- c(Good = 50, Satisfactory = 100, Moderate = 200, Poor = 300, "Very Poor" = 400, Severe = 500)

.aqi_min_hours <- 16
.aqi_min_pollutants <- 3

.aqi_interp <- function(pollutant, concentration) {
  x <- c(0, .aqi_pollutants[[pollutant]]$tops)
  y <- c(0, unname(.aqi_categories))
  out <- rep(NA_real_, length(concentration))
  # a negative concentration is a sensor fault, not 0
  ok <- is.finite(concentration) & concentration >= 0
  out[ok] <- stats::approx(x, y, xout = concentration[ok], rule = 2)$y
  # no cap at 500, as in CPCB's AQI-Calculator.xls
  n <- length(x)
  above <- ok & concentration > x[n]
  slope <- (y[n] - y[n - 1]) / (x[n] - x[n - 1])
  out[above] <- y[n] + (concentration[above] - x[n]) * slope
  out
}

# round() rounds half to even; CPCB's calculator shows half up
.round_half_up <- function(x) floor(x + 0.5)

.aqi_split_label <- function(label, part = 1) {
  # a label repeats once per reading and regexec is slow
  labels <- unique(label)
  m <- regmatches(labels, regexec("^\\s*(.*?)\\s*(?:\\(([^()]*)\\))?\\s*$", labels, perl = TRUE))
  vapply(m, function(x) if (length(x)) x[part + 1] else NA_character_, character(1))[match(label, labels)]
}

# Unit of a label such as "PM2.5 (ug/m3)", "" when it has none
.aqi_label_unit <- function(label) .aqi_split_label(label, part = 2)

# A label without its unit, case or punctuation: "PM2.5 (ug/m3)" -> "pm25"
.aqi_key <- function(label) {
  # an earlier group stays in the name but is a qualifier: "CO (8hr) (ug/m3)"
  key <- tolower(gsub("\\([^()]*\\)", "", .aqi_split_label(as.character(label))))
  gsub("[^a-z0-9]", "", sub("2.5", "25", key, fixed = TRUE))
}

# "ug" or "mg" for a concentration unit such as "ug/m3" or "\u00b5g/m3", else ""
.aqi_mass_unit <- function(unit) {
  mass <- substr(gsub("\u03bc|\u00b5", "u", tolower(trimws(as.character(unit)))), 1, 2)
  ifelse(mass %in% c("ug", "mg"), mass, "")
}

# "ppb" or "ppm" for a volume unit, else ""
.aqi_volume_unit <- function(unit) {
  volume <- substr(tolower(trimws(as.character(unit))), 1, 3)
  ifelse(volume %in% c("ppb", "ppm"), volume, "")
}

# ppb to ug/m3 needs temperature and pressure, so those values are missing
.aqi_warn_volume <- function(pollutant, factor) {
  bad <- is.na(factor) & !is.na(pollutant)
  if (any(bad)) {
    warning(sprintf(
      "NAQI values in ppb or ppm treated as missing (%s): converting needs temperature and pressure",
      paste(unique(pollutant[bad]), collapse = ", ")
    ), call. = FALSE)
  }
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
#' between the band tops of CPCB's AQI calculator, so the sub-index has no
#' gaps between bands (PM2.5 30 is 50, and 60 is 100).
#'
#' @param pollutant A pollutant label (see \code{aqi_pollutant_name()}). A
#'   label with a mass unit, such as \code{"CO (ug/m3)"}, is converted to the
#'   NAQI unit. A label in ppb or ppm gives \code{NA}, with a warning, as the
#'   conversion needs temperature and pressure.
#' @param concentration Numeric vector of 24-hour averages (8-hour for CO and
#'   O3), in mg/m3 for CO and ug/m3 for the others when the label has no unit.
#' @return Numeric vector of sub-indices; the Severe band runs from 400 at
#'   its first breakpoint with slope 100 over the width of the Very Poor band
#'   (for O3, 100 over 540), and continues without a cap, so a sub-index can
#'   be more than 500. O3 above 208 stays on the 8-hour value.
#'   \code{NA}, negative and non-finite values give \code{NA}.
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
  factor <- .aqi_unit_factor(.aqi_label_unit(pollutant), name)
  .aqi_warn_volume(name, factor)
  .aqi_interp(name, as.numeric(concentration) * factor)
}

#' Overall National AQI of a set of concentrations
#'
#' @description
#' The overall AQI is the highest sub-index. CPCB requires at least three
#' pollutants, one of them PM2.5 or PM10.
#'
#' @param concentrations Named numeric vector or list: pollutant label to
#'   averaged concentration. Labels that are not NAQI pollutants, and missing,
#'   negative or non-finite values, are ignored. Mass units in a label are
#'   converted; values labelled in ppb or ppm are ignored with one warning.
#' @return List with \code{aqi} (integer, \code{NA} when the data are
#'   insufficient), \code{category}, \code{dominant_pollutant}, the named
#'   \code{sub_indices} and \code{status}: \code{"ok"}, \code{"no_pm"} or
#'   \code{"too_few_pollutants"}.
#' @references
#' CPCB (2014). *National Air Quality Index*. Control of Urban Pollution Series
#' CUPS/82/2014-15, pp. 35, 37, 44.
#' <https://cpcb.gov.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvRklOQUwtUkVQT1JUX0FRSV8ucGRm>
#' (accessed 2026-11-09).
#'
#' CPCB. *About National Air Quality Index*.
#' <https://cpcb.nic.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvQWJvdXRfQVFJLnBkZg==>
#' (accessed 2026-11-09).
#'
#' CPCB. *How is AQI calculated?*
#' <https://cpcb.gov.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvSG93X0FRSV9DYWxjdWxhdGVkLnBkZg==>
#' (accessed 2026-11-09).
#'
#' CPCB. *AQI-Calculator.xls*.
#' <https://cpcb.gov.in/upload/national-air-quality-index/AQI-Calculator.xls>
#' (accessed 2026-11-09).
#' @examples
#' compute_aqi(c("PM2.5" = 45, PM10 = 80, NO2 = 30))$aqi
#' @export
compute_aqi <- function(concentrations) {
  values <- unlist(concentrations)
  labels <- as.character(names(values))
  names_naqi <- aqi_pollutant_name(labels)
  factors <- .aqi_unit_factor(.aqi_label_unit(labels), names_naqi)
  .aqi_warn_volume(names_naqi, factors)
  numbers <- suppressWarnings(as.numeric(values)) * factors
  keep <- !is.na(names_naqi)
  subs <- stats::setNames(
    mapply(.aqi_interp, names_naqi[keep], numbers[keep]),
    names_naqi[keep]
  )
  subs <- subs[!is.na(subs)]
  # a repeated label counts once; ties go to the first in .aqi_pollutants
  order <- intersect(names(.aqi_pollutants), names(subs))
  subs <- vapply(order, function(n) max(subs[names(subs) == n]), numeric(1))
  status <- .aqi_status(length(subs), any(c("PM2.5", "PM10") %in% names(subs)))
  if (status != "ok") {
    return(list(
      aqi = NA_integer_, category = NA_character_,
      dominant_pollutant = NA_character_, sub_indices = subs, status = status
    ))
  }
  dominant <- names(subs)[which.max(subs)]
  aqi <- as.integer(.round_half_up(max(subs)))
  list(
    aqi = aqi, category = get_aqi_category(aqi),
    dominant_pollutant = dominant, sub_indices = subs, status = status
  )
}

# PM is checked before the count, the order Python uses too
.aqi_status <- function(n_pollutants, has_pm) {
  ifelse(!has_pm, "no_pm", ifelse(n_pollutants < .aqi_min_pollutants, "too_few_pollutants", "ok"))
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

# in category order; get_aqi_categories indexes into the names
.aqi_colours <- stats::setNames(
  c("#00B050", "#92D050", "#FFFF00", "#FF9900", "#FF0000", "#C00000"),
  names(.aqi_health_impacts)
)

#' CPCB colour of an AQI value
#'
#' @description
#' The colour CPCB uses for the National AQI category of each value, from
#' green (Good) to dark red (Severe).
#'
#' @param aqi_value Numeric vector of AQI values.
#' @return Character vector of hex colours, \code{NA} for missing values.
#' @examples
#' aqi_color(c(42, 180, NA, 450))
#' @export
aqi_color <- function(aqi_value) {
  unname(.aqi_colours[get_aqi_categories(aqi_value)])
}

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
