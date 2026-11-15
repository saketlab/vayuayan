# every test reads and writes a temporary cache, never the user's real downloads
withr::local_envvar(VAYUAYAN_CACHE_DIR = tempfile("vayuayan_test_cache"), .local_envir = testthat::teardown_env())
