#' Cache directory of vayuayan
#'
#' @description
#' Downloads are cached under one root, laid out like the Python package's
#' cache: CPCB repository files under \code{cpcb/} by their repository path,
#' and PM2.5 NetCDF files under \code{pm25/} by their WUSTL file names.
#'
#' The root is the \code{vayuayan.cache_dir} option, else the
#' \code{VAYUAYAN_CACHE_DIR} environment variable, else
#' \code{tools::R_user_dir("vayuayan", "cache")}. Setting
#' \code{VAYUAYAN_CACHE_DIR} makes R and Python share one cache. Files already
#' in the Python package's default cache (\code{~/.cache/vayuayan}, or its
#' \code{pm25_data} folder in the working directory) are read without
#' downloading them again.
#'
#' @return Character path of the cache root. It is not created.
#' @examples
#' vayuayan_cache_dir()
#' @export
vayuayan_cache_dir <- function() {
  dir <- getOption("vayuayan.cache_dir", "")
  if (!nzchar(dir)) dir <- Sys.getenv("VAYUAYAN_CACHE_DIR")
  if (!nzchar(dir)) dir <- tools::R_user_dir("vayuayan", "cache")
  dir
}

# default cache root of the Python package (constants.get_cache_dir)
.python_cache_dir <- function() {
  env <- Sys.getenv("VAYUAYAN_CACHE_DIR")
  if (nzchar(env)) {
    return(env)
  }
  if (.Platform$OS.type == "windows") {
    home <- Sys.getenv("USERPROFILE", path.expand("~"))
    return(file.path(home, "AppData", "Local", "vayuayan", "cache"))
  }
  xdg <- Sys.getenv("XDG_CACHE_HOME", file.path(path.expand("~"), ".cache"))
  file.path(xdg, "vayuayan")
}

# first existing file among dirs, else NULL
.cache_lookup <- function(dirs, name, min_size = 0) {
  for (path in file.path(unique(dirs), name)) {
    if (file.exists(path) && file.info(path)$size > min_size) {
      return(path)
    }
  }
  NULL
}

# Cache path of a CPCB repository file relative to a cache root, or NULL when
# it must not be cached: files of the current year still change.
.cpcb_cache_name <- function(filepath) {
  years <- as.integer(regmatches(
    filepath, gregexpr("(?<![0-9])(19|20)[0-9]{2}(?![0-9])", filepath, perl = TRUE)
  )[[1]])
  current <- as.integer(format(Sys.Date(), "%Y"))
  if (length(years) == 0 || max(years) >= current) {
    return(NULL)
  }
  parts <- strsplit(filepath, "/", fixed = TRUE)[[1]]
  parts <- parts[!parts %in% c("", ".", "..")]
  do.call(file.path, as.list(c("cpcb", gsub("[^A-Za-z0-9_.-]", "_", parts))))
}

.pm25_default_dirs <- function() {
  c(
    file.path(vayuayan_cache_dir(), "pm25"),
    file.path(.python_cache_dir(), "pm25"),
    "pm25_data"
  )
}
