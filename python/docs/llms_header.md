# vayuayan

> Python package to download and analyse air quality data: CPCB CAAQMS monitoring stations and OAQ low-cost sensors in India, and WUSTL ACAG satellite PM2.5 for the globe. It computes the CPCB National AQI and the US EPA AQI, and checks low-cost sensors against the EPA PM2.5 sensor targets. An R package with the same functions is at https://vayuayan.saketlab.org/R/.

## Data Sources

- CPCB: Central Pollution Control Board, India. Live and historical data of the CAAQMS stations: raw 15-minute readings, hourly and daily AQI, for stations and cities.
- OAQ: Open Air Quality (https://oaq.notf.in), low-cost sensor networks in India. Needs an API key.
- WUSTL ACAG: satellite-derived surface PM2.5, annual and monthly NetCDF grids, global or regional, for points and GeoJSON polygons.

## Installation and credentials

    pip install vayuayan              # Python 3.9+
    pip install "vayuayan[plot]"      # plot_* functions need matplotlib

- CPCB and WUSTL PM2.5 need no credentials.
- OAQ needs an API key. Ask the user for it and pass `OAQClient(api_key=...)`, or set `OAQ_API_KEY`. Never invent one.
- PM25Client downloads the NetCDF files directly. Google Earth Engine is only a fallback when that download fails, and needs `setup_earth_engine(project_id)`.

## Notes

- CPCB needs at least three pollutants, one of them PM2.5 or PM10, for an overall AQI; with fewer, `AQIResult.aqi` is None.
- Station and city tables from `CPCBHistorical.station_daily`, `city_daily` and `raw_readings` are long format.

## Command line

    vayuayan list_states
    vayuayan list_cities <state>
    vayuayan city_data --city <city> ...
    vayuayan station_data ...
    vayuayan daily_aqi ...
    vayuayan nearest_station
    vayuayan live_aqi --station <id> --date YYYY-MM-DD --hour 12
    vayuayan pm25 ...

Run `vayuayan <command> --help` for the arguments of each command.

## Links

- Docs: https://vayuayan.saketlab.org/python/
- R package: https://vayuayan.saketlab.org/R/
- Source: https://github.com/saketlab/vayuayan
