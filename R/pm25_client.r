.pm25_aws_base_url <- "https://s3.us-west-2.amazonaws.com/v6.gl.02.04/V6.GL.02.04/GL/"

.pm25_get_aws_filename <- function(year, month = NULL) {
    if (is.null(month)) {
        return(sprintf("V6GL02.04.CNNPM25.GL.%d01-%d12.nc", year, year))
    }
    return(sprintf(
        "V6GL02.04.CNNPM25.GL.%d%02d-%d%02d.nc",
        year, month, year, month
    ))
}

.pm25_get_aws_url <- function(year, month = NULL) {
    filename <- .pm25_get_aws_filename(year, month)
    if (is.null(month)) {
        return(paste0(.pm25_aws_base_url, "Annual/", filename))
    }
    return(paste0(.pm25_aws_base_url, "Monthly/", year, "/", filename))
}

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

    pm25_raster <- terra::rast(nc_file)
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
#' Download a WUSTL ACAG V6GL02 NetCDF file from AWS S3 and cache it locally.
#' If the file is already cached and complete (>1 MB), the cached version
#' is returned without re-downloading.
#'
#' @param year Integer. Year for data (e.g. \code{2023}).
#' @param month Optional integer (1--12). If NULL, downloads the annual file.
#' @param cache_dir Character. Directory to cache NetCDF files.
#'   Default: \code{"pm25_data"}.
#' @param force_download Logical. Force re-download even if file exists.
#'   Default: \code{FALSE}.
#' @return Character. Path to the downloaded (or cached) NetCDF file.
#' @examples
#' \dontrun{
#' # Download monthly data
#' nc_path <- pm25_download_netcdf(year = 2023, month = 11)
#'
#' # Download annual data
#' nc_path <- pm25_download_netcdf(year = 2023)
#' }
#' @export
pm25_download_netcdf <- function(year, month = NULL,
                                 cache_dir = "pm25_data",
                                 force_download = FALSE) {
    if (!dir.exists(cache_dir)) {
        dir.create(cache_dir, recursive = TRUE)
    }

    filename <- .pm25_get_aws_filename(year, month)
    cached_path <- file.path(cache_dir, filename)

    if (file.exists(cached_path) && !force_download) {
        file_size <- file.info(cached_path)$size
        if (file_size > 1024 * 1024) {
            cli::cli_alert_info("Using cached file: {cached_path}")
            return(cached_path)
        } else {
            cli::cli_alert_warning(
                "Cached file appears incomplete, re-downloading..."
            )
        }
    }

    aws_url <- .pm25_get_aws_url(year, month)
    cli::cli_alert_info("Downloading PM2.5 data from AWS...")
    cli::cli_alert_info("Source: {aws_url}")
    cli::cli_alert_info("Destination: {cached_path}")

    tryCatch(
        {
            download.file(
                aws_url,
                cached_path,
                method = "auto",
                mode = "wb",
                quiet = FALSE
            )

            final_size <- file.info(cached_path)$size / (1024 * 1024)
            cli::cli_alert_success(
                "Download complete: {round(final_size, 1)} MB"
            )

            return(cached_path)
        },
        error = function(e) {
            if (file.exists(cached_path)) {
                unlink(cached_path)
            }
            stop(sprintf("Failed to download NetCDF data: %s", e$message))
        }
    )
}

#' Get PM2.5 statistics for a region
#'
#' @description
#' Compute mean, SD, min, max, and pixel count of satellite PM2.5 for a
#' region defined by a GeoJSON file. Optionally group by a column in the
#' GeoJSON (e.g. district name) to return per-group statistics.
#'
#' @param geojson_file Character. Path to GeoJSON file defining the region.
#' @param year Integer. Year of the NetCDF data (e.g. \code{2023}).
#' @param month Optional integer (1--12). If NULL, uses annual data.
#' @param cache_dir Character. Directory to cache NetCDF files.
#'   Default: \code{"pm25_data"}.
#' @param group_by Optional character. Column name(s) in the GeoJSON to
#'   group polygons by (comma-separated for multiple columns).
#' @return List (or data frame if \code{group_by} is specified) with
#'   PM2.5 statistics: \code{mean}, \code{std}, \code{min}, \code{max},
#'   \code{count}.
#' @examples
#' \dontrun{
#' # Single region
#' stats <- pm25_get_stats("delhi.geojson", year = 2023, month = 11)
#' cat("Mean PM2.5:", round(stats$mean, 1), "ug/m3")
#'
#' # Grouped by district
#' stats_by_district <- pm25_get_stats(
#'   "delhi_districts.geojson",
#'   year     = 2023,
#'   month    = 11,
#'   group_by = "district_name"
#' )
#' }
#' @export
pm25_get_stats <- function(geojson_file, year, month = NULL,
                           cache_dir = "pm25_data", group_by = NULL) {
    if (!file.exists(geojson_file)) {
        stop(sprintf("GeoJSON file not found: %s", geojson_file))
    }

    nc_file <- pm25_download_netcdf(year, month, cache_dir = cache_dir)

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
            cat("Union failed, attempting fallback...\n")
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
#' @param cache_dir Character. Directory containing cached files.
#'   Default: \code{"pm25_data"}.
#' @return Character vector of cached file paths.
#' @examples
#' \dontrun{
#' files <- pm25_list_cached_files()
#' }
#' @export
pm25_list_cached_files <- function(cache_dir = "pm25_data") {
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
#' @param cache_dir Character. Directory containing cached files.
#'   Default: \code{"pm25_data"}.
#' @return Invisibly returns NULL.
#' @examples
#' \dontrun{
#' pm25_clear_cache()
#' }
#' @export
pm25_clear_cache <- function(cache_dir = "pm25_data") {
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
