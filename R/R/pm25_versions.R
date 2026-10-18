# WUSTL ACAG PM2.5 products in the public satpmdata bucket (us-east-1),
# matching PM25_VERSIONS in the Python package plus V5GL04
.pm25_bucket_url <- "https://satpmdata.s3.us-east-1.amazonaws.com/"

.pm25_v5_regions <- c(GL = "Global", AS = "Asia", EU = "Europe", "NA" = "NorthAmerica")

.pm25_versions <- list(
  V6GL03 = list(
    name = "V6.GL.03 (CNN)", dir = "V6GL03/CNNPM25", stem = "V6GL03.CNNPM25",
    variable = "PM25", years = c(1998L, 2024L),
    regions = c(GL = "GL", AS = "AS", EU = "EU", "NA" = "NA", AF = "AF")
  ),
  V6 = list(
    name = "V6.GL.02.04 (CNN)", dir = "archive/V6GL0204/CNNPM25",
    stem = "V6GL02.04.CNNPM25", variable = "PM25", years = c(1998L, 2023L),
    regions = c(GL = "GL", AS = "AS", EU = "EU", "NA" = "NA")
  ),
  V5 = list(
    name = "V5.GL.05.02 (GWR)", dir = "archive/V5GL0502/GWRPM25",
    stem = "V5GL0502.HybridPM25", variable = "GWRPM25", years = c(1998L, 2023L),
    regions = .pm25_v5_regions
  ),
  V5GL04 = list(
    name = "V5.GL.04 (GWR)", dir = "archive/V5GL04/GWRPM25",
    stem = "V5GL04.HybridPM25", variable = "GWRPM25", years = c(1998L, 2022L),
    regions = .pm25_v5_regions
  )
)

.pm25_spec <- function(version) {
  spec <- .pm25_versions[[version]]
  if (is.null(spec)) {
    stop(sprintf(
      "version must be one of: %s.",
      paste(names(.pm25_versions), collapse = ", ")
    ), call. = FALSE)
  }
  spec
}

.pm25_check_args <- function(year, month, region, version = "V6GL03") {
  spec <- .pm25_spec(version)
  if (length(year) != 1 || is.na(year) ||
    year < spec$years[1] || year > spec$years[2]) {
    stop(sprintf(
      "year must be between %d and %d for %s.",
      spec$years[1], spec$years[2], version
    ), call. = FALSE)
  }
  if (!is.null(month) && (length(month) != 1 || is.na(month) ||
    month < 1 || month > 12)) {
    stop("month must be NULL or an integer between 1 and 12.", call. = FALSE)
  }
  if (!region %in% names(spec$regions)) {
    stop(sprintf(
      "region must be one of: %s.",
      paste(names(spec$regions), collapse = ", ")
    ), call. = FALSE)
  }
}

.pm25_get_aws_filename <- function(year, month = NULL, region = "GL",
                                   version = "V6GL03") {
  spec <- .pm25_spec(version)
  first <- if (is.null(month)) 1L else as.integer(month)
  last <- if (is.null(month)) 12L else as.integer(month)
  sprintf(
    "%s.%s.%d%02d-%d%02d.nc",
    spec$stem, spec$regions[[region]],
    as.integer(year), first, as.integer(year), last
  )
}

.pm25_get_aws_url <- function(year, month = NULL, region = "GL",
                              version = "V6GL03") {
  spec <- .pm25_spec(version)
  period <- if (is.null(month)) "Annual" else "Monthly"
  paste0(
    .pm25_bucket_url, spec$dir, "/", period, "/", spec$regions[[region]], "/",
    .pm25_get_aws_filename(year, month, region, version)
  )
}
