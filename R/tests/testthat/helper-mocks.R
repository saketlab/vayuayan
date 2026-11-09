# Offline plumbing for the CPCB, OAQ and PM2.5 tests.

# The condition httr::stop_for_status() raises for a missing file.
http_404_error <- function() {
  structure(
    class = c("http_404", "http_400", "http_error", "error", "condition"),
    list(message = "Not Found (HTTP 404).", call = NULL)
  )
}

CPCB_REPO <- "https://airquality.cpcb.gov.in/caaqms-common/dataRepository/"
CPCB_FEED <- "https://airquality.cpcb.gov.in/caaqms/iit_rss_feed_with_coordinates"

# An httr response as the real client returns it, so that the real
# httr::content() and httr::stop_for_status() run against it.
fake_response <- function(status = 200L, body = "") {
  structure(
    list(
      url = "https://example.invalid/", status_code = as.integer(status),
      headers = httr::insensitive(list(`content-type` = "application/json")),
      all_headers = list(), cookies = data.frame(),
      content = if (is.raw(body)) body else charToRaw(enc2utf8(body)),
      date = Sys.time(), times = numeric(), request = NULL, handle = NULL
    ),
    class = "response"
  )
}

# Replace httr's verbs with a queue of responses and record each request. An
# error object in the queue is raised, as a failed connection would be. A
# request beyond the queue fails the test, so nothing reaches the network.
local_http <- function(..., .env = parent.frame()) {
  queue <- list(...)
  log <- new.env(parent = emptyenv())
  log$calls <- list()
  respond <- function(method, url, args) {
    configs <- Filter(function(a) inherits(a, "request"), args)
    options <- do.call(c, lapply(configs, function(a) a$options))
    disk <- Filter(function(a) inherits(a$output, "write_disk"), configs)
    session <- getOption("httr_config")$options
    log$calls[[length(log$calls) + 1]] <- list(
      method = method, url = url,
      final = if (!is.null(args$query)) httr::modify_url(url, query = args$query) else url,
      query = args$query, body = args$body, encode = args$encode, args = args,
      options = options,
      headers = do.call(c, lapply(configs, function(a) a$headers)),
      path = if (length(disk) > 0) disk[[1]]$output$path,
      ssl_verifypeer = session$ssl_verifypeer, ssl_verifyhost = session$ssl_verifyhost
    )
    if (length(queue) == 0) {
      stop("Unexpected request: ", method, " ", url, call. = FALSE)
    }
    reply <- queue[[1]]
    queue <<- queue[-1]
    if (inherits(reply, "condition")) stop(reply)
    if (length(disk) > 0) writeBin(reply$content, disk[[1]]$output$path)
    reply
  }
  testthat::local_mocked_bindings(
    GET = function(url, ...) respond("GET", url, list(...)),
    POST = function(url, ...) respond("POST", url, list(...)),
    RETRY = function(verb, url, ...) respond(verb, url, list(...)),
    .package = "httr", .env = .env
  )
  log
}

# The body CPCB answers get-download-link with
token_reply <- function(token = "tok") fake_response(200, token)

# A failed connection, as curl reports one
connection_error <- function(message = "Could not resolve host: airquality.cpcb.gov.in") {
  structure(
    class = c("curl_error_couldnt_resolve_host", "curl_error", "error", "condition"),
    list(message = message, call = NULL)
  )
}

# Parsed once here, so each local_cpcb() need not read the JSON again
cpcb_bundled_directory <- jsonlite::fromJSON(system.file(
  "extdata", "cpcb_station_directory.json",
  package = "vayuayan"
))

# A fresh .cpcb_cache (TLS flag, RSS) holding the bundled directory, and
# temporary cache roots for one test. Returns the cache root.
local_cpcb <- function(.env = parent.frame()) {
  dir <- tempfile("vayuayan-cache-")
  python <- tempfile("vayuayan-python-")
  cache <- new.env(parent = emptyenv())
  cache$directory <- cpcb_bundled_directory
  testthat::local_mocked_bindings(
    .cpcb_cache = cache,
    vayuayan_cache_dir = function() dir,
    .python_cache_dir = function() python,
    .env = .env
  )
  dir
}

# No live feed, without using up a response queued for a later request
local_no_feed <- function(.env = parent.frame()) {
  testthat::local_mocked_bindings(
    .cpcb_feed_stations = function() .cpcb_directory_stations()[0, , drop = FALSE],
    .env = .env
  )
}

# JSON body of a file-path listing whose entries are the columns in ...
file_listing <- function(...) {
  file_path_json(data.frame(..., stringsAsFactors = FALSE))
}

# Replace curl::multi_download; statuses[i] is what the i-th file gets
local_multi_download <- function(statuses, .env = parent.frame()) {
  log <- new.env(parent = emptyenv())
  testthat::local_mocked_bindings(
    multi_download = function(urls, destfiles, ...) {
      log$urls <- urls
      log$destfiles <- destfiles
      log$args <- list(...)
      file.create(destfiles)
      for (f in destfiles) writeLines("Day,January\n1,10", f)
      data.frame(
        success = statuses == 200, status_code = statuses,
        stringsAsFactors = FALSE
      )
    },
    .package = "curl", .env = .env
  )
  log
}

# Answers handles in order with list(status_code, content); NULL fails the transfer
local_curl_pool <- function(replies = list(), .env = parent.frame()) {
  log <- new.env(parent = emptyenv())
  log$pools <- list()
  log$handles <- list()
  log$added <- list()
  testthat::local_mocked_bindings(
    new_pool = function(...) {
      log$pools[[length(log$pools) + 1]] <- list(...)
      "pool"
    },
    new_handle = function(url = NULL, ...) {
      handle <- new.env(parent = emptyenv())
      handle$url <- url
      log$handles[[length(log$handles) + 1]] <- handle
      handle
    },
    handle_setopt = function(handle, ...) {
      handle$options <- list(...)
      invisible(handle)
    },
    handle_setheaders = function(handle, ...) {
      handle$headers <- list(...)
      invisible(handle)
    },
    multi_add = function(handle, done = NULL, fail = NULL, pool = NULL, ...) {
      log$added[[length(log$added) + 1]] <- list(handle = handle, done = done, fail = fail)
      invisible(handle)
    },
    multi_run = function(pool = NULL, ...) {
      for (i in seq_along(log$added)) {
        added <- log$added[[i]]
        reply <- if (i <= length(replies)) replies[[i]]
        if (is.null(reply)) added$fail("Timeout was reached") else added$done(reply)
      }
      invisible(list(success = length(log$added), error = 0L, pending = 0L))
    },
    .package = "curl", .env = .env
  )
  log
}

# Shape of CPCB's live feed: one live and one offline station in Delhi, one
# station in Mumbai, a city with no stations and a state with no cities
cpcb_feed_json <- function() {
  '{"country": [
    {"stateId": "Delhi", "citiesInState": [
      {"cityId": "Delhi", "stationsInCity": [
        {"siteId": "site_feedonly", "stationName": "Zeta Colony, Delhi - DPCC",
         "latitude": "28.70", "longitude": "77.10", "lastUpdate": "",
         "airQualityIndexValue": "NA", "pollutants": []},
        {"siteId": "site_301", "stationName": "Anand Vihar, Delhi - DPCC",
         "latitude": "28.6476", "longitude": "77.3158",
         "lastUpdate": "28-06-2026 18:00:00", "airQualityIndexValue": "180",
         "pollutants": [
           {"indexId": "PM2.5", "avg": "40", "min": "17", "max": "65"},
           {"indexId": "PM10", "avg": "56", "min": "24", "max": "102"}
         ]}
      ]}
    ]},
    {"stateId": "Maharashtra", "citiesInState": [
      {"cityId": "Mumbai", "stationsInCity": [
        {"siteId": "site_5392", "stationName": "Bandra Kurla Complex, Mumbai - IITM",
         "latitude": "19.0535", "longitude": "72.8464",
         "lastUpdate": "28-06-2026 18:00:00", "airQualityIndexValue": "95",
         "pollutants": [{"indexId": "PM2.5", "avg": "30", "min": "10", "max": "50"}]}
      ]},
      {"cityId": "Empty City", "stationsInCity": []}
    ]},
    {"stateId": "Ghost", "citiesInState": []}
  ]}'
}

# A feed response followed by whatever else the test expects
local_feed <- function(..., .env = parent.frame()) {
  local_http(fake_response(200, cpcb_feed_json()), ..., .env = .env)
}

# JSON body of CPCB's file-path endpoint
file_path_json <- function(data) {
  as.character(jsonlite::toJSON(
    list(status = "success", data = data),
    auto_unbox = TRUE, dataframe = "rows"
  ))
}

# A 4 x 3 NetCDF grid over 76.9-77.2 E, 28.5-28.7 N: 10 in the west half, 30
# in the east. values = NA leaves the grid empty.
write_pm25_nc <- function(path, var = "PM25", values = rep(c(10, 10, 30, 30), 3)) {
  lon <- ncdf4::ncdim_def("lon", "degrees_east", c(76.9, 77.0, 77.1, 77.2))
  lat <- ncdf4::ncdim_def("lat", "degrees_north", c(28.5, 28.6, 28.7))
  v <- ncdf4::ncvar_def(var, "ug/m3", list(lon, lat), -9999)
  nc <- ncdf4::nc_create(path, v)
  ncdf4::ncvar_put(nc, v, matrix(values, 4, 3))
  ncdf4::nc_close(nc)
  path
}

# Long rows, one constant value per pollutant; ... adds columns such as station_id
long_of <- function(hours, values, ...) {
  data.frame(
    ...,
    timestamp = rep(hours, length(values)),
    pollutant = rep(names(values), each = length(hours)),
    value = rep(unname(values), each = length(hours)),
    stringsAsFactors = FALSE
  )
}

long_hours <- function(hours, values) long_of(hours, values, station_id = "site_1", unit = "ug/m3")

# Rectangle as an sfc polygon in lon/lat
lonlat_box <- function(xmin, xmax, ymin, ymax) {
  sf::st_sfc(sf::st_polygon(list(rbind(
    c(xmin, ymin), c(xmax, ymin), c(xmax, ymax), c(xmin, ymax), c(xmin, ymin)
  ))), crs = 4326)
}
