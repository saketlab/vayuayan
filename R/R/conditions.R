# parent keeps its classes, so callers matching http_404 or curl_error still match
.vayuayan_abort <- function(class, message, ..., parent = NULL) {
  inherited <- if (is.null(parent)) character() else setdiff(class(parent), c("error", "condition"))
  stop(structure(
    class = c(class, inherited, "error", "condition"),
    list(message = message, call = NULL, ...)
  ))
}
