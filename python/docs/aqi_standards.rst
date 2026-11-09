AQI Standards
=============

vayuayan computes two different indices. They use different scales, averaging
times and pollutants, so an AQI value or category from one is not comparable
to one from the other.

.. list-table:: The two standards side by side
   :header-rows: 1
   :widths: 24 38 38

   * -
     - India: National AQI (NAQI) of CPCB
     - United States: AQI of the EPA
   * - Functions
     - ``compute_aqi``, ``daily_aqi``, ``sub_index``
     - ``compute_us_aqi``, ``daily_us_aqi``, ``us_sub_index``
   * - Pollutants
     - PM10, PM2.5, NO2, SO2, CO, O3, NH3, Pb
     - PM2.5, PM10, O3, CO, SO2, NO2
   * - Averaging
     - 24 hours; 8 hours for CO and O3
     - PM 24 hours; O3 and CO highest 8-hour mean; SO2 and NO2 highest 1-hour
       value (SO2 24 hours above 304 ppb)
   * - Units
     - µg/m³, CO in mg/m³
     - PM µg/m³; O3 and CO ppm; SO2 and NO2 ppb
   * - Input precision
     - not truncated
     - truncated to the table's precision first
   * - Categories
     - Good 0-50, Satisfactory 51-100, Moderate 101-200, Poor 201-300,
       Very Poor 301-400, Severe 401-500
     - Good 0-50, Moderate 51-100, Unhealthy for Sensitive Groups 101-150,
       Unhealthy 151-200, Very Unhealthy 201-300, Hazardous 301 and above
   * - Overall AQI
     - Highest sub-index, with at least 3 pollutants, one of them PM2.5 or
       PM10, and at least 16 hours each [1]_
     - Highest sub-index; no minimum number of pollutants [6]_
   * - Above the top
     - Slope of the last band continues; not capped at 500 [4]_
     - Slope of the 301-500 band continues; above 300 is Hazardous [6]_
   * - Rounding
     - Half up, as the calculator displays it [4]_
     - Half up to an integer [6]_

India
-----

**Equation** (CUPS/82 p.7 and p.37 [1]_):
``Ip = (IHI - ILO) / (BHI - BLO) * (Cp - BLO) + ILO``.

vayuayan uses the continuous form of CPCB's calculator [4]_ and CUPS/82 p.37
("subtract one from ILO"): every band starts at the top of the band below,
so there are no gaps between bands. PM2.5 30-60 maps to 50-100 and the Severe
band is 100 over the width of the Very Poor band.

.. list-table:: Concentration bands used by vayuayan (AQI band in the header)
   :header-rows: 1
   :widths: 22 13 13 13 13 13 13

   * - Pollutant
     - 0-50
     - 50-100
     - 100-200
     - 200-300
     - 300-400
     - 400-500
   * - PM10 (24 h, µg/m³)
     - 0-50
     - 50-100
     - 100-250
     - 250-350
     - 350-430
     - 430-510
   * - PM2.5 (24 h, µg/m³)
     - 0-30
     - 30-60
     - 60-90
     - 90-120
     - 120-250
     - 250-380
   * - NO2 (24 h, µg/m³)
     - 0-40
     - 40-80
     - 80-180
     - 180-280
     - 280-400
     - 400-520
   * - O3 (8 h, µg/m³)
     - 0-50
     - 50-100
     - 100-168
     - 168-208
     - 208-748
     - 748-1288
   * - CO (8 h, mg/m³)
     - 0-1
     - 1-2
     - 2-10
     - 10-17
     - 17-34
     - 34-51
   * - SO2 (24 h, µg/m³)
     - 0-40
     - 40-80
     - 80-380
     - 380-800
     - 800-1600
     - 1600-2400
   * - NH3 (24 h, µg/m³)
     - 0-200
     - 200-400
     - 400-800
     - 800-1200
     - 1200-1800
     - 1800-2400
   * - Pb (24 h, µg/m³)
     - 0-0.5
     - 0.5-1
     - 1-2
     - 2-3
     - 3-3.5
     - 3.5-4

CPCB publishes no upper concentration for Severe; each last column is the top
of Very Poor plus the width of Very Poor, which reproduces the calculator's
slope. Pb has no calculator row, so its Severe band follows the same rule.

.. list-table:: Published table, CUPS/82 Table 3.11 p.35 [1]_
   :header-rows: 1
   :widths: 22 13 13 13 13 13 13 13 13

   * - Category
     - PM10
     - PM2.5
     - NO2
     - O3
     - CO
     - SO2
     - NH3
     - Pb
   * - Good
     - 0-50
     - 0-30
     - 0-40
     - 0-50
     - 0-1.0
     - 0-40
     - 0-200
     - 0-0.5
   * - Satisfactory
     - 51-100
     - 31-60
     - 41-80
     - 51-100
     - 1.1-2.0
     - 41-80
     - 201-400
     - 0.6-1.0
   * - Moderate
     - 101-250
     - 61-90
     - 81-180
     - 101-168
     - 2.1-10
     - 81-380
     - 401-800
     - 1.1-2.0
   * - Poor
     - 251-350
     - 91-120
     - 181-280
     - 169-208
     - 10.1-17
     - 381-800
     - 801-1200
     - 2.1-3.0
   * - Very Poor
     - 351-430
     - 121-250
     - 281-400
     - 209-748
     - 17.1-34
     - 801-1600
     - 1201-1800
     - 3.1-3.5
   * - Severe
     - 430+
     - 250+
     - 400+
     - 748+
     - 34+
     - 1600+
     - 1800+
     - 3.5+

Where CPCB's sources conflict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The band edges above follow vayuayan's choice in each case:

* **Band arithmetic.** The "About" page's worked example [2]_ gives 51 for
  PM2.5 31 and 75 for 45 on the published table; the calculator [4]_ gives
  51.67 and 75. CUPS/82 p.37 says to subtract one from ILO, and the calculator
  is the arithmetic CPCB ships, so vayuayan is continuous. vayuayan therefore
  differs by a few points from the 'About' example.
* **O3 above 748.** The calculator's own O3 formulas are inconsistent: band 5
  divides by 539 although the band is 540 wide, and band 6 uses ``C - 400``
  instead of ``C - 748``, so it jumps at 748. vayuayan keeps the published
  208-748 and 748-1288 bands.
* **O3 above 208.** CUPS/82 Table 3.11 has a footnote "One hourly monitoring
  (for mathematical calculation only)" and §3.3.4 uses 1-hour values above 208.
  The "About" page [2]_, "How is AQI calculated?" [3]_ and the calculator [4]_
  use 8-hour values, as does vayuayan.
* **Severe and the 500 cap.** CUPS/82 Tables 3.2 and 3.11 give a 0-500 scale,
  but pp.38-41 print values to 1765 and the calculator has no cap. CPCB's
  published daily series looks capped at 500 from 2018, so very high days can
  differ. vayuayan does not cap.
* **Published edges.** The "About" page has Satisfactory Pb 0.5-1.0, Poor CO
  10-17, Very Poor CO 17-34 and Very Poor NH3 1200-1800 where CUPS/82 has 0.6,
  10.1, 17.1 and 1201. The continuous form removes these differences.
* **Rounding.** No document gives a rule. vayuayan rounds half up, as the
  calculator's whole-number display does.

Two regenerated files that look like CPCB sources are not used:
``app.cpcbccr.com/ccr_docs/How_AQI_Calculated.pdf`` (generated by ReportLab in
July 2026, with text that is not in CPCB's PDF) and
``app.cpcbccr.com/ccr_docs/AQI%20-Calculator.xls`` (made by openpyxl in July
2026, with different breakpoints).

United States
-------------

**Equation** (40 CFR 58 App G §3.4; EPA TAD p.13 [6]_ [8]_):
``Ip = (IHi - ILo) / (BPHi - BPLo) * (Cp - BPLo) + ILo``, with Cp truncated to
the precision of the table and the result rounded to the nearest integer. The
PM2.5 bands are those of the 2024 rule [7]_.

.. list-table:: Breakpoints, 40 CFR 58 App G Table 2 and TAD Table 6 p.14
   :header-rows: 1
   :widths: 14 22 12 12 12 12 10 10 8

   * - AQI
     - Category
     - O3 8 h ppm
     - O3 1 h ppm
     - PM2.5 24 h µg/m³
     - PM10 24 h µg/m³
     - CO 8 h ppm
     - SO2 ppb
     - NO2 1 h ppb
   * - 0-50
     - Good
     - 0.000-0.054
     -
     - 0.0-9.0
     - 0-54
     - 0.0-4.4
     - 0-35 (1 h)
     - 0-53
   * - 51-100
     - Moderate
     - 0.055-0.070
     -
     - 9.1-35.4
     - 55-154
     - 4.5-9.4
     - 36-75 (1 h)
     - 54-100
   * - 101-150
     - Unhealthy for Sensitive Groups
     - 0.071-0.085
     - 0.125-0.164
     - 35.5-55.4
     - 155-254
     - 9.5-12.4
     - 76-185 (1 h)
     - 101-360
   * - 151-200
     - Unhealthy
     - 0.086-0.105
     - 0.165-0.204
     - 55.5-125.4
     - 255-354
     - 12.5-15.4
     - 186-304 (1 h)
     - 361-649
   * - 201-300
     - Very Unhealthy
     - 0.106-0.200
     - 0.205-0.404
     - 125.5-225.4
     - 355-424
     - 15.5-30.4
     - 305-604 (24 h)
     - 650-1249
   * - 301-500
     - Hazardous
     -
     - 0.405-0.604
     - 225.5-325.4
     - 425-604
     - 30.5-50.4
     - 605-1004 (24 h)
     - 1250-2049

Truncation (App G §3.4(a)(i)(A)): O3 3 decimals; PM2.5 and CO 1 decimal; PM10,
SO2 and NO2 integers. Above the last band Equation 1 continues with the last
two breakpoints.

**O3.** 8-hour O3 does not define the index above 300 (App G note 2). Above
0.200 ppm with no 1-hour value, vayuayan returns no AQI and warns, instead of
an AQI from the other pollutants. A 1-hour value below 0.125 ppm is
disregarded. If both exist the higher sub-index counts (TAD p.15).

**SO2.** Below 305 ppb the 1-hour table applies. With a 24-hour average of 305
ppb or more the 24-hour table applies. If the 1-hour is 305 ppb or more and the
24-hour is below 305 ppb the sub-index is 200 (TAD pp.15-16). With 1-hour 305
ppb or more and no 24-hour value, the TAD is silent and vayuayan uses 200 from
the EPA AQS code table [9]_.

Daily US AQI from raw readings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``daily_us_aqi`` averages the readings by hour, as ``daily_aqi`` does, and then
for each station and day:

.. list-table::
   :header-rows: 1
   :widths: 18 42 40

   * - Pollutant
     - Daily value
     - Completeness (assumption)
   * - PM2.5, PM10
     - 24-hour mean
     - ``min_hours`` (18) of 24 hours
   * - O3, CO
     - Highest 8-hour running mean, placed at its last hour
     - A window needs 6 of 8 hours; the day needs ``min_hours`` of its 24
       windows
   * - SO2, NO2
     - Highest 1-hour value; 24-hour SO2 mean for the upper bands
     - ``min_hours`` of 24 hours (both values for SO2)

Assumptions
~~~~~~~~~~~

The EPA sets no completeness rule for a daily AQI (neither the TAD [6]_ nor
Appendix G [8]_ states one). These are vayuayan's choices and can change:

* **Completeness** is 18 of 24, 75%, the NAAQS data-handling figure of 40 CFR
  50 Appendices K, N, S, T and U [10]_, used here by analogy. The zero
  substitution tests of those appendices are not applied.
* **Hourly values** from sub-hourly data are simple means. The EPA gives no
  rule for this.
* **Window placement.** CO and O3 8-hour windows are placed by their last hour,
  as in ``daily_aqi``. The EPA's O3 day of 17 windows (TAD p.24) is not used.
* **Unit conversion** at 25 °C and 760 mm Hg (40 CFR 50.3 [10]_) with 24.45
  L/mol. CPCB states no reference conditions for its gases, so converting its
  µg/m³ to ppb is an assumption.
* **No 1-hour O3** is computed by ``daily_us_aqi``: the daily rule uses the
  8-hour mean only, so a day above 0.200 ppm has no AQI.
* **Blank units** mean the unit of the US table.
* **The day** may end at another hour with ``day_ends_at``. The EPA uses
  midnight to midnight local standard time.

References
----------

All accessed 2026-11-09.

.. [1] CPCB, *National Air Quality Index*, Control of Urban Pollution Series
   CUPS/82/2014-15 (2014).
   https://cpcb.gov.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvRklOQUwtUkVQT1JUX0FRSV8ucGRm
.. [2] CPCB, "About National Air Quality Index".
   https://cpcb.nic.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvQWJvdXRfQVFJLnBkZg==
.. [3] CPCB, "How is AQI calculated?".
   https://cpcb.gov.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvSG93X0FRSV9DYWxjdWxhdGVkLnBkZg==
.. [4] CPCB, ``AQI-Calculator.xls``, Sheet1 D8-D20.
   https://cpcb.gov.in/upload/national-air-quality-index/AQI-Calculator.xls
.. [6] EPA, *Technical Assistance Document for the Reporting of Daily Air
   Quality*, EPA-403/B-26-003 (May 2026), which replaces EPA-454/B-24-002 (May
   2024) at this URL.
   https://document.airnow.gov/technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf
.. [7] EPA, *Reconsideration of the NAAQS for Particulate Matter*, 89 FR 16202
   (6 March 2024).
   https://www.govinfo.gov/content/pkg/FR-2024-03-06/pdf/2024-02637.pdf
.. [8] 40 CFR Part 58 Appendix G, as amended at 89 FR 16403.
   https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-58/appendix-Appendix%20G%20to%20Part%2058
.. [9] EPA AQS code table ``aqi_breakpoints.csv``.
   https://aqs.epa.gov/aqsweb/documents/codetables/aqi_breakpoints.csv
.. [10] 40 CFR Part 50: §§50.3, 50.4, 50.8, Appendices K, N, S, T and U.
   https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-50
