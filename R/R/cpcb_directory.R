# station lookups: bundled directory snapshot plus the public RSS feed

.cpcb_cache <- new.env(parent = emptyenv())

# feed updates hourly; cache briefly so one call fetches it once
.cpcb_rss_ttl_mins <- 5

.cpcb_new_api <- function(path) {
  paste0(.cpcb_base_url, "/caaqms-common/dataRepository/", path)
}

# list(states = df, cities = list(state_code -> df), stations = list(city_code -> df))
.cpcb_directory <- function() {
  if (is.null(.cpcb_cache$directory)) {
    path <- system.file(
      "extdata", "cpcb_station_directory.json",
      package = "vayuayan"
    )
    .cpcb_cache$directory <- jsonlite::fromJSON(path)
  }
  .cpcb_cache$directory
}

# names come from cities; station rows spell some states differently
.cpcb_directory_stations <- function() {
  if (is.null(.cpcb_cache$stations)) {
    dir <- .cpcb_directory()
    cities <- do.call(rbind, dir$cities)
    stations <- do.call(rbind, Filter(is.data.frame, dir$stations))
    stations <- stations[, c("station_id", "station_name", "latitude", "longitude", "city_code")]
    .cpcb_cache$stations <- merge(
      stations,
      cities[, c("city_code", "city_name", "state_name")],
      by = "city_code"
    )
  }
  .cpcb_cache$stations
}

.cpcb_match <- function(df, value, cols) {
  if (!is.data.frame(df) || is.null(value) || !nzchar(value)) {
    return(NULL)
  }
  hit <- Reduce(`|`, lapply(cols, function(col) {
    !is.na(df[[col]]) & tolower(df[[col]]) == tolower(value)
  }))
  idx <- which(hit)
  if (length(idx) == 0) {
    return(NULL)
  }
  df[idx[1], , drop = FALSE]
}

# CPCB dropdown shape
.cpcb_dropdown <- function(label, value = label) {
  df <- data.frame(label = label, value = value, stringsAsFactors = FALSE)
  df <- unique(df[order(df$label), , drop = FALSE])
  rownames(df) <- NULL
  df
}

.cpcb_resolve_state <- function(state) {
  .cpcb_match(.cpcb_directory()$states, state, c("state_name", "state_code"))
}

.cpcb_resolve_city <- function(city, state = "") {
  dir <- .cpcb_directory()
  codes <- if (nzchar(state)) {
    .cpcb_resolve_state(state)$state_code
  } else {
    dir$states$state_code
  }
  for (code in codes) {
    hit <- .cpcb_match(dir$cities[[code]], city, c("city_name", "city_code"))
    if (!is.null(hit)) {
      return(hit)
    }
  }
  NULL
}

# Exact ID or name, else a name containing `value`; several such names is an error.
.cpcb_find_station <- function(df, value, id_col, name_col) {
  hit <- .cpcb_match(df, value, c(id_col, name_col))
  if (!is.null(hit) || !is.data.frame(df) || is.null(value) || !nzchar(value)) {
    return(hit)
  }
  idx <- which(grepl(tolower(value), tolower(df[[name_col]]), fixed = TRUE))
  if (length(idx) > 1) {
    stop(sprintf(
      "Station '%s' matches %d stations, be more specific: %s",
      value, length(idx), paste(utils::head(sort(df[[name_col]][idx]), 8), collapse = "; ")
    ), call. = FALSE)
  }
  if (length(idx) == 0) NULL else df[idx, , drop = FALSE]
}

# feed covers stations newer than the snapshot
.cpcb_resolve_station <- function(station_id, station_name = "") {
  st <- .cpcb_directory_stations()
  hit <- .cpcb_find_station(st, station_id, "station_id", "station_name") %||%
    .cpcb_find_station(st, station_name, "station_id", "station_name")
  if (!is.null(hit)) {
    return(list(
      station_id = hit$station_id,
      station_name = hit$station_name,
      state = hit$state_name,
      city = hit$city_name
    ))
  }

  rss <- tryCatch(.cpcb_rss_stations(), error = function(e) NULL)
  hit <- .cpcb_find_station(rss, station_id, "id", "name") %||%
    .cpcb_find_station(rss, station_name, "id", "name")
  if (is.null(hit)) {
    return(NULL)
  }
  list(
    station_id = hit$id,
    station_name = hit$name,
    state = hit$state,
    city = hit$city
  )
}

.cpcb_require_station <- function(station) {
  .cpcb_resolve_station(station) %||%
    stop(sprintf("Station '%s' not found", station), call. = FALSE)
}

.cpcb_col <- function(df, name, default = NA) {
  if (name %in% names(df)) df[[name]] else rep(default, nrow(df))
}

.cpcb_rss_cities <- function() {
  cached <- .cpcb_cache$rss
  if (!is.null(cached) &&
    difftime(Sys.time(), cached$time, units = "mins") < .cpcb_rss_ttl_mins) {
    return(cached$cities)
  }

  response <- httr::GET(
    paste0(.cpcb_base_url, "/caaqms/iit_rss_feed_with_coordinates"),
    httr::user_agent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    ),
    httr::timeout(30)
  )
  httr::stop_for_status(response)
  feed <- jsonlite::fromJSON(
    httr::content(response, as = "text", encoding = "UTF-8")
  )

  per_state <- lapply(seq_len(NROW(feed$country)), function(i) {
    cities <- feed$country$citiesInState[[i]]
    keep <- vapply(cities$stationsInCity, NROW, integer(1)) > 0
    if (!any(keep)) {
      return(NULL)
    }
    out <- data.frame(
      cityName = cities$cityId[keep],
      # cityID duplicates cityName; existing callers read it
      cityID = cities$cityId[keep],
      stateID = feed$country$stateId[i],
      stringsAsFactors = FALSE
    )
    out$stationsInCity <- lapply(cities$stationsInCity[keep], .cpcb_rss_station_frame)
    out
  })
  out <- do.call(rbind, per_state)

  .cpcb_cache$rss <- list(time = Sys.time(), cities = out)
  out
}

.cpcb_rss_station_frame <- function(st) {
  last_update <- .cpcb_col(st, "lastUpdate", "")
  out <- data.frame(
    id = .cpcb_col(st, "siteId"),
    name = .cpcb_col(st, "stationName"),
    latitude = .cpcb_col(st, "latitude"),
    longitude = .cpcb_col(st, "longitude"),
    live = !is.na(last_update) & nzchar(last_update),
    avg = .cpcb_col(st, "airQualityIndexValue"),
    lastUpdate = last_update,
    stringsAsFactors = FALSE
  )
  out$pollutants <- .cpcb_col(st, "pollutants", list(NULL))
  out
}

.cpcb_rss_stations <- function() {
  cities <- .cpcb_rss_cities()
  stations <- do.call(rbind, cities$stationsInCity)
  n <- vapply(cities$stationsInCity, nrow, integer(1))
  stations$city <- rep(cities$cityName, n)
  stations$state <- rep(cities$stateID, n)
  stations
}

.cpcb_normalize_frequency <- function(frequency) {
  map <- c(
    hourly = "1H", "1_hour" = "1H", "1h" = "1H",
    daily = "1D", "24_hours" = "1D", "24h" = "1D", "1d" = "1D",
    monthly = "1M", "1m" = "1M",
    "15_minute" = "15M", "15m" = "15M"
  )
  out <- unname(map[tolower(frequency)])
  if (is.na(out)) frequency else out
}

# Repository files of past years are cached like the Python package does
.cpcb_read_repository <- function(filepath, n_max = Inf) {
  name <- .cpcb_cache_name(filepath)
  path <- if (!is.null(name)) {
    .cache_lookup(c(vayuayan_cache_dir(), .python_cache_dir()), name)
  }
  if (is.null(path)) {
    path <- .cpcb_download_repository(filepath, name)
    if (is.null(name)) on.exit(unlink(path))
  }
  if (tolower(tools::file_ext(filepath)) == "csv") {
    utils::read.csv(path,
      check.names = FALSE, fileEncoding = "UTF-8",
      nrows = if (is.finite(n_max)) n_max else -1
    )
  } else {
    as.data.frame(readxl::read_excel(path, n_max = n_max))
  }
}

# Download to the cache when name is given, else to a temporary file.
.cpcb_download_repository <- function(filepath, name = NULL) {
  dest <- if (is.null(name)) {
    tempfile(fileext = paste0(".", tools::file_ext(filepath)))
  } else {
    file.path(vayuayan_cache_dir(), name)
  }
  dir.create(dirname(dest), recursive = TRUE, showWarnings = FALSE)
  partial <- paste0(dest, ".part")
  on.exit(unlink(partial))
  res <- httr::GET(
    .cpcb_new_api("download-excel-file"),
    query = list(file_name = filepath),
    httr::write_disk(partial, overwrite = TRUE),
    httr::timeout(120)
  )
  httr::stop_for_status(res)
  file.rename(partial, dest)
  dest
}

.cpcb_save_year <- function(data_files, year, save_location, what) {
  for (entry in data_files) {
    if (isTRUE(entry$year == year)) {
      df <- .cpcb_read_repository(entry$filePath, n_max = 31)
      utils::write.csv(df, file = save_location, row.names = FALSE)
      cli::cli_alert_success("Saved {what} {year} to {save_location}")
      return(utils::head(df))
    }
  }
  stop(sprintf("Data not found for %s in year %s", what, year), call. = FALSE)
}
