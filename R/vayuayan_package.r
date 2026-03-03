#' @keywords internal
"_PACKAGE"

#' @importFrom httr GET POST content stop_for_status add_headers set_cookies timeout
#'             write_disk user_agent status_code
#' @importFrom jsonlite fromJSON toJSON base64_enc base64_dec
#' @importFrom dplyr %>% mutate filter select group_by summarise bind_rows across all_of group_split
#' @importFrom sf st_read st_transform st_union st_bbox st_crs st_is_empty st_area st_write
#' @importFrom terra rast crop mask ext values vect
#' @importFrom geosphere distHaversine
#' @importFrom cli cli_alert_info cli_alert_success cli_alert_warning cli_alert
#'             cli_h1 cli_h2 cli_ul cli_text cli_code
#' @importFrom glue glue
#' @importFrom readxl read_excel
#' @importFrom lubridate now year month day hour
#' @importFrom stats sd
#' @importFrom utils download.file head
NULL

NULL

.onAttach <- function(libname, pkgname) {
  packageStartupMessage("vayuayan: Air quality data analysis for India")
  packageStartupMessage("Version 0.1.3")
  packageStartupMessage("Use vayuayan_welcome() for quick start guide")
}
