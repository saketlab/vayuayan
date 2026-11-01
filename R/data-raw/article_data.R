pkgload::load_all()

year <- 2022
metro <- c(
  "Delhi", "Mumbai", "Kolkata", "Chennai", "Bengaluru",
  "Surat", "Kanpur", "Jaipur", "Lucknow", "Pune", "Ahmedabad", "Hyderabad"
)
station_dirs <- c(Delhi = "station_data", Mumbai = "station_data_mumbai")

cpcb_city_daily(metro, year, cache_dir = "vignettes/data/metro")
for (city in names(station_dirs)) {
  cpcb_city_daily(city, year, cache_dir = file.path("vignettes/data", tolower(city)))
  cpcb_station_daily(
    cpcb_get_station_list(city)$value, year,
    cache_dir = file.path("vignettes", station_dirs[[city]])
  )
}

diurnal <- "vignettes/data/diurnal/raw_pm25_2023.csv"
if (!file.exists(diurnal)) {
  raw <- cpcb_raw_readings(c("site_5112", "site_1558"), 2023, "PM2.5")
  stopifnot(nrow(raw) > 0)
  dir.create(dirname(diurnal), recursive = TRUE, showWarnings = FALSE)
  utils::write.csv(transform(raw, timestamp = format(timestamp, "%Y-%m-%d %H:%M:%S")), diurnal, row.names = FALSE)
}

files <- c(
  diurnal,
  file.path("vignettes/data/metro", sprintf("%s_aqi_%s.csv", tolower(metro), year)),
  file.path("vignettes/data", tolower(names(station_dirs)), sprintf("%s_aqi_%s.csv", tolower(names(station_dirs)), year)),
  list.files(file.path("vignettes", station_dirs), sprintf("_%s\\.csv$", year), full.names = TRUE)
)
stopifnot(all(file.exists(files)))
utils::tar("article-data.tar.gz", files, compression = "gzip", tar = "internal")
cli::cli_alert_success("Wrote article-data.tar.gz ({length(files)} files)")
