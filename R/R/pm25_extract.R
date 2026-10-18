# V5 coordinates carry float jitter, so terra warns about a missing
# geotransform; the cell positions are still exact
.pm25_rast <- function(nc_file) {
  withCallingHandlers(
    terra::rast(nc_file),
    warning = function(w) {
      if (grepl("geotransform", conditionMessage(w))) invokeRestart("muffleWarning")
    }
  )
}

.pm25_layer <- function(nc_file) {
  r <- .pm25_rast(nc_file)
  r[[.pm25_find_variable(r)]]
}

#' PM2.5 at points
#'
#' @description
#' Satellite PM2.5 of the grid cell that contains each point.
#'
#' @param latitude,longitude Numeric vectors of coordinates in decimal degrees.
#' @param year Integer year.
#' @param month Optional integer (1--12). If NULL, uses the annual file.
#' @param version,region,cache_dir Passed to \code{pm25_download_netcdf()}.
#' @param nc_file Optional path to a local NetCDF file to use instead of a
#'   download.
#' @return Numeric vector of PM2.5 in ug/m3, \code{NA} where the grid has no
#'   value.
#' @examplesIf interactive()
#' pm25_get_point(28.6139, 77.2090, year = 2023, month = 11, region = "AS")
#' @export
pm25_get_point <- function(latitude, longitude, year = NULL, month = NULL,
                           version = "V6GL03", region = "GL",
                           cache_dir = NULL,
                           nc_file = NULL) {
  if (is.null(nc_file)) {
    nc_file <- pm25_download_netcdf(
      year, month,
      cache_dir = cache_dir, region = region, version = version
    )
  }
  values <- terra::extract(.pm25_layer(nc_file), cbind(longitude, latitude))[[1]]
  if (anyNA(values)) {
    cli::cli_alert_warning("No PM2.5 data at {sum(is.na(values))} point(s).")
  }
  values
}

#' PM2.5 statistics for each polygon
#'
#' @description
#' Mean and standard deviation of satellite PM2.5 within each feature of a
#' GeoJSON file, over the cells whose centers fall inside it.
#'
#' @param geojson_file Path or URL of a GeoJSON file, or an \code{sf} object.
#' @param year Integer year.
#' @param month Optional integer (1--12). If NULL, uses the annual file.
#' @param id_field Optional column that names each feature. Defaults to
#'   \code{NAME_1}, then \code{name}, then the row number.
#' @param version,region,cache_dir Passed to \code{pm25_download_netcdf()}.
#' @param nc_file Optional path to a local NetCDF file to use instead of a
#'   download.
#' @return Data frame with the identifier column, \code{mean} and \code{std}.
#' @examplesIf interactive()
#' pm25_get_stats_by_polygon(
#'   "https://geo.bharatviz.org/geojsons/districts/India_LGD_districts.geojson",
#'   year = 2023, month = 11, id_field = "district_name", region = "AS"
#' )
#' @export
pm25_get_stats_by_polygon <- function(geojson_file, year = NULL, month = NULL,
                                      id_field = NULL, version = "V6GL03",
                                      region = "GL",
                                      cache_dir = NULL,
                                      nc_file = NULL) {
  gdf <- if (inherits(geojson_file, "sf")) {
    geojson_file
  } else {
    sf::st_read(geojson_file, quiet = TRUE)
  }
  gdf <- sf::st_transform(gdf, 4326)
  if (is.null(nc_file)) {
    nc_file <- pm25_download_netcdf(
      year, month,
      cache_dir = cache_dir, region = region, version = version
    )
  }
  pm25 <- .pm25_load_and_crop(nc_file, sf::st_bbox(gdf))
  zones <- terra::vect(sf::st_geometry(gdf))
  means <- terra::extract(pm25, zones, fun = mean, na.rm = TRUE, ID = FALSE)[[1]]
  sds <- terra::extract(pm25, zones, fun = stats::sd, na.rm = TRUE, ID = FALSE)[[1]]

  id_col <- if (!is.null(id_field) && id_field %in% names(gdf)) {
    id_field
  } else {
    intersect(c("NAME_1", "name"), names(gdf))[1]
  }
  ids <- if (is.na(id_col)) seq_len(nrow(gdf)) else gdf[[id_col]]
  out <- data.frame(id = ids, mean = means, std = sds)
  names(out)[1] <- if (is.na(id_col)) "index" else id_col
  out
}

#' Monthly mean PM2.5 over a region
#'
#' @description
#' Mean satellite PM2.5 over the bounding box of \code{shape} for each month
#' of a year, downloading the monthly files when they are not in
#' \code{cache_dir}. A directory that already holds the files under their
#' WUSTL names, such as a local copy of V5GL04, is read without downloading.
#'
#' @param shape An \code{sf} or \code{sfc} object defining the region.
#' @param year Integer year.
#' @param months Integer vector of months.
#' @param version,region,cache_dir Passed to \code{pm25_download_netcdf()}.
#' @return Data frame with columns \code{month} and \code{pm25}.
#' @examplesIf interactive()
#' delhi <- india_boundary(state = "Delhi")
#' pm25_monthly(delhi, 2022, version = "V5GL04", region = "AS")
#' @export
pm25_monthly <- function(shape, year, months = 1:12, version = "V6GL03",
                         region = "GL",
                         cache_dir = NULL) {
  var <- .pm25_spec(version)$variable
  pm25 <- vapply(months, function(m) {
    nc_file <- pm25_download_netcdf(
      year, m,
      cache_dir = cache_dir, region = region, version = version
    )
    pm25_read_netcdf_bbox(nc_file, shape, var = var)
  }, numeric(1))
  data.frame(month = as.integer(months), pm25 = pm25)
}
