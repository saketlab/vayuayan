#' PM25Client R6 Class
#'
#' @description
#' Client for processing PM2.5 satellite data from NetCDF files.
#'
#' @export
PM25Client <- R6::R6Class(
  "PM25Client",
  
  public = list(
    #' @field cache_dir Directory to cache downloaded NetCDF files
    cache_dir = NULL,
    
    #' @field aws_base_url AWS S3 base URL for WUSTL ACAG data
    aws_base_url = "https://s3.us-west-2.amazonaws.com/v6.gl.02.04/V6.GL.02.04/GL/",
    
    #' @description
    #' Initialize the PM25Client
    #' @param cache_dir Directory to cache NetCDF files (default: "pm25_data")
    #' @return A new PM25Client object
    initialize = function(cache_dir = "pm25_data") {
      self$cache_dir <- cache_dir
      
      if (!dir.exists(cache_dir)) {
        dir.create(cache_dir, recursive = TRUE)
      }
      
      invisible(self)
    },
    
    #' @description
    #' Download NetCDF file from AWS if not cached
    #' @param year Year for data
    #' @param month Optional month (1-12). If NULL, downloads annual data
    #' @param force_download Force re-download even if file exists
    #' @return Path to the downloaded NetCDF file
    download_netcdf_if_needed = function(year, month = NULL, force_download = FALSE) {
      filename <- private$get_aws_filename(year, month)
      cached_path <- file.path(self$cache_dir, filename)
      
      # Check if file exists and is valid
      if (file.exists(cached_path) && !force_download) {
        file_size <- file.info(cached_path)$size
        if (file_size > 1024 * 1024) {  # At least 1MB
          cli::cli_alert_info("Using cached file: {cached_path}")
          return(cached_path)
        } else {
          cli::cli_alert_warning("Cached file appears incomplete, re-downloading...")
        }
      }
      
      # Download from AWS
      aws_url <- private$get_aws_url(year, month)
      cli::cli_alert_info("Downloading PM2.5 data from AWS...")
      cli::cli_alert_info("Source: {aws_url}")
      cli::cli_alert_info("Destination: {cached_path}")
      
      tryCatch({
        # Download with progress
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
      }, error = function(e) {
        if (file.exists(cached_path)) {
          unlink(cached_path)
        }
        stop(sprintf("Failed to download NetCDF data: %s", e$message))
      })
    },
    
    #' @description
    #' Compute PM2.5 statistics for a region from GeoJSON
    #' @param geojson_file Path to GeoJSON file
    #' @param year Year of NetCDF data
    #' @param month Optional month of NetCDF data
    #' @param group_by Optional column name(s) to group polygons by
    #' @return Data frame or list with PM2.5 statistics
    get_pm25_stats = function(geojson_file, year, month = NULL, group_by = NULL) {
      if (!file.exists(geojson_file)) {
        stop(sprintf("GeoJSON file not found: %s", geojson_file))
      }
      
      # Download NetCDF file if needed
      nc_file <- self$download_netcdf_if_needed(year, month)
      
      # Read GeoJSON
      gdf <- sf::st_read(geojson_file, quiet = TRUE)
      gdf <- sf::st_transform(gdf, 4326)
      
      # If group_by specified, use grouped processing
      if (!is.null(group_by)) {
        group_cols <- strsplit(group_by, ",")[[1]]
        group_cols <- trimws(group_cols)
        
        # Validate columns exist
        missing_cols <- setdiff(group_cols, names(gdf))
        if (length(missing_cols) > 0) {
          stop(sprintf(
            "Column(s) %s not found in GeoJSON. Available columns: %s",
            paste(missing_cols, collapse = ", "),
            paste(names(gdf), collapse = ", ")
          ))
        }
        
        return(private$get_pm25_stats_grouped(gdf, nc_file, group_cols))
      }
      
      # Otherwise, process as combined polygon
      polygon <- sf::st_union(gdf)
      bbox <- sf::st_bbox(polygon)
      
      # Load and process NetCDF data
      pm25_raster <- terra::rast(nc_file)
      
      # Find PM2.5 variable
      var_names <- names(pm25_raster)
      pm25_var <- NULL
      if ("PM25" %in% var_names) {
        pm25_var <- "PM25"
      } else if ("GWRPM25" %in% var_names) {
        pm25_var <- "GWRPM25"
      } else {
        stop(sprintf(
          "PM2.5 variable not found. Available variables: %s",
          paste(var_names, collapse = ", ")
        ))
      }
      
      # Extract PM2.5 layer
      pm25_layer <- pm25_raster[[pm25_var]]
      
      # Crop to bounding box with buffer
      bbox_buffered <- sf::st_bbox(c(
        xmin = bbox$xmin - 0.1,
        ymin = bbox$ymin - 0.1,
        xmax = bbox$xmax + 0.1,
        ymax = bbox$ymax + 0.1
      ))
      
      pm25_cropped <- terra::crop(pm25_layer, terra::ext(bbox_buffered))
      
      # Mask to polygon
      polygon_vect <- terra::vect(polygon)
      pm25_masked <- terra::mask(pm25_cropped, polygon_vect)
      
      # Calculate statistics
      values <- terra::values(pm25_masked, na.rm = TRUE)
      values <- values[!is.na(values)]
      
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
    },
    
    #' @description
    #' List all cached NetCDF files
    #' @return Character vector of cached file paths
    list_cached_files = function() {
      if (!dir.exists(self$cache_dir)) {
        cli::cli_alert_info("Cache directory does not exist")
        return(character(0))
      }
      
      cached_files <- list.files(
        self$cache_dir,
        pattern = "\\.nc$",
        full.names = TRUE
      )
      
      if (length(cached_files) > 0) {
        cli::cli_alert_info("Cached files in {self$cache_dir}:")
        for (file in cached_files) {
          size_mb <- file.info(file)$size / (1024 * 1024)
          cli::cli_alert(
            "   {basename(file)} ({round(size_mb, 1)} MB)"
          )
        }
      } else {
        cli::cli_alert_info("No cached files in {self$cache_dir}")
      }
      
      return(cached_files)
    },
    
    #' @description
    #' Clear all cached NetCDF files
    clear_cache = function() {
      if (!dir.exists(self$cache_dir)) {
        cli::cli_alert_info("Cache directory does not exist")
        return(invisible(NULL))
      }
      
      cached_files <- list.files(
        self$cache_dir,
        pattern = "\\.nc$",
        full.names = TRUE
      )
      
      for (file in cached_files) {
        tryCatch({
          unlink(file)
          cli::cli_alert_success("Removed: {file}")
        }, error = function(e) {
          cli::cli_alert_warning("Could not remove {file}: {e$message}")
        })
      }
      
      cli::cli_alert_success("Cache cleared: {self$cache_dir}")
      invisible(NULL)
    }
  ),
  
  private = list(
    get_aws_filename = function(year, month = NULL) {
      if (is.null(month)) {
        return(sprintf("V6GL02.04.CNNPM25.GL.%d01-%d12.nc", year, year))
      }
      return(sprintf("V6GL02.04.CNNPM25.GL.%d%02d-%d%02d.nc", year, month, year, month))
    },
    
    get_aws_url = function(year, month = NULL) {
      filename <- private$get_aws_filename(year, month)
      if (is.null(month)) {
        return(paste0(self$aws_base_url, "Annual/", filename))
      }
      return(paste0(self$aws_base_url, "Monthly/", year, "/", filename))
    },
    
    get_pm25_stats_grouped = function(gdf, nc_file, group_cols) {
      bbox <- sf::st_bbox(gdf)
      
      # Load NetCDF
      pm25_raster <- terra::rast(nc_file)
      
      # Find PM2.5 variable
      var_names <- names(pm25_raster)
      pm25_var <- NULL
      if ("PM25" %in% var_names) {
        pm25_var <- "PM25"
      } else if ("GWRPM25" %in% var_names) {
        pm25_var <- "GWRPM25"
      } else {
        stop(sprintf(
          "PM2.5 variable not found. Available variables: %s",
          paste(var_names, collapse = ", ")
        ))
      }
      
      pm25_layer <- pm25_raster[[pm25_var]]
      
      # Crop to overall bounding box
      bbox_buffered <- sf::st_bbox(c(
        xmin = bbox$xmin - 0.1,
        ymin = bbox$ymin - 0.1,
        xmax = bbox$xmax + 0.1,
        ymax = bbox$ymax + 0.1
      ))
      
      pm25_cropped <- terra::crop(pm25_layer, terra::ext(bbox_buffered))
      
      # Group and process
      results <- list()
      
      gdf_grouped <- gdf %>%
        dplyr::group_by(across(all_of(group_cols))) %>%
        dplyr::group_split()
      
      for (group_gdf in gdf_grouped) {
        tryCatch({
          # Get group values
          group_vals <- group_gdf[1, group_cols, drop = FALSE]
          
          # Combine all polygons in group
          combined_geom <- sf::st_union(group_gdf)
          
          # Mask to geometry
          geom_vect <- terra::vect(combined_geom)
          pm25_masked <- terra::mask(pm25_cropped, geom_vect)
          
          # Calculate statistics
          values <- terra::values(pm25_masked, na.rm = TRUE)
          values <- values[!is.na(values)]
          
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
        }, error = function(e) {
          cli::cli_alert_warning("Error processing group: {e$message}")
        })
      }
      
      return(dplyr::bind_rows(results))
    }
  )
)
