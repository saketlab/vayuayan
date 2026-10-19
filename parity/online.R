# Online parity cases of the R package; parity/test_online.py runs the same
# cases in Python and compares. Usage, from the repo root:
#   Rscript parity/online.R <out.json> <cache_dir> <polygon.geojson>

args <- commandArgs(trailingOnly = TRUE)
out_path <- args[1]
cache <- args[2]
polygon <- args[3]
pkgload::load_all("R", quiet = TRUE)
options(vayuayan.cache_dir = file.path(cache, "root"))

# Data frames as columns, times as text, so both languages compare as JSON
norm <- function(x) {
  if (is.data.frame(x)) {
    return(lapply(as.list(x), norm))
  }
  if (inherits(x, "POSIXt")) {
    return(format(x, "%Y-%m-%d %H:%M:%S", tz = "UTC"))
  }
  if (inherits(x, "Date") || is.factor(x)) {
    return(as.character(x))
  }
  if (is.list(x)) {
    return(lapply(x, norm))
  }
  x
}

coords <- c(28.61, 77.21)
pm25_dir <- file.path(cache, "pm25")
cases <- list(
  state_list = function() cpcb_get_state_list(),
  city_list = function() cpcb_get_city_list("Maharashtra"),
  station_list = function() cpcb_get_station_list("Delhi"),
  add_coords = function() cpcb_add_coords(cpcb_get_station_list("Delhi")),
  file_path_station = function() {
    cpcb_get_file_path(
      station_id = "site_301", year = "2023", frequency = "daily",
      data_type = "stationLevel"
    )
  },
  file_path_city = function() {
    cpcb_get_file_path(city = "Delhi", frequency = "daily", data_type = "cityLevel")
  },
  city_daily = function() cpcb_city_daily("Delhi", 2023, cache_dir = file.path(cache, "csv")),
  station_daily = function() {
    cpcb_station_daily("site_301", 2023, cache_dir = file.path(cache, "csv"))
  },
  station_daily_aqi = function() cpcb_station_daily_aqi("site_301", 2023),
  raw_station = function() {
    cpcb_download_raw_station_data("site_301", 2023, tidy = TRUE)
  },
  hourly_city = function() cpcb_download_hourly_city_data("Delhi", 2023, month = "January"),
  hourly_station = function() {
    cpcb_download_hourly_station_data("site_301", 2023, month = "January")
  },
  nearest_station = function() cpcb_get_nearest_station(coords),
  nearest_stations = function() {
    cpcb_get_nearest_stations(coords, k = 5)[c("station_id", "station_name", "distance_km")]
  },
  nearest_within_radius = function() {
    unname(as.list(cpcb_get_nearest_stations(coords, k = 1, max_distance_km = 3)[
      1, c("station_id", "distance_km")
    ]))
  },
  all_india = function() stations_to_dataframe(cpcb_get_all_india()),
  live_station = function() {
    data <- cpcb_get_live_aqi_data_for_station("site_301")
    list(
      station_id = data$station_id, station_name = data$station_name,
      metrics = cpcb_live_metrics(data)
    )
  },
  india_boundary = function() as.numeric(sf::st_bbox(india_boundary(state = "Delhi"))),
  pm25_point = function() pm25_get_point(coords[1], coords[2], 2020, region = "AS", cache_dir = pm25_dir),
  pm25_point_monthly = function() {
    pm25_get_point(coords[1], coords[2], 2020, month = 1, region = "AS", cache_dir = pm25_dir)
  },
  pm25_stats = function() pm25_get_stats(polygon, 2020, region = "AS", cache_dir = pm25_dir)
)
if (nzchar(Sys.getenv("OAQ_API_KEY"))) {
  cases$oaq_providers <- function() oaq_list_providers(oaq_session())
  cases$oaq_stations <- function() oaq_stations_table(oaq_session(), "cpcb")
  cases$oaq_tally <- function() oaq_city_tally(oaq_sensors(oaq_session()))
  cases$oaq_check_records <- function() {
    oaq_check_daily_records(oaq_session(), "cpcb", "164", c("2026-05-29", "2026-05-30"))
  }
  cases$oaq_readings <- function() {
    oaq_readings(oaq_session(), "airnet", "12036", c("2026-09-14", "2026-09-15"))
  }
  cases$oaq_daily_means <- function() {
    oaq_daily_means(oaq_session(), "airnet", "12032", c("2026-09-14", "2026-09-15"))
  }
}

# PARITY_ONLY=oaq_ (comma-separated name prefixes) runs some cases only
only <- strsplit(Sys.getenv("PARITY_ONLY"), ",", fixed = TRUE)[[1]]
if (length(only)) {
  cases <- cases[Reduce(`|`, lapply(only, function(p) startsWith(names(cases), p)))]
}

results <- lapply(names(cases), function(name) {
  message("R: ", name)
  tryCatch(
    list(value = norm(cases[[name]]())),
    error = function(e) list(error = conditionMessage(e))
  )
})
names(results) <- names(cases)
jsonlite::write_json(
  results, out_path,
  auto_unbox = TRUE, digits = NA, null = "null", na = "null"
)
