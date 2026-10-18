.pm25_find_variable <- function(pm25_raster) {
  var_names <- names(pm25_raster)
  if ("PM25" %in% var_names) {
    return("PM25")
  } else if ("GWRPM25" %in% var_names) {
    return("GWRPM25")
  } else {
    stop(sprintf(
      "PM2.5 variable not found. Available variables: %s",
      paste(var_names, collapse = ", ")
    ))
  }
}

.pm25_load_and_crop <- function(nc_file, bbox) {
  if (any(is.na(bbox)) || any(is.infinite(bbox))) {
    stop("Bounding box contains invalid values.")
  }

  pm25_raster <- .pm25_rast(nc_file)
  pm25_var <- .pm25_find_variable(pm25_raster)
  pm25_layer <- pm25_raster[[pm25_var]]

  bbox_buffered <- sf::st_bbox(c(
    xmin = as.numeric(bbox$xmin) - 0.1,
    ymin = as.numeric(bbox$ymin) - 0.1,
    xmax = as.numeric(bbox$xmax) + 0.1,
    ymax = as.numeric(bbox$ymax) + 0.1
  ))
  if (any(is.na(bbox_buffered)) || any(is.infinite(bbox_buffered))) {
    stop("Buffered bounding box contains invalid values.")
  }

  terra::crop(pm25_layer, terra::ext(bbox_buffered))
}

.pm25_get_stats_grouped <- function(gdf, nc_file, group_cols) {
  pm25_cropped <- .pm25_load_and_crop(nc_file, sf::st_bbox(gdf))

  results <- list()

  gdf_grouped <- gdf %>%
    dplyr::group_by(dplyr::across(dplyr::all_of(group_cols))) %>%
    dplyr::group_split()

  for (group_gdf in gdf_grouped) {
    tryCatch(
      {
        group_vals <- group_gdf[1, group_cols, drop = FALSE]
        combined_geom <- sf::st_union(group_gdf)
        geom_vect <- terra::vect(combined_geom)
        pm25_masked <- terra::mask(pm25_cropped, geom_vect)

        values <- terra::values(pm25_masked, na.rm = TRUE)

        result <- as.list(group_vals)

        if (length(values) > 0) {
          result$mean <- mean(values)
          result$std <- sd(values)
          result$min <- min(values)
          result$max <- max(values)
          result$count <- length(values)
        } else {
          result$mean <- NA
          result$std <- NA
          result$min <- NA
          result$max <- NA
          result$count <- 0
        }

        results[[length(results) + 1]] <- result
      },
      error = function(e) {
        cli::cli_alert_warning("Error processing group: {e$message}")
      }
    )
  }

  return(dplyr::bind_rows(results))
}

#' Download PM2.5 NetCDF file
#'
#' @description
#' Download a WUSTL ACAG SatPM2.5 NetCDF file from the AWS Open Data registry
#' and cache it locally. A cached file larger than 1 MB is reused without
#' downloading it again.
#'
#' Use \code{region = "AS"} for work within Asia, including India; its files
#' are much smaller than the global ones.
#'
#' @param year Integer. Year for data, within the range of \code{version}.
#' @param month Optional integer (1--12). If NULL, downloads the annual file.
#' @param cache_dir Character. Directory to cache NetCDF files. \code{NULL}
#'   uses the \code{pm25} folder of \code{vayuayan_cache_dir()}, and also
#'   reads files from the Python package's cache.
#' @param force_download Logical. Download again even if the file is cached.
#' @param region Character. Spatial subset: \code{"GL"} (global, default),
#'   \code{"AS"} (Asia), \code{"EU"}, \code{"NA"}, or \code{"AF"} (V6GL03
#'   only).
#' @param version Character. Dataset version:
#'   \describe{
#'     \item{\code{"V6GL03"}}{V6.GL.03, CNN, 1998--2024 (default).}
#'     \item{\code{"V6"}}{V6.GL.02.04, CNN, 1998--2023.}
#'     \item{\code{"V5"}}{V5.GL.05.02, GWR, 1998--2023.}
#'     \item{\code{"V5GL04"}}{V5.GL.04, GWR, 1998--2022.}
#'   }
#' @return Character. Path to the downloaded (or cached) NetCDF file.
#' @source \url{https://www.satpm.org/v6-gl-03}
#' @examplesIf interactive()
#' # Monthly Asia subset
#' nc_path <- pm25_download_netcdf(year = 2023, month = 11, region = "AS")
#'
#' # The older GWR product
#' nc_path <- pm25_download_netcdf(2022, 11, region = "AS", version = "V5GL04")
#' @export
pm25_download_netcdf <- function(year, month = NULL,
                                 cache_dir = NULL,
                                 force_download = FALSE,
                                 region = "GL",
                                 version = "V6GL03") {
  .pm25_check_args(year, month, region, version)
  dirs <- if (is.null(cache_dir)) .pm25_default_dirs() else cache_dir
  filename <- .pm25_get_aws_filename(year, month, region, version)

  if (!force_download) {
    cached <- .cache_lookup(dirs, filename, min_size = 1024 * 1024)
    if (!is.null(cached)) {
      cli::cli_alert_info("Using cached file: {cached}")
      return(cached)
    }
  }
  dir.create(dirs[1], recursive = TRUE, showWarnings = FALSE)
  cached_path <- file.path(dirs[1], filename)

  aws_url <- .pm25_get_aws_url(year, month, region, version)
  cli::cli_alert_info("Downloading {aws_url}")

  # temp name so an interrupted transfer never looks cached
  partial <- paste0(cached_path, ".part")
  on.exit(unlink(partial), add = TRUE)
  response <- tryCatch(
    httr::GET(
      aws_url,
      httr::write_disk(partial, overwrite = TRUE),
      if (interactive()) httr::progress()
    ),
    error = function(e) {
      stop(sprintf("Failed to download NetCDF data: %s", conditionMessage(e)),
        call. = FALSE
      )
    }
  )
  httr::stop_for_status(response, task = paste("download", aws_url))
  file.rename(partial, cached_path)

  size_mb <- file.info(cached_path)$size / (1024 * 1024)
  cli::cli_alert_success("Download complete: {round(size_mb, 1)} MB")
  cached_path
}

#' Get PM2.5 statistics for a region
#'
#' @description
#' Compute mean, SD, min, max, and pixel count of satellite PM2.5 for a
#' region defined by a GeoJSON file. Optionally group by a column in the
#' GeoJSON (e.g. district name) to return per-group statistics.
#'
#' @param geojson_file Character. Path or URL to a GeoJSON file defining the
#'   region (remote \code{http(s)://} URLs are read directly).
#' @param year Integer. Year of the NetCDF data (e.g. \code{2023}). Ignored
#'   when \code{nc_file} is supplied.
#' @param month Optional integer (1--12). If NULL, uses annual data. Ignored
#'   when \code{nc_file} is supplied.
#' @param cache_dir Character. Directory to cache NetCDF files. \code{NULL}
#'   uses the \code{pm25} folder of \code{vayuayan_cache_dir()}, and also
#'   reads files from the Python package's cache.
#' @param group_by Optional character. Column name(s) in the GeoJSON to
#'   group polygons by (comma-separated for multiple columns).
#' @param nc_file Optional character. Path to a local NetCDF file to use
#'   directly. When supplied, no download is attempted and \code{year}/
#'   \code{month} are ignored. Useful for offline data (e.g. WUSTL V5GL04
#'   files on a local mount).
#' @param region Character. Spatial subset to download, passed to
#'   \code{pm25_download_netcdf()}. \code{"AS"} covers India in a smaller
#'   file.
#' @param version Character. Dataset version, passed to
#'   \code{pm25_download_netcdf()}.
#' @return List (or data frame if \code{group_by} is specified) with
#'   PM2.5 statistics: \code{mean}, \code{std}, \code{min}, \code{max},
#'   \code{count}.
#' @examplesIf interactive()
#' # Single region (remote BharatViz boundary)
#' stats <- pm25_get_stats(
#'   "https://geo.bharatviz.org/geojsons/cities/delhi.geojson",
#'   year = 2023, month = 11
#' )
#' cat("Mean PM2.5:", round(stats$mean, 1), "ug/m3")
#'
#' # Grouped by district
#' stats_by_district <- pm25_get_stats(
#'   "https://geo.bharatviz.org/geojsons/districts/India_LGD_districts.geojson",
#'   year     = 2023,
#'   month    = 11,
#'   group_by = "district_name"
#' )
#'
#' # Use a local (offline) NetCDF file directly
#' stats <- pm25_get_stats(
#'   "https://geo.bharatviz.org/geojsons/cities/delhi.geojson",
#'   nc_file = "V5GL04.HybridPM25.Global.202211-202211.nc"
#' )
#' @export
pm25_get_stats <- function(geojson_file, year = NULL, month = NULL,
                           cache_dir = NULL,
                           group_by = NULL, nc_file = NULL, region = "GL",
                           version = "V6GL03") {
  # geojson_file may be a local path or a remote URL (read directly by
  # sf::st_read via GDAL). Only validate existence for local paths.
  is_url <- grepl("^(https?|ftp)://", geojson_file)
  if (!is_url && !file.exists(geojson_file)) {
    stop(sprintf("GeoJSON file not found: %s", geojson_file))
  }

  # When nc_file is supplied, use that local NetCDF directly and skip the
  # download. Otherwise fetch (or reuse a cached copy) for year/month.
  if (is.null(nc_file)) {
    if (is.null(year)) {
      stop("Either 'year' or 'nc_file' must be supplied.")
    }
    nc_file <- pm25_download_netcdf(
      year, month,
      cache_dir = cache_dir, region = region, version = version
    )
  } else if (!file.exists(nc_file)) {
    stop(sprintf("NetCDF file not found: %s", nc_file))
  }

  gdf <- sf::st_read(geojson_file, quiet = TRUE)
  gdf <- sf::st_transform(gdf, 4326)

  if (!is.null(group_by)) {
    group_cols <- strsplit(group_by, ",")[[1]]
    group_cols <- trimws(group_cols)

    missing_cols <- setdiff(group_cols, names(gdf))
    if (length(missing_cols) > 0) {
      stop(sprintf(
        "Column(s) %s not found in GeoJSON. Available columns: %s",
        paste(missing_cols, collapse = ", "),
        paste(names(gdf), collapse = ", ")
      ))
    }

    return(.pm25_get_stats_grouped(gdf, nc_file, group_cols))
  }

  gdf <- gdf[!sf::st_is_empty(gdf) & as.numeric(sf::st_area(gdf)) > 0, ]

  polygon <- tryCatch(
    {
      sf::st_union(gdf)
    },
    error = function(e) {
      cli::cli_alert_warning("Union failed, retrying after a GeoJSON round trip.")
      tmp_geojson <- tempfile(fileext = ".geojson")
      on.exit(unlink(tmp_geojson), add = TRUE)
      sf::st_write(gdf, tmp_geojson, delete_dsn = TRUE, quiet = TRUE)
      gdf <- sf::st_read(tmp_geojson, quiet = TRUE)
      sf::st_union(gdf)
    }
  )
  if (sf::st_is_empty(polygon) || is.null(polygon)) {
    stop("Polygon is empty or invalid.")
  }

  pm25_cropped <- .pm25_load_and_crop(nc_file, sf::st_bbox(polygon))

  polygon_vect <- terra::vect(polygon)
  pm25_masked <- terra::mask(pm25_cropped, polygon_vect)

  values <- terra::values(pm25_masked, na.rm = TRUE)

  if (length(values) == 0) {
    stop("No valid PM2.5 data found within the polygon boundary")
  }

  return(list(
    mean = mean(values),
    std = sd(values),
    min = min(values),
    max = max(values),
    count = length(values)
  ))
}

#' List cached PM2.5 NetCDF files
#'
#' @description
#' List all cached NetCDF files in the cache directory with file sizes.
#'
#' @param cache_dir Character. Directory containing cached files. \code{NULL}
#'   uses the \code{pm25} folder of \code{vayuayan_cache_dir()}.
#' @return Character vector of cached file paths.
#' @examplesIf interactive()
#' files <- pm25_list_cached_files()
#' @export
pm25_list_cached_files <- function(cache_dir = NULL) {
  cache_dir <- cache_dir %||% file.path(vayuayan_cache_dir(), "pm25")
  if (!dir.exists(cache_dir)) {
    cli::cli_alert_info("Cache directory does not exist")
    return(character(0))
  }

  cached_files <- list.files(
    cache_dir,
    pattern = "\\.nc$",
    full.names = TRUE
  )

  if (length(cached_files) > 0) {
    cli::cli_alert_info("Cached files in {cache_dir}:")
    for (file in cached_files) {
      size_mb <- file.info(file)$size / (1024 * 1024)
      cli::cli_alert(
        "   {basename(file)} ({round(size_mb, 1)} MB)"
      )
    }
  } else {
    cli::cli_alert_info("No cached files in {cache_dir}")
  }

  return(cached_files)
}

#' Clear PM2.5 cache
#'
#' @description
#' Delete all cached NetCDF files from the cache directory to free disk space.
#'
#' @param cache_dir Character. Directory containing cached files. \code{NULL}
#'   uses the \code{pm25} folder of \code{vayuayan_cache_dir()}.
#' @return Invisibly returns NULL.
#' @examplesIf interactive()
#' pm25_clear_cache()
#' @export
pm25_clear_cache <- function(cache_dir = NULL) {
  cache_dir <- cache_dir %||% file.path(vayuayan_cache_dir(), "pm25")
  if (!dir.exists(cache_dir)) {
    cli::cli_alert_info("Cache directory does not exist")
    return(invisible(NULL))
  }

  cached_files <- list.files(
    cache_dir,
    pattern = "\\.nc$",
    full.names = TRUE
  )

  for (file in cached_files) {
    tryCatch(
      {
        unlink(file)
        cli::cli_alert_success("Removed: {file}")
      },
      error = function(e) {
        cli::cli_alert_warning("Could not remove {file}: {e$message}")
      }
    )
  }

  cli::cli_alert_success("Cache cleared: {cache_dir}")
  invisible(NULL)
}

# Bounding-box readers for gridded PM2.5 NetCDF (e.g. WUSTL ACAG). These files
# store data in [lon, lat] order; the functions read only the pixels covering a
# region's bounding box, avoiding a full global array load. Defaults match the
# WUSTL V5GL04 product (variable "GWRPM25"); override var/lon_name/lat_name for
# other products.

#' Build the file path for a WUSTL V5GL04 monthly NetCDF
#'
#' @param year Integer year (1998--2022).
#' @param month Integer month (1--12).
#' @param base_dir Directory holding the monthly NetCDF files.
#' @return Character path to the monthly NetCDF file.
#' @examples
#' pm25_v5gl04_path(2022, 11, base_dir = "~/data/V5GL04/Monthly")
#' @export
pm25_v5gl04_path <- function(year, month, base_dir) {
  file.path(base_dir, sprintf(
    "V5GL04.HybridPM25.Global.%04d%02d-%04d%02d.nc",
    year, month, year, month
  ))
}

# Read the bbox subset of a gridded NetCDF as a list(lons, lats, data).
.pm25_read_bbox <- function(nc_path, shape, var, lon_name, lat_name) {
  if (!requireNamespace("ncdf4", quietly = TRUE)) {
    stop("Package 'ncdf4' is required to read NetCDF subsets. ",
      "Install it with install.packages(\"ncdf4\").",
      call. = FALSE
    )
  }
  bbox <- sf::st_bbox(shape)
  nc <- ncdf4::nc_open(nc_path)
  on.exit(ncdf4::nc_close(nc))
  lons <- ncdf4::ncvar_get(nc, lon_name)
  lats <- ncdf4::ncvar_get(nc, lat_name)
  lon_idx <- which(lons >= bbox["xmin"] & lons <= bbox["xmax"])
  lat_idx <- which(lats >= bbox["ymin"] & lats <= bbox["ymax"])
  data <- ncdf4::ncvar_get(
    nc, var,
    start = c(min(lon_idx), min(lat_idx)),
    count = c(length(lon_idx), length(lat_idx))
  )
  list(lons = lons[lon_idx], lats = lats[lat_idx], data = data)
}

#' Mean gridded PM2.5 over a region's bounding box
#'
#' Reads only the pixels covering \code{shape}'s bounding box and returns the
#' mean value. Useful for a quick monthly figure over a city or district.
#'
#' @param nc_path Path to a gridded PM2.5 NetCDF file.
#' @param shape An \code{sf} object defining the region.
#' @param var NetCDF variable name. Defaults to \code{"GWRPM25"} (WUSTL V5GL04).
#' @param lon_name,lat_name Longitude/latitude dimension names.
#' @return Numeric mean value over the bounding box.
#' @examplesIf interactive()
#' shape <- sf::st_read("https://geo.bharatviz.org/geojsons/cities/delhi.geojson")
#' pm25_read_netcdf_bbox(pm25_v5gl04_path(2022, 11, "."), shape)
#' @export
pm25_read_netcdf_bbox <- function(nc_path, shape, var = "GWRPM25",
                                  lon_name = "lon", lat_name = "lat") {
  d <- .pm25_read_bbox(nc_path, shape, var, lon_name, lat_name)
  mean(d$data, na.rm = TRUE)
}

#' Load a gridded PM2.5 raster cropped to a region's bounding box
#'
#' Reads the pixels covering \code{shape}'s bounding box and returns them as a
#' \code{terra} raster in EPSG:4326, ready for masking or zonal extraction.
#'
#' @param nc_path Path to a gridded PM2.5 NetCDF file.
#' @param shape An \code{sf} object defining the region.
#' @param var NetCDF variable name. Defaults to \code{"GWRPM25"} (WUSTL V5GL04).
#' @param lon_name,lat_name Longitude/latitude dimension names.
#' @param mask Logical. If \code{TRUE}, set pixels outside \code{shape} to
#'   \code{NA}.
#' @return A \code{terra} \code{SpatRaster} cropped to the bounding box.
#' @examplesIf interactive()
#' shape <- sf::st_read("https://geo.bharatviz.org/geojsons/cities/delhi.geojson")
#' r <- pm25_load_netcdf_bbox(pm25_v5gl04_path(2022, 11, "."), shape)
#' @export
pm25_load_netcdf_bbox <- function(nc_path, shape, var = "GWRPM25",
                                  lon_name = "lon", lat_name = "lat",
                                  mask = FALSE) {
  d <- .pm25_read_bbox(nc_path, shape, var, lon_name, lat_name)
  r <- terra::rast(
    nrows = length(d$lats), ncols = length(d$lons),
    xmin = min(d$lons), xmax = max(d$lons),
    ymin = min(d$lats), ymax = max(d$lats),
    crs = "EPSG:4326"
  )
  terra::values(r) <- t(d$data)[nrow(t(d$data)):1, ]
  if (mask) {
    r <- terra::mask(r, terra::vect(sf::st_geometry(shape)))
  }
  r
}
