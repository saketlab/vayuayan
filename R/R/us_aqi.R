# EPA-454/B-24-002 (May 2024), as python/vayuayan/us_aqi.py:
# https://document.airnow.gov/technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf
# bands: concentration low, high, index low, high
.us_aqi_pollutants <- list(
  PM2.5 = list(unit = "ug/m3", decimals = 1, molar_mass = NA, bands = c(
    0.0, 9.0, 0, 50, 9.1, 35.4, 51, 100, 35.5, 55.4, 101, 150,
    55.5, 125.4, 151, 200, 125.5, 225.4, 201, 300, 225.5, 325.4, 301, 500
  )),
  PM10 = list(unit = "ug/m3", decimals = 0, molar_mass = NA, bands = c(
    0, 54, 0, 50, 55, 154, 51, 100, 155, 254, 101, 150,
    255, 354, 151, 200, 355, 424, 201, 300, 425, 604, 301, 500
  )),
  O3 = list(unit = "ppm", decimals = 3, molar_mass = 48.00, bands = c(
    0.000, 0.054, 0, 50, 0.055, 0.070, 51, 100, 0.071, 0.085, 101, 150,
    0.086, 0.105, 151, 200, 0.106, 0.200, 201, 300
  )),
  O3_1h = list(unit = "ppm", decimals = 3, molar_mass = 48.00, bands = c(
    0.125, 0.164, 101, 150, 0.165, 0.204, 151, 200,
    0.205, 0.404, 201, 300, 0.405, 0.604, 301, 500
  )),
  CO = list(unit = "ppm", decimals = 1, molar_mass = 28.01, bands = c(
    0.0, 4.4, 0, 50, 4.5, 9.4, 51, 100, 9.5, 12.4, 101, 150,
    12.5, 15.4, 151, 200, 15.5, 30.4, 201, 300, 30.5, 50.4, 301, 500
  )),
  SO2 = list(unit = "ppb", decimals = 0, molar_mass = 64.07, bands = c(
    0, 35, 0, 50, 36, 75, 51, 100, 76, 185, 101, 150, 186, 304, 151, 200
  )),
  SO2_24h = list(unit = "ppb", decimals = 0, molar_mass = 64.07, bands = c(
    305, 604, 201, 300, 605, 1004, 301, 500
  )),
  NO2 = list(unit = "ppb", decimals = 0, molar_mass = 46.01, bands = c(
    0, 53, 0, 50, 54, 100, 51, 100, 101, 360, 101, 150,
    361, 649, 151, 200, 650, 1249, 201, 300, 1250, 2049, 301, 500
  ))
)

# Upper AQI limit of each category; Hazardous is every value above 300
.us_aqi_categories <- c(
  Good = 50, Moderate = 100, "Unhealthy for Sensitive Groups" = 150,
  Unhealthy = 200, "Very Unhealthy" = 300
)
.us_aqi_category_names <- c(names(.us_aqi_categories), "Hazardous")

# Standard AQI colors (EPA Table 2) and ColorVision Assist colors (Table 3)
.us_aqi_colors <- c("#00E400", "#FFFF00", "#FF7E00", "#FF0000", "#8F3F97", "#7E0023")
.us_aqi_colors_assist <- c("#9EFF91", "#FFC905", "#FF8205", "#F02200", "#890997", "#640015")

# litres per mole at 25 degrees C, the EPA's conversion
.us_aqi_molar_volume <- 24.45

# the EPA switches to 1-hour O3 and 24-hour SO2 above these tables
.us_aqi_no_extrapolation <- c("O3", "SO2")

#' US AQI name of a pollutant label
#'
#' @description
#' Match a pollutant label such as \code{"PM2.5 (ug/m3)"}, \code{"Ozone"},
#' \code{"O3_1h"} or \code{"SO2 24h"} to its US EPA AQI name.
#'
#' @param label Character vector of labels.
#' @return Character vector of US AQI names (\code{"PM2.5"}, \code{"PM10"},
#'   \code{"O3"}, \code{"O3_1h"}, \code{"CO"}, \code{"SO2"},
#'   \code{"SO2_24h"}, \code{"NO2"}), \code{NA} for other labels.
#' @examples
#' us_aqi_pollutant_name(c("PM2.5 (ug/m3)", "Ozone", "NH3"))
#' @export
us_aqi_pollutant_name <- function(label) {
  unname(.us_aqi_names[.aqi_key(label)])
}

.us_aqi_names <- c(
  stats::setNames(names(.us_aqi_pollutants), .aqi_key(names(.us_aqi_pollutants))),
  ozone = "O3", ozone1h = "O3_1h", o38h = "O3", co8h = "CO",
  so21h = "SO2", no21h = "NO2", pm2524h = "PM2.5", pm1024h = "PM10"
)

#' US EPA AQI sub-index of concentrations
#'
#' @description
#' The US EPA AQI sub-index of one pollutant (May 2024 tables). Each
#' concentration is truncated to the precision of the table, then the
#' sub-index is a linear function of the concentration within its band.
#'
#' @param pollutant A pollutant label (see \code{us_aqi_pollutant_name()}).
#'   A label with a mass unit, such as \code{"O3 (ug/m3)"} or
#'   \code{"CO (mg/m3)"}, is converted to ppm or ppb at 25 degrees C. Without
#'   a unit, PM2.5 and PM10 are in ug/m3, O3 and CO in ppm, and SO2 and NO2
#'   in ppb.
#' @param concentration Numeric vector of averages: 24-hour for PM2.5, PM10
#'   and \code{SO2_24h}, 8-hour for O3 and CO, and 1-hour for \code{O3_1h},
#'   SO2 and NO2.
#' @return Numeric vector of sub-indices. Above the highest breakpoint the
#'   sub-index continues on the slope of the 301-500 band, so it can be more
#'   than 500. \code{NA} for missing values, for 8-hour O3 above 0.200 ppm,
#'   1-hour O3 below 0.125 ppm, 1-hour SO2 above 304 ppb and 24-hour SO2
#'   below 305 ppb, where the EPA uses the other averaging time.
#' @examples
#' us_aqi_sub_index("PM2.5", c(9, 35.4, 400))
#' @export
us_aqi_sub_index <- function(pollutant, concentration) {
  name <- us_aqi_pollutant_name(pollutant)
  if (length(name) != 1 || is.na(name)) {
    stop(sprintf(
      "'%s' is not a US AQI pollutant: %s", pollutant,
      paste(names(.us_aqi_pollutants), collapse = ", ")
    ), call. = FALSE)
  }
  p <- .us_aqi_pollutants[[name]]
  c <- .us_aqi_to_epa_unit(p, .aqi_label_unit(pollutant), as.numeric(concentration))
  # 1e-9 keeps 0.0549999... from a unit conversion at 0.055
  c <- floor(c * 10^p$decimals + 1e-9) / 10^p$decimals
  bands <- matrix(p$bands, ncol = 4, byrow = TRUE)
  vapply(c, function(x) {
    if (is.na(x)) {
      return(NA_real_)
    }
    i <- which(bands[, 1] <= x & x <= bands[, 2])
    # the EPA continues the 301-500 slope above 500
    if (!length(i) && x > bands[nrow(bands), 2] && !name %in% .us_aqi_no_extrapolation) {
      i <- nrow(bands)
    }
    if (length(i)) {
      b <- bands[i[1], ]
      return((b[4] - b[3]) / (b[2] - b[1]) * (x - b[1]) + b[3])
    }
    # below the table of 1-hour O3 or 24-hour SO2, the other average applies
    NA_real_
  }, numeric(1))
}

.us_aqi_to_epa_unit <- function(p, unit, value) {
  prefix <- .aqi_mass_unit(unit)
  if (is.na(p$molar_mass) || prefix == "") {
    return(value)
  }
  mg_per_m3 <- if (prefix == "ug") value / 1000 else value
  ppm <- mg_per_m3 * .us_aqi_molar_volume / p$molar_mass
  if (p$unit == "ppb") ppm * 1000 else ppm
}

#' US EPA AQI category of AQI values
#'
#' @param aqi_value Numeric vector of AQI values.
#' @return Character vector of categories (\code{"Good"} to
#'   \code{"Hazardous"}, which includes all values above 300),
#'   \code{"No Data"} for missing values.
#' @examples
#' us_aqi_category(c(42, 120, NA))
#' @export
us_aqi_category <- function(aqi_value) {
  out <- .us_aqi_category_names[findInterval(aqi_value, c(-Inf, .us_aqi_categories), left.open = TRUE)]
  out[is.na(aqi_value)] <- "No Data"
  out
}

#' US EPA AQI color of AQI values
#'
#' @description
#' The EPA color of each AQI value as a hex code: the standard colors (EPA
#' Table 2), or the ColorVision Assist colors (Table 3), which have more
#' contrast for people with color vision deficiency.
#'
#' @param aqi_value Numeric vector of AQI values.
#' @param color_vision_assist Logical. Use the ColorVision Assist colors.
#' @return Character vector of hex colors, \code{NA} for missing values.
#' @examples
#' us_aqi_color(c(42, 120, NA))
#' us_aqi_color(120, color_vision_assist = TRUE)
#' @export
us_aqi_color <- function(aqi_value, color_vision_assist = FALSE) {
  colors <- if (color_vision_assist) .us_aqi_colors_assist else .us_aqi_colors
  unname(stats::setNames(colors, .us_aqi_category_names)[us_aqi_category(aqi_value)])
}

#' Overall US EPA AQI of a set of concentrations
#'
#' @description
#' The US AQI is the highest sub-index, rounded half up. The EPA has no
#' minimum number of pollutants. For O3 and SO2 with both averaging times,
#' the higher sub-index counts. If the 1-hour SO2 is 305 ppb or more and the
#' 24-hour SO2 is below 305 ppb, the SO2 sub-index is 200.
#'
#' @param concentrations Named numeric vector or list: pollutant label to
#'   concentration (see \code{us_aqi_sub_index()}). Labels that are not US
#'   AQI pollutants and missing values are ignored.
#' @return List with \code{aqi} (integer, \code{NA} when no pollutant has a
#'   sub-index), \code{category}, \code{dominant_pollutant} and the named
#'   \code{sub_indices}.
#' @examples
#' compute_us_aqi(c("PM2.5" = 35.4, O3 = 0.060))$aqi
#' @export
compute_us_aqi <- function(concentrations) {
  values <- unlist(concentrations)
  names_us <- us_aqi_pollutant_name(names(values))
  subs <- numeric(0)
  outside <- character(0) # pollutants with a value outside their table
  for (i in which(!is.na(names_us))) {
    s <- us_aqi_sub_index(names(values)[i], values[[i]])
    if (!is.na(s)) {
      subs[names_us[i]] <- max(s, subs[names_us[i]], na.rm = TRUE)
    } else if (!is.na(values[[i]])) {
      outside <- c(outside, names_us[i])
    }
  }
  # EPA: 1-hour SO2 >= 305 ppb with 24-hour < 305 ppb gives 200
  if (all(c("SO2", "SO2_24h") %in% outside)) {
    subs["SO2"] <- max(200, subs["SO2"], na.rm = TRUE)
  }
  if (!length(subs)) {
    return(list(
      aqi = NA_integer_, category = NA_character_,
      dominant_pollutant = NA_character_, sub_indices = subs
    ))
  }
  aqi <- as.integer(.round_half_up(max(subs)))
  list(
    aqi = aqi, category = us_aqi_category(aqi),
    dominant_pollutant = names(subs)[which.max(subs)], sub_indices = subs
  )
}
