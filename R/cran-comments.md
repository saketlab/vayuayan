## R CMD check results

0 errors | 0 warnings | 1 note

* This is a new submission.

## Internet resources

The package wraps public web services (CPCB, OAQ, and the WUSTL ACAG bucket
on the AWS Open Data registry). Examples that need the network use
`@examplesIf interactive()`, or `@examplesIf` on the `OAQ_API_KEY`
environment variable for the key-protected OAQ API. Network tests call
`skip_on_cran()` and `skip_if_offline()`. The vignette evaluates network
chunks only when `NOT_CRAN` is `"true"` and CPCB answers.

The station lookup functions read a bundled directory file and run offline
in examples and tests.

Downloads are cached only in `tools::R_user_dir("vayuayan", "cache")`, or in
a directory the user sets with the `vayuayan.cache_dir` option, the
`VAYUAYAN_CACHE_DIR` environment variable or a `cache_dir` argument. Nothing
is written during examples, tests or the vignette on CRAN.
