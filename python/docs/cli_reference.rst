Command Line Interface
======================

The vayuayan command line interface gives access to all functions of the package.

Basic Usage
-----------

.. code-block:: bash

   vayuayan [command] [options]

To show all the commands:

.. code-block:: bash

   vayuayan --help

Data Discovery Commands
-----------------------

list_states
~~~~~~~~~~~

List all the states that have AQI data.

.. code-block:: bash

   vayuayan list_states

list_cities
~~~~~~~~~~~

List the cities in a state. The state is a name or a code, in any case.

.. code-block:: bash

   vayuayan list_cities "Maharashtra"

list_stations
~~~~~~~~~~~~~

List the monitoring stations in a city, with their station IDs. The city is a
name or a code, in any case. The list has offline stations too, and stations
that are newer than the bundled station directory.

.. code-block:: bash

   vayuayan list_stations "Mumbai"

Historical Data Commands
------------------------

city_data
~~~~~~~~~

Download the AQI data of a city for one year.

.. code-block:: bash

   vayuayan city_data --city "Mumbai" --year 2024 --path "mumbai_aqi.csv"

**Parameters:**

- ``--city``: Name of the city (necessary)
- ``--year``: Year of the data (necessary)
- ``--path``: Output file path (necessary)

station_data
~~~~~~~~~~~~

Download the AQI data of a monitoring station for one year.

.. code-block:: bash

   vayuayan station_data --station_id "site_5964" --year 2024 --path "station_aqi.csv"

**Parameters:**

- ``--station_id``: ID of the monitoring station (necessary)
- ``--year``: Year of the data (necessary)
- ``--path``: Output file path (necessary)

daily_aqi
~~~~~~~~~

Compute the daily National AQI of a station from its raw 15-minute data,
with the CPCB breakpoints and rules (see ``vayuayan.aqi``).

.. code-block:: bash

   vayuayan daily_aqi --station_id "site_301" --year 2024 --path "daily_aqi.csv"

**Parameters:**

- ``--station_id``: ID of the monitoring station (necessary)
- ``--year``: Year of the data (optional. The default is the current year.)
- ``--path``: CSV file for the daily table, with the sub-index of each pollutant (optional)
- ``--bulletin``: Use the 24 hours that end at 4 PM, like CPCB's daily bulletin. The default is calendar days. CPCB validates its data before it publishes, so the values can differ from the published daily AQI.

Live Data Commands
------------------

locate_me
~~~~~~~~~

Get your current location from your IP address.

.. code-block:: bash

   vayuayan locate_me

nearest_station
~~~~~~~~~~~~~~~

Find the nearest air quality monitoring station.

.. code-block:: bash

   # Using IP-based geolocation
   vayuayan nearest_station

   # Using specific coordinates
   vayuayan nearest_station --lat 19.0760 --lon 72.8777

**Parameters:**

- ``--lat``: Latitude (optional. If you do not give it, the CLI uses the IP location.)
- ``--lon``: Longitude (optional. If you do not give it, the CLI uses the IP location.)

live_aqi
~~~~~~~~

Get live air quality data.

.. code-block:: bash

   # For your current location
   vayuayan live_aqi --path "current_aqi.json"

   # For specific coordinates
   vayuayan live_aqi --lat 19.0760 --lon 72.8777 --path "mumbai_aqi.json"

   # For specific station
   vayuayan live_aqi --station_id "site_5964" --path "station_aqi.json"

   # For specific date and time
   vayuayan live_aqi --date 2024-02-25 --hour 10 --path "historical_aqi.json"

**Parameters:**

- ``--lat``: Latitude (optional)
- ``--lon``: Longitude (optional)
- ``--station_id``: Station ID (optional)
- ``--date``: Date in YYYY-MM-DD format (optional)
- ``--hour``: Hour (0-23) (optional)
- ``--path``: Output file path (optional)

PM2.5 Data Commands
-------------------

pm25
~~~~

Get PM2.5 data for the geographic regions in a GeoJSON file.

.. code-block:: bash

   # Analyze PM2.5 data for complete region
   vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11

   # Analyze PM2.5 data grouped by state
   vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11 --group_by state_name

   # Analyze PM2.5 data grouped by multiple columns (state and district)
   vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11 --group_by state_name,district_name


**Parameters:**

- ``--geojson_path``: Path to the GeoJSON file of the region (necessary)
- ``--year``: Year of the data (necessary)
- ``--month``: Month (1-12) (optional. If you do not give it, the CLI uses annual data.)
- ``--group_by``: One column or comma-separated columns for the polygon groups (optional)
- ``--version``: Dataset version, ``V5`` (V5.GL.05.02, 1998-2023), ``V6`` (V6.GL.02.04, 1998-2023) or ``V6GL03`` (V6.GL.03, 1998-2024). Optional. The default is ``V6GL03``. Only ``V6`` has the Google Earth Engine fallback.

Help and Information
--------------------

cli-help
~~~~~~~~

Show the full help of the CLI:

.. code-block:: bash

   vayuayan --help

Examples
--------

Complete Workflow Example
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # 1. Find your location
   vayuayan locate_me

   # 2. Find nearest station
   vayuayan nearest_station

   # 3. Get current AQI
   vayuayan live_aqi --path "current_aqi.json"

   # 4. Explore available data
   vayuayan list_states
   vayuayan list_cities "Maharashtra"
   vayuayan list_stations "Mumbai"

   # 5. Download historical data
   vayuayan city_data --city "Mumbai" --year 2024 --path "mumbai_2024.csv"

Error Handling
--------------

The CLI gives clear error messages and exit codes:

- **Exit code 0**: Success
- **Exit code 1**: General error, or the user stopped the command
- **Exit code 2**: Invalid arguments

Frequent errors and their solutions:

- **Network timeout**: Make sure that the internet connection is on. Then run the command again.
- **Invalid city or station**: Use the list commands to find the correct names and IDs.
- **File permission errors**: Make sure that you can write to the output directory.
- **Invalid coordinates**: Make sure that the latitude is from -90 to 90 and the longitude is from -180 to 180.