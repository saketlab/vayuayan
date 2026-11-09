past <- function(names) sprintf("/AQI_daily/city_level/%s/2022/%s_2022.csv", names, names)

token_replies <- function(tokens) lapply(tokens, token_reply)

test_that("prefetch sends fewer than two files to the sequential download", {
  local_cpcb()
  http <- local_http()
  this_year <- format(Sys.Date(), "%Y")
  current <- sprintf("/AQI_daily/x/%s/x_%s.csv", this_year, this_year)

  expect_null(.cpcb_prefetch(character(0)))
  expect_null(.cpcb_prefetch(past("a")))
  # current-year files are not cached, so they do not count
  expect_null(.cpcb_prefetch(c(past("a"), current, current)))
  # the same file twice is one file
  expect_null(.cpcb_prefetch(c(past("a"), past("a"))))
  expect_length(http$calls, 0)
})

test_that("prefetch skips files that are already cached", {
  dir <- local_cpcb()
  http <- local_http()
  files <- past(c("a", "b"))
  cached <- file.path(dir, .cpcb_cache_name(files[1]))
  dir.create(dirname(cached), recursive = TRUE)
  writeLines("Day\n1", cached)

  .cpcb_prefetch(files)
  expect_length(http$calls, 0)
})

test_that("prefetch asks for one token each and downloads in one batch", {
  dir <- local_cpcb()
  files <- past(c("a", "b"))
  http <- do.call(local_http, token_replies(c("tokA", "tokB%3D")))
  dl <- local_multi_download(c(200L, 200L))

  .cpcb_prefetch(files)

  expect_length(http$calls, 2)
  expect_equal(http$calls[[1]]$url, paste0(CPCB_REPO, "get-download-link"))
  expect_equal(http$calls[[1]]$query, list(file_name = files[1]))
  expect_equal(http$calls[[2]]$query, list(file_name = files[2]))
  # a token request has one try, an outage must not cost a timeout per file
  expect_equal(http$calls[[1]]$args$times, 1)

  expect_equal(dl$urls, paste0(CPCB_REPO, "download-excel-fileEnc?file_name=", c("tokA", "tokB%3D")))
  dest <- file.path(dir, vapply(files, .cpcb_cache_name, ""))
  expect_equal(unname(dl$destfiles), unname(paste0(dest, ".part")))
  expect_false(dl$args$progress)
  expect_equal(dl$args$timeout, 120)
  expect_equal(dl$args$ssl_verifypeer, 1L)
  expect_equal(dl$args$ssl_verifyhost, 2L)
  expect_true(all(file.exists(dest)))
  expect_false(any(file.exists(paste0(dest, ".part"))))
})

test_that("prefetch turns off verification after a TLS failure this session", {
  local_cpcb()
  .cpcb_cache$insecure <- TRUE
  do.call(local_http, token_replies(c("a", "b")))
  dl <- local_multi_download(c(200L, 200L))

  .cpcb_prefetch(past(c("a", "b")))
  expect_equal(dl$args$ssl_verifypeer, 0L)
  expect_equal(dl$args$ssl_verifyhost, 0L)
})

test_that("prefetch keeps only the files that downloaded", {
  dir <- local_cpcb()
  files <- past(c("a", "b", "c"))
  do.call(local_http, token_replies(c("a", "b", "c")))
  local_multi_download(c(200L, 404L, 500L))

  .cpcb_prefetch(files)

  dest <- file.path(dir, vapply(files, .cpcb_cache_name, ""))
  expect_equal(unname(file.exists(dest)), c(TRUE, FALSE, FALSE))
  expect_equal(unname(file.exists(paste0(dest, ".part"))), c(FALSE, FALSE, FALSE))
})

test_that("prefetch downloads the files that got a token before an outage", {
  dir <- local_cpcb()
  files <- past(c("a", "b", "c"))
  http <- local_http(token_reply("tokA"), fake_response(500, "down"))
  dl <- local_multi_download(200L)

  .cpcb_prefetch(files)

  # the failed second token ends the requests, so c is never asked for
  expect_length(http$calls, 2)
  expect_equal(dl$urls, paste0(CPCB_REPO, "download-excel-fileEnc?file_name=tokA"))
  expect_equal(list.files(dir, recursive = TRUE), .cpcb_cache_name(files[1]))
})

test_that("prefetch is a no-op when CPCB gives no first token", {
  dir <- local_cpcb()
  http <- local_http(fake_response(500, "down"))
  dl <- local_multi_download(200L)

  expect_null(.cpcb_prefetch(past(c("a", "b", "c"))))
  expect_length(http$calls, 1)
  expect_null(dl$urls)
  expect_equal(list.files(dir, recursive = TRUE), character(0))
})
