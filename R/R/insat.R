# Fire detections read off ISRO MOSDAC's open INSAT L2P fire preview images (as Python's vayuayan.insat)

.insat_preview <- "https://mosdac.gov.in/look/%s_IMG/preview/%d/%s/%sIMG_%s%d_%s_L2P_FIR_V01R00.jpg"
.insat_minutes <- list("3S" = c(0, 30), "3R" = c(15, 45), "3D" = c(0, 30))
.insat_months <- c("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
# "width x height" -> layout: lon and lat pixel anchors, map box, graticule lines, light lines, min_px
# blobs below min_px are JPEG noise at marker edges, where decoders differ
.insat_layouts <- list(
  "2002x2242" = list(
    name = "3S", x_lon = c(168, 50, 1695, 100), y_lat = c(1912, 0, 485, 40),
    box = c(0, 245, 2002, 2242), grat = c(473, 1246), light = TRUE, min_px = 10
  ),
  "2000x2434" = list(
    name = "3S-2024", x_lon = c(501, 70, 1498, 90), y_lat = c(1829.5, 10, 762, 30),
    box = c(0, 150, 2000, 2300), grat = c(1000, 1313), light = TRUE, min_px = 10
  ),
  "1260x1495" = list(
    name = "3R", x_lon = c(20, 60, 1203.5, 100), y_lat = c(1381, 0, 89, 40),
    box = c(23, 92, 1200, 1378), grat = c(611, 777), light = FALSE, min_px = 3
  )
)

#' INSAT fire preview image URLs
#'
#' MOSDAC publishes a preview JPEG of the INSAT-3DS fire product every 30
#' minutes (at :00 and :30 UTC; INSAT-3D too) and of INSAT-3DR at :15 and :45,
#' without a login.
#'
#' @param start First day (UTC), a \code{Date} or \code{"YYYY-MM-DD"}.
#' @param end Last day (UTC), inclusive.
#' @param satellite \code{"3S"} (INSAT-3DS, 2024 on), \code{"3R"} (INSAT-3DR) or \code{"3D"} (INSAT-3D).
#' @return A character vector of URLs, one per image slot.
#' @examples
#' head(insat_fire_urls("2026-11-01"), 2)
#' @export
insat_fire_urls <- function(start, end = start, satellite = "3S") {
  if (!satellite %in% names(.insat_minutes)) {
    stop("satellite must be one of ", paste(sort(names(.insat_minutes)), collapse = ", "), call. = FALSE)
  }
  first <- as.Date(start)
  last <- as.Date(end)
  if (last < first) stop("end is before start", call. = FALSE)
  out <- character(0)
  for (d in as.list(seq(first, last, by = "day"))) {
    y <- as.integer(format(d, "%Y"))
    dmon <- paste0(format(d, "%d"), .insat_months[as.integer(format(d, "%m"))])
    slots <- as.vector(t(outer(0:23, .insat_minutes[[satellite]], function(h, m) sprintf("%02d%02d", h, m))))
    out <- c(out, sprintf(.insat_preview, satellite, y, dmon, satellite, dmon, y, slots))
  }
  out
}

#' Fires on INSAT fire preview images
#'
#' Downloads the MOSDAC preview of every slot from \code{start} to \code{end} (cached
#' under \code{vayuayan_cache_dir()/insat}, and also read from the Python package's
#' cache), finds the red fire markers and converts their centres to longitude
#' and latitude. A blob is a floor on the number of fire pixels: markers
#' overlap. The product misses small and cloud-covered fires.
#'
#' @inheritParams insat_fire_urls
#' @param bbox \code{c(west, south, east, north)} to keep; \code{NULL} for the whole image.
#' @return A data frame with \code{file}, \code{layout} (\code{"3S"}, \code{"3S-2024"} or \code{"3R"}),
#'   \code{time_utc}, \code{header_count} (the product's own count on \code{"3S"} images, read
#'   with the \code{tesseract} command if installed), \code{lon}, \code{lat} and \code{area_px},
#'   one row per fire blob. Slots with no image are skipped. Needs the
#'   suggested \code{jpeg} package.
#'   JPEG libraries decode edge pixels differently, so \code{area_px} can differ by a
#'   few pixels and \code{lon} and \code{lat} by about 0.01 between systems.
#' @examplesIf interactive()
#' punjab <- insat_fires("2026-11-05", bbox = c(73.5, 27.6, 77.8, 32.6))
#' @export
insat_fires <- function(start, end = start, satellite = "3S", bbox = NULL) {
  frames <- list()
  for (url in insat_fire_urls(start, end, satellite)) {
    path <- .insat_download(url)
    if (!is.null(path)) frames[[length(frames) + 1]] <- parse_insat_fire_image(path)
  }
  out <- if (length(frames)) do.call(rbind, frames) else .insat_empty()
  if (!is.null(bbox)) {
    out <- out[out$lon >= bbox[1] & out$lon <= bbox[3] & out$lat >= bbox[2] & out$lat <= bbox[4], , drop = FALSE]
    rownames(out) <- NULL
  }
  out
}

#' Fire blobs on one INSAT fire preview image
#'
#' @param path Path to a MOSDAC INSAT L2P fire preview JPEG.
#' @param read_count Read the header count with \code{tesseract} (\code{"3S"} layout only).
#' @return A data frame as \code{\link{insat_fires}}.
#' @export
parse_insat_fire_image <- function(path, read_count = TRUE) {
  if (!requireNamespace("jpeg", quietly = TRUE)) {
    stop("parse_insat_fire_image needs the jpeg package: install.packages(\"jpeg\")", call. = FALSE)
  }
  rgb <- round(jpeg::readJPEG(path)[, , 1:3] * 255)
  parsed <- parse_insat_fire_array(rgb)
  count <- if (read_count && parsed$layout == "3S") .insat_header_count(rgb) else NA_integer_
  m <- regmatches(basename(path), regexec("_(\\d{2})([A-Z]{3})(\\d{4})_(\\d{2})(\\d{2})_", basename(path)))[[1]]
  when <- if (length(m)) {
    as.POSIXct(sprintf("%s-%02d-%s %s:%s:00", m[4], match(m[3], .insat_months), m[2], m[5], m[6]), tz = "UTC")
  } else {
    as.POSIXct(NA, tz = "UTC")
  }
  b <- parsed$blobs
  if (!nrow(b)) {
    return(.insat_empty())
  }
  data.frame(
    file = basename(path), layout = parsed$layout, time_utc = when, header_count = count,
    lon = b$lon, lat = b$lat, area_px = b$area_px
  )
}

#' Fire blobs on an INSAT preview image array
#'
#' @param rgb A height x width x 3 array of 0-255 values.
#' @return A list with \code{layout} and \code{blobs} (a data frame of \code{lon}, \code{lat},
#'   \code{area_px}, in row-major order of each blob's first pixel). Errors on an
#'   unknown image size or when the graticule is not where the layout expects.
#' @export
parse_insat_fire_array <- function(rgb) {
  key <- paste0(dim(rgb)[2], "x", dim(rgb)[1])
  lay <- .insat_layouts[[key]]
  if (is.null(lay)) stop(sprintf("unknown INSAT preview layout %s x %s", dim(rgb)[2], dim(rgb)[1]), call. = FALSE)
  rows <- (lay$box[2] + 1):lay$box[4]
  cols <- (lay$box[1] + 1):lay$box[3]
  lines <- list(matrix(rgb[rows, lay$grat[1] + 1, ], ncol = 3), matrix(rgb[lay$grat[2] + 1, cols, ], ncol = 3))
  for (px in lines) { # the calibration must still match the drawing
    grey <- (apply(px, 1, max) - apply(px, 1, min)) < 25
    grey <- grey & (if (lay$light) rowMeans(px) > 150 else rowMeans(px) < 140)
    if (mean(grey) < 0.3) stop(sprintf("%s graticule is not where expected; the layout has changed", lay$name), call. = FALSE)
  }
  r <- rgb[rows, cols, 1]
  g <- rgb[rows, cols, 2]
  b <- rgb[rows, cols, 3]
  red <- matrix(FALSE, dim(rgb)[1], dim(rgb)[2])
  red[rows, cols] <- (r - g > 40) & (r - b > 40) & (r > 120)
  groups <- Filter(function(p) nrow(p) >= lay$min_px, .insat_components(red))
  centre <- function(col) vapply(groups, function(p) mean(p[, col] - 1), numeric(1))
  ll <- .insat_lonlat(lay, centre(2), centre(1))
  blobs <- data.frame(lon = round(ll$lon, 3), lat = round(ll$lat, 3), area_px = vapply(groups, nrow, integer(1)))
  list(layout = lay$name, blobs = blobs)
}

# 8-connected groups of TRUE cells as (row, col) matrices, in row-major order of their first cell
.insat_components <- function(mask) {
  idx <- which(mask, arr.ind = TRUE)
  if (!nrow(idx)) {
    return(list())
  }
  idx <- idx[order(idx[, 1], idx[, 2]), , drop = FALSE]
  todo <- mask
  groups <- list()
  for (k in seq_len(nrow(idx))) {
    if (!todo[idx[k, 1], idx[k, 2]]) next
    todo[idx[k, 1], idx[k, 2]] <- FALSE
    stack <- list(idx[k, ])
    got <- list()
    while (length(stack)) {
      p <- stack[[length(stack)]]
      stack[[length(stack)]] <- NULL
      got[[length(got) + 1]] <- p
      for (dy in -1:1) {
        for (dx in -1:1) {
          y <- p[1] + dy
          x <- p[2] + dx
          if (y >= 1 && x >= 1 && y <= nrow(todo) && x <= ncol(todo) && todo[y, x]) {
            todo[y, x] <- FALSE
            stack[[length(stack) + 1]] <- c(y, x)
          }
        }
      }
    }
    groups[[length(groups) + 1]] <- do.call(rbind, got)
  }
  groups
}

.insat_merc <- function(lat) log(tan(pi / 4 + lat * pi / 360))

.insat_lonlat <- function(lay, x, y) {
  a <- lay$x_lon
  l <- lay$y_lat
  lon <- a[2] + (x - a[1]) * (a[4] - a[2]) / (a[3] - a[1])
  m <- .insat_merc(l[2]) + (y - l[1]) * (.insat_merc(l[4]) - .insat_merc(l[2])) / (l[3] - l[1])
  list(lon = lon, lat = (2 * atan(exp(m)) - pi / 2) * 180 / pi)
}

# "COUNT:N POINTS" from a "3S" header with the tesseract command; NA without it
.insat_header_count <- function(rgb) {
  exe <- Sys.which("tesseract")
  if (!nzchar(exe)) {
    return(NA_integer_)
  }
  grey <- floor((rgb[96:140, 251:1600, 1] * 299 + rgb[96:140, 251:1600, 2] * 587 + rgb[96:140, 251:1600, 3] * 114) / 1000)
  big <- 255 - grey[rep(seq_len(nrow(grey)), each = 2), rep(seq_len(ncol(grey)), each = 2)]
  pgm <- tempfile(fileext = ".pgm")
  on.exit(unlink(pgm), add = TRUE)
  con <- file(pgm, "wb")
  writeBin(charToRaw(sprintf("P5\n%d %d\n255\n", ncol(big), nrow(big))), con)
  writeBin(as.raw(t(big)), con)
  close(con)
  text <- paste(suppressWarnings(system2(exe, c(shQuote(pgm), "-", "--psm", "7"), stdout = TRUE, stderr = FALSE)), collapse = " ")
  m <- regmatches(text, regexec("COUNT\\s*:\\s*([0-9OoIl]+)", text))[[1]]
  if (length(m) < 2) {
    return(NA_integer_)
  }
  as.integer(chartr("OoIl", "0011", m[2]))
}

# Cached image path; NULL when MOSDAC has no image for the slot
.insat_download <- function(url) {
  name <- basename(url)
  cached <- .cache_lookup(.cache_dirs("insat"), name)
  if (!is.null(cached)) {
    return(cached)
  }
  resp <- httr::RETRY("GET", url, times = 3, httr::timeout(120), quiet = TRUE, terminate_on = 400:499)
  if (httr::status_code(resp) == 404) {
    return(NULL)
  }
  httr::stop_for_status(resp, task = "download an INSAT preview")
  body <- httr::content(resp, as = "raw")
  if (length(body) < 2 || body[1] != as.raw(0xff) || body[2] != as.raw(0xd8)) {
    return(NULL)
  } # an HTML page, not a JPEG
  .cache_write(file.path(vayuayan_cache_dir(), "insat", name), function(p) writeBin(body, p))
}

.insat_empty <- function() {
  data.frame(
    file = character(0), layout = character(0), time_utc = as.POSIXct(character(0), tz = "UTC"),
    header_count = integer(0), lon = numeric(0), lat = numeric(0), area_px = integer(0)
  )
}
