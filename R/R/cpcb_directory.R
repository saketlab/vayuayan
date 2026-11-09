# station lookups: bundled directory snapshot plus the public RSS feed

.cpcb_cache <- new.env(parent = emptyenv())

# feed updates hourly; cache briefly so one call fetches it once
.cpcb_rss_ttl_mins <- 5

.cpcb_new_api <- function(path) {
  paste0(.cpcb_base_url, "/caaqms-common/dataRepository/", path)
}

# CPCB's certificate often breaks; send public-data requests unverified then
.cpcb_ssl_fallback <- function(request) {
  if (isTRUE(.cpcb_cache$insecure)) {
    return(httr::with_config(
      httr::config(ssl_verifypeer = 0L, ssl_verifyhost = 0L), request()
    ))
  }
  tryCatch(request(), error = function(e) {
    if (!grepl("SSL|TLS|certificate|SEC_E_", conditionMessage(e))) stop(e)
    cli::cli_alert_warning("SSL verification failed for CPCB; sending without verification")
    .cpcb_cache$insecure <- TRUE
    .cpcb_ssl_fallback(request)
  })
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
      cities[, c("city_code", "city_name", "state_name", "state_code")],
      by = "city_code"
    )
  }
  .cpcb_cache$stations
}

# TRUE where the name or code is the query; a feed station may have no code
.cpcb_place_matches <- function(query, name, code) {
  if (is.null(query) || !nzchar(query)) {
    return(rep(TRUE, length(name)))
  }
  tolower(name) %in% tolower(query) | tolower(code) %in% tolower(query)
}

# Live feed stations in the directory's columns; no rows when the feed is down
.cpcb_feed_stations <- function() {
  feed <- tryCatch(.cpcb_rss_stations(), error = function(e) {
    cli::cli_alert_info("CPCB live feed unavailable, using the station directory alone: {conditionMessage(e)}")
    NULL
  })
  known <- .cpcb_directory_stations()
  if (is.null(feed) || nrow(feed) == 0) {
    return(known[0, , drop = FALSE])
  }
  feed <- feed[!is.na(feed$id) & nzchar(feed$id) & !is.na(feed$name) & !duplicated(feed$id), , drop = FALSE]
  dir <- .cpcb_directory()
  cities <- do.call(rbind, dir$cities)
  city_row <- match(
    paste(tolower(feed$state), tolower(feed$city)),
    paste(tolower(cities$state_name), tolower(cities$city_name))
  )
  out <- data.frame(
    station_id = feed$id,
    station_name = feed$name,
    latitude = .to_numeric(feed$latitude),
    longitude = .to_numeric(feed$longitude),
    city_code = cities$city_code[city_row],
    city_name = feed$city,
    state_name = feed$state,
    state_code = dir$states$state_code[match(tolower(feed$state), tolower(dir$states$state_name))],
    stringsAsFactors = FALSE
  )
  out[names(known)]
}

# The directory plus the stations only the live feed knows
.cpcb_station_catalogue <- function() {
  known <- .cpcb_directory_stations()
  feed <- .cpcb_feed_stations()
  rbind(known, feed[!feed$station_id %in% known$station_id, , drop = FALSE])
}

#' Stations of the CPCB directory and live feed
#'
#' @description
#' One row per station, with its ID, name, city, state and coordinates: the
#' bundled directory plus the stations only the CPCB live feed knows. If the
#' feed is unavailable, the directory alone is used.
#'
#' @param state Optional state name or code.
#' @param city Optional city name or code. Every city of that name is included
#'   unless \code{state} is given.
#' @return Data frame with \code{station_id}, \code{station_name}, \code{city},
#'   \code{state}, \code{latitude} and \code{longitude}, sorted by state, city
#'   and station name. It has no rows if nothing matches.
#' @examplesIf interactive()
#' head(cpcb_station_table(city = "Delhi"))
#' @export
cpcb_station_table <- function(state = NULL, city = NULL) {
  stations <- .cpcb_station_catalogue()
  stations <- stations[
    .cpcb_place_matches(state, stations$state_name, stations$state_code) &
      .cpcb_place_matches(city, stations$city_name, stations$city_code), ,
    drop = FALSE
  ]
  out <- data.frame(
    station_id = stations$station_id,
    station_name = stations$station_name,
    city = stations$city_name,
    state = stations$state_name,
    latitude = .to_numeric(stations$latitude),
    longitude = .to_numeric(stations$longitude),
    stringsAsFactors = FALSE
  )
  out <- out[order(out$state, out$city, out$station_name, method = "radix"), ]
  rownames(out) <- NULL
  out
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
  # radix sorts in C-locale order whatever the session locale
  df <- unique(df[order(df$label, method = "radix"), , drop = FALSE])
  rownames(df) <- NULL
  df
}

.cpcb_resolve_state <- function(state) {
  .cpcb_match(.cpcb_directory()$states, state, c("state_name", "state_code"))
}

.cpcb_resolve_city <- function(city, state = "") {
  state <- state %||% ""
  dir <- .cpcb_directory()
  codes <- if (nzchar(state)) {
    .cpcb_resolve_state(state)$state_code
  } else {
    dir$states$state_code
  }
  hits <- lapply(codes, function(code) .cpcb_match(dir$cities[[code]], city, c("city_name", "city_code")))
  hits <- Filter(Negate(is.null), hits)
  if (length(hits) > 1) {
    .cpcb_abort_ambiguous_city(city, vapply(hits, function(h) h$state_name, ""))
  }
  if (length(hits) == 1) hits[[1]] else NULL
}

.cpcb_abort_ambiguous_city <- function(city, states) {
  states <- sort(states, method = "radix")
  .vayuayan_abort(
    "vayuayan_ambiguous",
    sprintf("City '%s' is in more than one state, give the state: %s", city, paste(states, collapse = "; ")),
    candidates = states
  )
}

# Exact ID or name, else a name containing `value`; several such names is an error.
.cpcb_find_station <- function(df, value, id_col, name_col) {
  hit <- .cpcb_match(df, value, c(id_col, name_col))
  if (!is.null(hit) || !is.data.frame(df) || is.null(value) || !nzchar(value)) {
    return(hit)
  }
  idx <- which(grepl(tolower(value), tolower(df[[name_col]]), fixed = TRUE))
  if (length(idx) > 1) {
    candidates <- sort(df[[name_col]][idx])
    .vayuayan_abort(
      "vayuayan_ambiguous",
      sprintf(
        "Station '%s' matches %d stations, be more specific: %s",
        value, length(idx), paste(utils::head(candidates, 8), collapse = "; ")
      ),
      candidates = candidates
    )
  }
  if (length(idx) == 0) NULL else df[idx, , drop = FALSE]
}

# city narrows the search and state narrows the city, as in Python
.cpcb_resolve_station <- function(station_id, station_name = "", city = NULL, state = NULL) {
  city <- city %||% ""
  state <- state %||% ""
  # raises for a city in several states before anything is searched
  if (nzchar(city)) .cpcb_resolve_city(city, state)
  in_place <- function(st) {
    if (!nzchar(city)) {
      return(st)
    }
    st[
      .cpcb_place_matches(city, st$city_name, st$city_code) &
        .cpcb_place_matches(state, st$state_name, st$state_code), ,
      drop = FALSE
    ]
  }
  known <- in_place(.cpcb_directory_stations())
  catalogue <- NULL
  hit <- NULL
  for (query in c(station_id, station_name)) {
    if (!nzchar(query)) next
    # an exact directory hit needs no feed; a partial name must see both sources
    hit <- .cpcb_match(known, query, c("station_id", "station_name"))
    if (is.null(hit)) {
      if (is.null(catalogue)) catalogue <- in_place(.cpcb_station_catalogue())
      hit <- .cpcb_find_station(catalogue, query, "station_id", "station_name")
    }
    if (!is.null(hit)) break
  }
  if (is.null(hit)) {
    return(NULL)
  }
  list(
    station_id = hit$station_id,
    station_name = hit$station_name,
    state = hit$state_name,
    city = hit$city_name
  )
}

.cpcb_require_station <- function(station, city = NULL, state = NULL) {
  .cpcb_resolve_station(station, city = city, state = state) %||%
    .vayuayan_abort("vayuayan_not_found", sprintf("Station '%s' not found", station))
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

  response <- .cpcb_get(
    paste0(.cpcb_base_url, "/caaqms/iit_rss_feed_with_coordinates"),
    httr::user_agent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    ),
    httr::timeout(30)
  )
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
  out <- .cpcb_sort_cities(out)

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
  stations <- if (length(cities$stationsInCity) > 0) {
    do.call(rbind, cities$stationsInCity)
  } else {
    .cpcb_rss_station_frame(data.frame(siteId = character()))
  }
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

# Repository files of past years are cached; either cache may hold them
.cpcb_read_repository <- function(filepath, n_max = Inf) {
  name <- .cpcb_cache_name(filepath)
  path <- if (!is.null(name)) {
    .cache_lookup(c(vayuayan_cache_dir(), .python_cache_dir()), name)
  }
  if (!is.null(path) && !.cpcb_usable_file(path)) {
    path <- NULL
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

# CPCB often times out on one request, so every call retries
.cpcb_request <- function(verb, url, ..., terminate_on, times) {
  .cpcb_ssl_fallback(function() {
    httr::RETRY(
      verb, url, ...,
      times = times, pause_base = 1, pause_cap = 8, terminate_on = terminate_on, quiet = TRUE
    )
  })
}

# 4xx is not retried
.cpcb_get <- function(url, ..., times = 4) {
  res <- .cpcb_request("GET", url, ..., terminate_on = 400:499, times = times)
  httr::stop_for_status(res)
  res
}

# 404 is no such file and anything else is the network's, decided here for token and download
.cpcb_repository_step <- function(step) {
  tryCatch(step(), error = function(e) {
    if (inherits(e, c("vayuayan_network", "vayuayan_data_not_found"))) stop(e)
    class <- if (inherits(e, "http_404")) "vayuayan_data_not_found" else "vayuayan_network"
    .vayuayan_abort(class, conditionMessage(e), parent = e)
  })
}

# token is already URL-encoded; re-encoding it gets HTTP 400
.cpcb_download_url <- function(filepath, ...) {
  .cpcb_repository_step(function() {
    res <- .cpcb_get(
      .cpcb_new_api("get-download-link"),
      query = list(file_name = filepath),
      httr::timeout(30),
      ...
    )
    token <- trimws(httr::content(res, as = "text", encoding = "UTF-8"))
    if (!grepl("^[A-Za-z0-9%+/=_-]+$", token)) {
      stop("CPCB sent no download token for ", filepath, call. = FALSE)
    }
    paste0(.cpcb_new_api("download-excel-fileEnc"), "?file_name=", token)
  })
}

# an error page must not reach the cache
.cpcb_usable_file <- function(path) {
  if (!file.exists(path)) {
    return(FALSE)
  }
  bytes <- readBin(path, "raw", 256L)
  bytes <- bytes[!bytes %in% charToRaw(" \t\r\n")]
  length(bytes) > 0 && !bytes[1] %in% charToRaw("<{")
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
  .cpcb_repository_step(function() {
    .cpcb_get(
      .cpcb_download_url(filepath),
      httr::write_disk(partial, overwrite = TRUE),
      httr::timeout(120)
    )
    if (!.cpcb_usable_file(partial)) {
      stop("CPCB sent no usable file for ", filepath, call. = FALSE)
    }
  })
  file.rename(partial, dest)
  dest
}

# failures fall through to the sequential download, which reports them
.cpcb_prefetch <- function(filepaths) {
  names <- vapply(filepaths, function(f) .cpcb_cache_name(f) %||% NA_character_, "",
    USE.NAMES = FALSE
  )
  roots <- c(vayuayan_cache_dir(), .python_cache_dir())
  todo <- !is.na(names) & !duplicated(names)
  todo[todo] <- vapply(names[todo], function(n) is.null(.cache_lookup(roots, n)), TRUE)
  if (sum(todo) < 2) {
    return(invisible())
  }
  files <- filepaths[todo]
  urls <- rep(NA_character_, length(files))
  for (i in seq_along(files)) {
    urls[i] <- tryCatch(.cpcb_download_url(files[i], times = 1), error = function(e) NA_character_)
    if (is.na(urls[i])) break # an outage must not cost a timeout per file
  }
  todo[todo] <- !is.na(urls)
  urls <- urls[!is.na(urls)]
  if (!any(todo)) {
    return(invisible())
  }
  dest <- file.path(vayuayan_cache_dir(), names[todo])
  for (dir in unique(dirname(dest))) dir.create(dir, recursive = TRUE, showWarnings = FALSE)
  part <- paste0(dest, ".part")
  insecure <- isTRUE(.cpcb_cache$insecure)
  res <- curl::multi_download(
    urls, part,
    progress = FALSE, timeout = 120,
    ssl_verifypeer = if (insecure) 0L else 1L,
    ssl_verifyhost = if (insecure) 0L else 2L
  )
  ok <- res$success %in% TRUE & res$status_code %in% 200 &
    vapply(part, .cpcb_usable_file, TRUE, USE.NAMES = FALSE)
  file.rename(part[ok], dest[ok])
  unlink(part[!ok])
  invisible()
}

.cpcb_save_year <- function(data_files, year, save_location, what) {
  for (entry in data_files) {
    if (identical(as.character(entry[["year"]]), as.character(year)) && !is.null(entry[["filepath"]])) {
      df <- .cpcb_read_repository(entry[["filepath"]], n_max = 31)
      return(.cpcb_save(df, save_location))
    }
  }
  .vayuayan_abort("vayuayan_data_not_found", sprintf("Data not found for %s in year %s", what, year))
}

# Cities by share of live stations, then name (any case); stations live
# first, then by name.
.cpcb_sort_cities <- function(cities) {
  if (is.null(cities) || nrow(cities) == 0) {
    return(cities)
  }
  cities$stationsInCity <- lapply(cities$stationsInCity, function(st) {
    st[order(!st$live, st$name, method = "radix"), , drop = FALSE]
  })
  live_share <- vapply(cities$stationsInCity, function(st) mean(st$live), numeric(1))
  cities <- cities[order(-live_share, tolower(cities$cityName), method = "radix"), , drop = FALSE]
  rownames(cities) <- NULL
  cities
}
