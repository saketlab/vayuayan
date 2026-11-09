test_that("the CPCB repository API lives at its known base", {
  expect_equal(.cpcb_base_url, "https://airquality.cpcb.gov.in")
  expect_equal(.cpcb_new_api("file-path"), paste0(CPCB_REPO, "file-path"))
})

test_that(".cpcb_get issues a retried GET", {
  local_cpcb()
  http <- local_http(fake_response(200, "ok"))
  res <- .cpcb_get("https://cpcb.example/x", httr::timeout(5))

  call <- http$calls[[1]]
  expect_equal(call$method, "GET")
  expect_equal(call$url, "https://cpcb.example/x")
  expect_equal(call$args$times, 4)
  expect_equal(call$args$pause_base, 1)
  expect_equal(call$args$pause_cap, 8)
  expect_equal(call$args$terminate_on, 400:499)
  expect_true(call$args$quiet)
  expect_equal(call$options$timeout_ms, 5000)
  expect_equal(res$status_code, 200L)
})

test_that(".cpcb_get raises on 4xx and 5xx", {
  local_cpcb()
  for (status in c(403L, 404L, 500L, 503L)) {
    local_http(fake_response(status, "nope"))
    expect_error(
      .cpcb_get("https://cpcb.example/x"),
      class = paste0("http_", status)
    )
  }
})

test_that(".cpcb_get passes a connection failure on and stays verified", {
  local_cpcb()
  http <- local_http(connection_error())
  expect_error(.cpcb_get("https://cpcb.example/x"), "Could not resolve host")
  expect_length(http$calls, 1)
  expect_null(.cpcb_cache$insecure)
})

test_that(".cpcb_get repeats a TLS failure without verification", {
  local_cpcb()
  http <- local_http(
    connection_error("SSL certificate problem: certificate has expired"),
    fake_response(200, "ok"),
    fake_response(200, "ok")
  )
  res <- suppressMessages(.cpcb_get("https://cpcb.example/x"))

  expect_equal(res$status_code, 200L)
  expect_length(http$calls, 2)
  expect_null(http$calls[[1]]$ssl_verifypeer)
  expect_equal(http$calls[[2]]$ssl_verifypeer, 0L)
  expect_equal(http$calls[[2]]$ssl_verifyhost, 0L)
  expect_true(.cpcb_cache$insecure)

  # the next request skips the failing verified attempt
  .cpcb_get("https://cpcb.example/y")
  expect_length(http$calls, 3)
  expect_equal(http$calls[[3]]$ssl_verifypeer, 0L)
})

test_that("every TLS message .cpcb_ssl_fallback knows triggers it", {
  for (msg in c("SSL connect error", "schannel: TLS handshake", "SEC_E_UNTRUSTED_ROOT")) {
    local_cpcb()
    n <- 0
    out <- suppressMessages(.cpcb_ssl_fallback(function() {
      n <<- n + 1
      if (n == 1) stop(msg) else "ok"
    }))
    expect_equal(out, "ok", info = msg)
    expect_true(.cpcb_cache$insecure, info = msg)
  }
})

test_that("the download link is requested with the file path as a query", {
  local_cpcb()
  path <- "/Raw_data/15Min/2024/site_301 Anand.csv"
  http <- local_http(token_reply("abc%3D%3D\n"))
  url <- .cpcb_download_url(path)

  call <- http$calls[[1]]
  expect_equal(call$method, "GET")
  expect_equal(call$url, paste0(CPCB_REPO, "get-download-link"))
  expect_equal(call$query, list(file_name = path))
  expect_equal(
    call$final,
    paste0(CPCB_REPO, "get-download-link?file_name=%2FRaw_data%2F15Min%2F2024%2Fsite_301%20Anand.csv")
  )
  expect_equal(call$options$timeout_ms, 30000)
  expect_equal(call$args$times, 4)
  expect_equal(url, paste0(CPCB_REPO, "download-excel-fileEnc?file_name=abc%3D%3D"))
})

test_that("the download token goes into the URL unchanged", {
  local_cpcb()
  for (token in c("aB3+/=_-", "x%2Fy%3D", "plain")) {
    local_http(token_reply(token))
    expect_equal(
      .cpcb_download_url("/x.csv"),
      paste0(CPCB_REPO, "download-excel-fileEnc?file_name=", token),
      info = token
    )
  }
})

test_that(".cpcb_download_url sets how many times to retry", {
  local_cpcb()
  http <- local_http(token_reply())
  .cpcb_download_url("/x.csv", times = 1)
  expect_equal(http$calls[[1]]$args$times, 1)
})

test_that(".cpcb_download_url reports each kind of failure", {
  local_cpcb()
  local_http(fake_response(404, "gone"))
  expect_error(.cpcb_download_url("/x.csv"), class = "http_404")
  local_http(fake_response(500, "boom"))
  expect_error(.cpcb_download_url("/x.csv"), class = "http_500")
  local_http(connection_error())
  expect_error(.cpcb_download_url("/x.csv"), "Could not resolve")

  # bodies CPCB answers with when it has no token
  for (body in c("", "   ", "<html>error</html>", "{\"status\":\"failed\"}")) {
    local_http(fake_response(200, body))
    expect_error(.cpcb_download_url("/x.csv"), "no download token", info = body)
  }

  # bytes that are not UTF-8 decode to NA
  local_http(fake_response(200, as.raw(0xff)))
  expect_error(.cpcb_download_url("/x.csv"), "no download token")
})

test_that(".cpcb_download_repository fetches the token, then the file", {
  dir <- local_cpcb()
  http <- local_http(
    token_reply("tok%3D"),
    fake_response(200, "Day,January\n1,10\n")
  )
  dest <- .cpcb_download_repository("/AQI_daily/delhi/2022/delhi_2022.csv", "cpcb/delhi_2022.csv")

  expect_equal(dest, file.path(dir, "cpcb/delhi_2022.csv"))
  expect_length(http$calls, 2)
  expect_equal(http$calls[[1]]$url, paste0(CPCB_REPO, "get-download-link"))
  expect_equal(
    http$calls[[2]]$url,
    paste0(CPCB_REPO, "download-excel-fileEnc?file_name=tok%3D")
  )
  expect_null(http$calls[[2]]$query)
  expect_equal(http$calls[[2]]$options$timeout_ms, 120000)
  expect_equal(http$calls[[2]]$path, paste0(dest, ".part"))
  expect_equal(readLines(dest), c("Day,January", "1,10"))
  expect_false(file.exists(paste0(dest, ".part")))
})

test_that(".cpcb_download_repository without a name writes a temporary file", {
  local_cpcb()
  local_http(
    token_reply(),
    fake_response(200, "a,b\n")
  )
  dest <- .cpcb_download_repository("/x/y.csv")
  on.exit(unlink(dest), add = TRUE)
  expect_match(dest, "\\.csv$")
  expect_equal(normalizePath(dirname(dest)), normalizePath(tempdir()))
})

test_that("a failed file download leaves nothing behind", {
  dir <- local_cpcb()
  http <- local_http(
    token_reply(),
    fake_response(404, "not here")
  )
  expect_error(.cpcb_download_repository("/a/x_2020.csv", "cpcb/x.csv"), class = "http_404")
  expect_equal(list.files(dir, recursive = TRUE), character(0))
  expect_length(http$calls, 2)
})

test_that("a failed token request stops before the file is fetched", {
  dir <- local_cpcb()
  http <- local_http(fake_response(500, "down"))
  expect_error(.cpcb_download_repository("/a/x_2020.csv", "cpcb/x.csv"), class = "http_500")
  expect_length(http$calls, 1)
  expect_equal(list.files(dir, recursive = TRUE), character(0))
})

csv_path_current <- function() {
  year <- format(Sys.Date(), "%Y")
  sprintf("/Raw_data/15Min/%s/site_301_%s.csv", year, year)
}

test_that("a current-year CSV is read and not kept", {
  dir <- local_cpcb()
  http <- local_http(
    token_reply(),
    fake_response(200, "Timestamp,PM2.5 (ug/m3)\n2024-01-01,12\n2024-01-02,13\n")
  )
  df <- .cpcb_read_repository(csv_path_current())

  expect_equal(names(df), c("Timestamp", "PM2.5 (ug/m3)"))
  expect_equal(df$`PM2.5 (ug/m3)`, c(12L, 13L))
  expect_false(file.exists(sub("\\.part$", "", http$calls[[2]]$path)))
  expect_equal(list.files(dir, recursive = TRUE), character(0))
})

test_that("n_max limits the rows read from a CSV", {
  local_cpcb()
  local_http(
    token_reply(),
    fake_response(200, "a\n1\n2\n3\n")
  )
  expect_equal(.cpcb_read_repository(csv_path_current(), n_max = 2)$a, c(1L, 2L))
})

test_that("an Excel workbook from CPCB is read, to n_max rows", {
  xlsx <- readxl::readxl_example("datasets.xlsx")
  bytes <- readBin(xlsx, "raw", file.size(xlsx))
  full <- as.data.frame(readxl::read_excel(xlsx))
  dir <- local_cpcb()

  local_http(token_reply(), fake_response(200, bytes))
  df <- .cpcb_read_repository("/AQI_daily/delhi/2022/delhi_2022.xlsx", n_max = 3)
  expect_s3_class(df, "data.frame")
  expect_false(inherits(df, "tbl_df"))
  expect_equal(nrow(df), 3)
  expect_equal(names(df), names(full))
  # the past-year file is in the cache
  expect_true(file.exists(file.path(dir, "cpcb/AQI_daily/delhi/2022/delhi_2022.xlsx")))

  http <- local_http()
  expect_equal(nrow(.cpcb_read_repository("/AQI_daily/delhi/2022/delhi_2022.xlsx")), nrow(full))
  expect_length(http$calls, 0)
})

test_that("a file already in either cache needs no request", {
  dir <- local_cpcb()
  http <- local_http()
  rel <- .cpcb_cache_name("/AQI_daily/delhi/2021/delhi_2021.csv")

  own <- file.path(dir, rel)
  dir.create(dirname(own), recursive = TRUE)
  writeLines("Day,January\n1,11", own)
  expect_equal(.cpcb_read_repository("/AQI_daily/delhi/2021/delhi_2021.csv")$January, 11L)

  unlink(own)
  py <- file.path(.python_cache_dir(), rel)
  dir.create(dirname(py), recursive = TRUE)
  writeLines("Day,January\n1,22", py)
  expect_equal(.cpcb_read_repository("/AQI_daily/delhi/2021/delhi_2021.csv")$January, 22L)
  expect_length(http$calls, 0)
})

test_that("a cached error page or empty file is downloaded again", {
  path <- "/AQI_daily/delhi/2021/delhi_2021.csv"
  for (body in c("<html>Service Unavailable</html>", "{\"status\":\"failed\"}", "")) {
    dir <- local_cpcb()
    cached <- file.path(dir, .cpcb_cache_name(path))
    dir.create(dirname(cached), recursive = TRUE)
    writeLines(body, cached)
    http <- local_http(token_reply(), fake_response(200, "Day,January\n1,33\n"))

    expect_equal(.cpcb_read_repository(path)$January, 33L, info = body)
    expect_length(http$calls, 2)
    expect_equal(readLines(cached), c("Day,January", "1,33"), info = body)
  }
})

test_that("a corrupt workbook is not left in the cache", {
  dir <- local_cpcb()
  local_http(
    token_reply(),
    fake_response(200, "<html>Service Unavailable</html>")
  )
  path <- "/AQI_daily/delhi/2019/delhi_2019.xlsx"
  expect_error(.cpcb_read_repository(path))
  expect_false(file.exists(file.path(dir, .cpcb_cache_name(path))))
})

test_that(".cpcb_save_year needs no path and skips an entry without a file", {
  local_mocked_bindings(
    .cpcb_read_repository = function(filepath, n_max = Inf) data.frame(Day = 1:2)
  )
  listing <- list(list(year = "2021", filepath = "/2021.xlsx"))
  expect_silent(rows <- .cpcb_save_year(listing, 2021, "", "city Delhi"))
  expect_equal(nrow(rows), 2)
  expect_error(.cpcb_save_year(list(list(year = "2021")), 2021, "", "city Delhi"), "not found")
})

test_that(".cpcb_save_year writes a CSV only when given a path", {
  written <- 0
  local_mocked_bindings(
    .cpcb_read_repository = function(filepath, n_max = Inf) data.frame(Day = 1:2)
  )
  local_mocked_bindings(
    write.csv = function(x, file, ...) {
      written <<- written + 1
      file.create(file)
    },
    .package = "utils"
  )
  listing <- list(list(year = "2021", filepath = "/2021.xlsx"))

  rows <- .cpcb_save_year(listing, 2021, "", "city Delhi")
  expect_equal(nrow(rows), 2)
  expect_equal(written, 0)

  suppressMessages(.cpcb_save_year(listing, 2021, tempfile(), "city Delhi"))
  expect_equal(written, 1)
})

test_that(".cpcb_save_year writes the year asked for, capped at 31 rows", {
  asked <- NULL
  sheet <- data.frame(Day = 1:31, January = 31:1)
  local_mocked_bindings(.cpcb_read_repository = function(filepath, n_max = Inf) {
    asked <<- list(filepath = filepath, n_max = n_max)
    sheet
  })
  out <- tempfile(fileext = ".csv")
  on.exit(unlink(out), add = TRUE)
  listing <- list(
    list(year = "2021", filepath = "/2021.xlsx"),
    list(year = 2022L, filepath = "/2022.xlsx")
  )

  rows <- suppressMessages(.cpcb_save_year(listing, 2022, out, "city Delhi"))
  expect_equal(asked, list(filepath = "/2022.xlsx", n_max = 31))
  expect_equal(nrow(rows), 31)
  expect_equal(nrow(utils::read.csv(out)), 31)

  suppressMessages(.cpcb_save_year(listing, "2021", out, "city Delhi"))
  expect_equal(asked$filepath, "/2021.xlsx")
  expect_error(
    .cpcb_save_year(listing, 2019, out, "city Delhi"),
    "Data not found for city Delhi in year 2019"
  )
})
