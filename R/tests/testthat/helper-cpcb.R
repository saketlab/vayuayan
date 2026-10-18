# GitHub runners time out reaching CPCB; the first curl error skips the rest
cpcb_state <- new.env()

cpcb_test_that <- function(desc, code) {
  test_that(desc, {
    skip_on_cran()
    skip_if_offline()
    if (!is.null(cpcb_state$error)) skip(cpcb_state$error)
    tryCatch(code, curl_error = function(e) {
      cpcb_state$error <- paste("CPCB unreachable:", conditionMessage(e))
      skip(cpcb_state$error)
    })
  })
}
