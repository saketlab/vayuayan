# NAQI and US AQI against tables typed from the source documents, not read
# from the package, so a wrong table in the package fails.

# CPCB AQI-Calculator.xls Sheet1 D8-D20 and CUPS/82/2014-15 Table 3.11 p.35 and
# p.37 (continuous). The last top is the Very Poor width added to its top.
india_tops <- list(
  PM10 = c(0, 50, 100, 250, 350, 430, 510),
  PM2.5 = c(0, 30, 60, 90, 120, 250, 380),
  NO2 = c(0, 40, 80, 180, 280, 400, 520),
  # Severe stays on the published 748 band: the calculator's formula is wrong there
  O3 = c(0, 50, 100, 168, 208, 748, 1288),
  CO = c(0, 1, 2, 10, 17, 34, 51),
  SO2 = c(0, 40, 80, 380, 800, 1600, 2400),
  NH3 = c(0, 200, 400, 800, 1200, 1800, 2400),
  # CUPS/82 Table 3.11 p.35; the calculator has no Pb row
  Pb = c(0, 0.5, 1, 2, 3, 3.5, 4)
)
india_index <- c(0, 50, 100, 200, 300, 400, 500)

# 40 CFR 58 App G Table 2 (FR 16404-05); EPA TAD EPA-403/B-26-003 Table 6 p.14
us_bands <- list(
  "PM2.5" = list(1, rbind(
    c(0.0, 9.0, 0, 50), c(9.1, 35.4, 51, 100), c(35.5, 55.4, 101, 150),
    c(55.5, 125.4, 151, 200), c(125.5, 225.4, 201, 300), c(225.5, 325.4, 301, 500)
  )),
  PM10 = list(0, rbind(
    c(0, 54, 0, 50), c(55, 154, 51, 100), c(155, 254, 101, 150),
    c(255, 354, 151, 200), c(355, 424, 201, 300), c(425, 604, 301, 500)
  )),
  O3 = list(3, rbind(
    c(0.000, 0.054, 0, 50), c(0.055, 0.070, 51, 100), c(0.071, 0.085, 101, 150),
    c(0.086, 0.105, 151, 200), c(0.106, 0.200, 201, 300)
  )),
  O3_1h = list(3, rbind(
    c(0.125, 0.164, 101, 150), c(0.165, 0.204, 151, 200),
    c(0.205, 0.404, 201, 300), c(0.405, 0.604, 301, 500)
  )),
  CO = list(1, rbind(
    c(0.0, 4.4, 0, 50), c(4.5, 9.4, 51, 100), c(9.5, 12.4, 101, 150),
    c(12.5, 15.4, 151, 200), c(15.5, 30.4, 201, 300), c(30.5, 50.4, 301, 500)
  )),
  SO2 = list(0, rbind(c(0, 35, 0, 50), c(36, 75, 51, 100), c(76, 185, 101, 150), c(186, 304, 151, 200))),
  SO2_24h = list(0, rbind(c(305, 604, 201, 300), c(605, 1004, 301, 500))),
  NO2 = list(0, rbind(
    c(0, 53, 0, 50), c(54, 100, 51, 100), c(101, 360, 101, 150),
    c(361, 649, 151, 200), c(650, 1249, 201, 300), c(1250, 2049, 301, 500)
  ))
)

# I = (IHI - ILO) / (BHI - BLO) * (C - BLO) + ILO (CUPS/82 p.37; TAD p.13)
equation <- function(c, b) (b[4] - b[3]) / (b[2] - b[1]) * (c - b[1]) + b[3]

test_that("every India band has its index at the bottom, top and middle", {
  for (name in names(india_tops)) {
    tops <- india_tops[[name]]
    for (k in 1:6) {
      band <- c(tops[k], tops[k + 1], india_index[k], india_index[k + 1])
      info <- paste(name, k)
      expect_equal(aqi_sub_index(name, band[1]), band[3], info = info)
      expect_equal(aqi_sub_index(name, band[2]), band[4], info = info)
      middle <- (band[1] + band[2]) / 2
      expect_equal(aqi_sub_index(name, middle), equation(middle, band), info = info)
    }
  }
})

test_that("every US band has its index at the bottom, top and middle", {
  for (name in names(us_bands)) {
    decimals <- us_bands[[name]][[1]]
    bands <- us_bands[[name]][[2]]
    for (k in seq_len(nrow(bands))) {
      band <- bands[k, ]
      info <- paste(name, k)
      expect_equal(us_aqi_sub_index(name, band[1]), band[3], info = info)
      expect_equal(us_aqi_sub_index(name, band[2]), band[4], info = info)
      # the middle truncated to the table's precision, as TAD p.13 does first
      middle <- floor((band[1] + band[2]) / 2 * 10^decimals + 1e-9) / 10^decimals
      expect_equal(us_aqi_sub_index(name, middle), equation(middle, band), info = info)
    }
  }
})

test_that("the NAQI matches the cell formulas of CPCB's calculator", {
  cases <- list(
    list("PM2.5", 31, 50 + 1 * 50 / 30), list("PM2.5", 34, 50 + 4 * 50 / 30),
    list("PM2.5", 45, 75), list("PM2.5", 60, 100),
    list("PM2.5", 60.4, 100 + 0.4 * 100 / 30), list("PM2.5", 61, 100 + 1 * 100 / 30),
    list("PM2.5", 300, 400 + 50 * 100 / 130), list("PM10", 121, 100 + 21 * 100 / 150),
    list("PM10", 700, 400 + 270 * 100 / 80), list("CO", 1.1, 50 + 0.1 * 50 / 1),
    list("O3", 169, 200 + 1 * 100 / 40)
  )
  for (case in cases) {
    expect_equal(aqi_sub_index(case[[1]], case[[2]]), case[[3]], info = paste(case[[1]], case[[2]]))
  }
})

test_that("O3 above 748 keeps the published band, not the calculator's formula", {
  # the calculator would give 400 + (749 - 400) * 100 / 539 = 464.75
  expect_equal(aqi_sub_index("O3", 748), 400)
  expect_equal(aqi_sub_index("O3", 749), 400 + 1 * 100 / 540)
})

test_that("O3 above 208 stays on the 8-hour value", {
  expect_equal(aqi_sub_index("O3", 300), 300 + 92 * 100 / 540)
})

test_that("the NAQI is not capped at 500", {
  expect_equal(aqi_sub_index("PM2.5", 1000), 400 + 750 * 100 / 130)
  r <- compute_aqi(c("PM2.5" = 1000, PM10 = 50, NO2 = 40))
  expect_equal(r$aqi, floor(400 + 750 * 100 / 130 + 0.5))
  expect_equal(r$category, "Severe")
})

test_that("the NAQI has no gaps between bands and rounds half up", {
  # 30.5 is in the former gap between 30 and 31
  expect_equal(aqi_sub_index("PM2.5", 30.5), 50 + 0.5 * 50 / 30)
  expect_equal(aqi_sub_index("PM10", 100.5), 100 + 0.5 * 100 / 150)
  expect_equal(compute_aqi(c(PM10 = 50.5, NO2 = 10, SO2 = 10))$aqi, 51L)
})

# PM2.5, PM10, NO2 in ug/m3; expected AQI and category hand-computed
same_air <- list(
  # India: PM2.5 25*50/30 = 41.67, PM10 45, NO2 37.5; US: 49/26.3*15.9+51 = 80.62
  low = list(c(25, 45, 30), 45L, "Good", "PM10", 81L, "Moderate", "PM2.5"),
  # India: PM2.5 100+15*100/30 = 150, PM10 133.33, NO2 110; US: 49/69.9*19.5+151 = 164.67
  moderate = list(c(75, 150, 90), 150L, "Moderate", "PM2.5", 165L, "Unhealthy", "PM2.5"),
  # India: PM10 400+270*100/80 = 737.5 half up; PM2.5 515.38; NO2 483.33
  # US: PM2.5 199/99.9*174.5+301 = 648.6; PM10 606.73
  extreme = list(c(400, 700, 500), 738L, "Severe", "PM10", 649L, "Hazardous", "PM2.5")
)

test_that("the same air has a different category in each standard", {
  for (name in names(same_air)) {
    case <- same_air[[name]]
    input <- case[[1]]
    india <- compute_aqi(c("PM2.5" = input[1], PM10 = input[2], NO2 = input[3]))
    expect_equal(india$aqi, case[[2]], info = name)
    expect_equal(india$category, case[[3]], info = name)
    expect_equal(india$dominant_pollutant, case[[4]], info = name)
    us <- compute_us_aqi(c("PM2.5" = input[1], PM10 = input[2]))
    expect_equal(us$aqi, case[[5]], info = name)
    expect_equal(us$category, case[[6]], info = name)
    expect_equal(us$dominant_pollutant, case[[7]], info = name)
    expect_false(india$category == us$category, info = name)
  }
})

test_that("each standard uses only its published categories", {
  india <- c("Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe")
  us <- c(
    "Good", "Moderate", "Unhealthy for Sensitive Groups", "Unhealthy",
    "Very Unhealthy", "Hazardous"
  )
  expect_setequal(get_aqi_categories(0:999), india)
  expect_setequal(us_aqi_category(0:999), us)
})
