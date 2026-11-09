test_that(".cpcb_match needs a data frame and a value, and takes the first hit", {
  df <- data.frame(id = c("a", "b", "b"), name = c("X", NA, "Z"))
  expect_null(.cpcb_match(list(), "a", "id"))
  expect_null(.cpcb_match(df, NULL, "id"))
  expect_null(.cpcb_match(df, "", "id"))
  expect_null(.cpcb_match(df, "missing", c("id", "name")))
  expect_equal(.cpcb_match(df, "A", "id")$name, "X")
  expect_equal(.cpcb_match(df, "b", c("id", "name"))$name, NA_character_)
  expect_equal(.cpcb_match(df, "z", c("id", "name"))$id, "b")
})

test_that(".cpcb_dropdown sorts in C-locale order and removes duplicates", {
  out <- .cpcb_dropdown(c("b", "Z", "a", "a"), c("2", "3", "1", "1"))
  expect_named(out, c("label", "value"))
  expect_equal(out$label, c("Z", "a", "b"))
  expect_equal(out$value, c("3", "1", "2"))
  expect_equal(rownames(out), c("1", "2", "3"))
  expect_equal(.cpcb_dropdown("only")$value, "only")
})

test_that(".cpcb_find_station prefers an exact hit, then a single partial name", {
  df <- data.frame(
    id = c("s1", "s2", "s3"),
    name = c("Anand Vihar, Delhi", "Anand Nagar, Pune", "ITO, Delhi")
  )
  expect_equal(.cpcb_find_station(df, "S3", "id", "name")$name, "ITO, Delhi")
  expect_equal(.cpcb_find_station(df, "ito, delhi", "id", "name")$id, "s3")
  expect_equal(.cpcb_find_station(df, "vihar", "id", "name")$id, "s1")
  expect_null(.cpcb_find_station(df, "nowhere", "id", "name"))
  expect_null(.cpcb_find_station(df, "", "id", "name"))
  expect_null(.cpcb_find_station(NULL, "x", "id", "name"))
  expect_error(
    .cpcb_find_station(df, "anand", "id", "name"),
    "'anand' matches 2 stations.*Anand Nagar, Pune; Anand Vihar, Delhi"
  )
  # the value is plain text, not a pattern
  expect_null(.cpcb_find_station(df, ".*", "id", "name"))
})

test_that("states resolve by name or code", {
  local_cpcb()
  expect_equal(.cpcb_resolve_state("kerala")$state_name, "Kerala")
  by_name <- .cpcb_resolve_state("Delhi")
  expect_equal(.cpcb_resolve_state(by_name$state_code)$state_name, "Delhi")
  expect_null(.cpcb_resolve_state("Atlantis"))
})

test_that("a city resolves within a state or across all of them", {
  local_cpcb()
  expect_equal(.cpcb_resolve_city("mumbai", "maharashtra")$city_name, "Mumbai")
  expect_null(.cpcb_resolve_city("mumbai", "Atlantis"))
  expect_null(.cpcb_resolve_city("Atlantis"))
  by_code <- .cpcb_resolve_city("Mumbai")
  expect_equal(.cpcb_resolve_city(by_code$city_code)$city_name, "Mumbai")
})

test_that("the bundled directory is read once and merges city names", {
  local_cpcb()
  rm("directory", envir = .cpcb_cache)
  st <- .cpcb_directory_stations()
  expect_true(all(c("station_id", "station_name", "latitude", "longitude", "city_name", "state_name") %in% names(st)))
  expect_named(.cpcb_cache$directory, c("states", "cities", "stations"), ignore.order = TRUE)
  expect_equal(.cpcb_cache$stations$station_id, st$station_id)

  row <- st[st$station_id == "site_5392", ]
  expect_equal(row$city_name, "Mumbai")
  expect_equal(row$state_name, "Maharashtra")
})

test_that("a station missing from the directory comes from the live feed", {
  local_cpcb()
  local_feed()
  hit <- .cpcb_resolve_station("site_feedonly")
  expect_equal(hit, list(
    station_id = "site_feedonly", station_name = "Zeta Colony, Delhi - DPCC",
    state = "Delhi", city = "Delhi"
  ))
})

test_that("a station is searched by name after its ID", {
  local_cpcb()
  local_feed()
  hit <- .cpcb_resolve_station("no-such-id", station_name = "Zeta Colony")
  expect_equal(hit$station_id, "site_feedonly")
})

test_that("a station lookup survives a feed outage", {
  local_cpcb()
  local_http(fake_response(500, "down"))
  expect_null(.cpcb_resolve_station("site_feedonly"))

  local_cpcb()
  local_http(fake_response(200, '{"country": []}'))
  expect_null(.cpcb_resolve_station("site_feedonly"))
})

test_that("a station in neither source is an error", {
  local_cpcb()
  local_feed()
  expect_error(.cpcb_require_station("site_nope"), "Station 'site_nope' not found")
  expect_equal(.cpcb_require_station("site_feedonly")$city, "Delhi")
})

test_that(".cpcb_col fills a missing column with the default", {
  df <- data.frame(a = 1:2)
  expect_equal(.cpcb_col(df, "a"), 1:2)
  expect_equal(.cpcb_col(df, "b"), c(NA, NA))
  expect_equal(.cpcb_col(df, "b", "x"), c("x", "x"))
})

test_that("every frequency name has CPCB's code", {
  codes <- c(
    hourly = "1H", "1_hour" = "1H", "1h" = "1H",
    daily = "1D", "24_hours" = "1D", "24h" = "1D", "1d" = "1D",
    monthly = "1M", "1m" = "1M",
    "15_minute" = "15M", "15m" = "15M"
  )
  for (name in names(codes)) {
    expect_equal(.cpcb_normalize_frequency(name), codes[[name]], info = name)
  }
  expect_equal(.cpcb_normalize_frequency("Fortnightly"), "Fortnightly")
})

test_that("cpcb_get_complete_list covers the whole directory", {
  local_cpcb()
  all_data <- cpcb_get_complete_list()
  expect_named(all_data, c("cities", "stations"))

  delhi <- all_data$cities[["Delhi"]]
  expect_named(delhi, c("label", "value"))
  expect_true("Delhi" %in% delhi$label)
  expect_equal(delhi$label, delhi$value)

  st <- all_data$stations[["Delhi"]]
  expect_true("site_301" %in% st$value)
  expect_equal(st$label[st$value == "site_301"], "Anand Vihar, Delhi - DPCC")
})

test_that("station and city lists come from the bundled directory", {
  local_cpcb()
  http <- local_http()
  expect_equal(cpcb_get_state_list(), sort(cpcb_get_state_list(), method = "radix"))
  expect_true("Delhi" %in% cpcb_get_city_list("Delhi"))
  mum <- cpcb_get_station_list("mumbai")
  expect_equal(mum$value[mum$label == "Bandra Kurla Complex, Mumbai - IITM"], "site_5392")
  expect_equal(nrow(cpcb_get_station_list("Atlantis")), 0)
  expect_length(http$calls, 0)
})
