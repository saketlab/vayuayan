Command Line Interface
======================

The vayuayan command line interface provides convenient access to all package functionality.

Basic Usage
-----------

.. code-block:: bash

   vayuayan [command] [options]

To see all available commands:

.. code-block:: bash

   vayuayan --help

Data Discovery Commands
-----------------------

list_states
~~~~~~~~~~~

List all available states for AQI data.

.. code-block:: bash

   vayuayan list_states

list_cities
~~~~~~~~~~~

List cities available in a specific state.

.. code-block:: bash

   vayuayan list_cities "Maharashtra"

list_stations
~~~~~~~~~~~~~

List monitoring stations in a specific city.

.. code-block:: bash

   vayuayan list_stations "Mumbai"

Historical Data Commands
------------------------

city_data
~~~~~~~~~

Download yearly AQI data for a specific city.

.. code-block:: bash

   vayuayan city_data --city "Mumbai" --year 2024 --path "mumbai_aqi.csv"

**Parameters:**

- ``--city``: Name of the city (required)
- ``--year``: Year for data (required)
- ``--path``: Output file path (required)

station_data
~~~~~~~~~~~~

Download yearly AQI data for a specific monitoring station.

.. code-block:: bash

   vayuayan station_data --station_id "site_5964" --year 2024 --path "station_aqi.csv"

**Parameters:**

- ``--station_id``: ID of the monitoring station (required)
- ``--year``: Year for data (required)  
- ``--path``: Output file path (required)

Live Data Commands
------------------

locate_me
~~~~~~~~~

Get your current location based on IP address.

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

- ``--lat``: Latitude (optional, uses IP location if not provided)
- ``--lon``: Longitude (optional, uses IP location if not provided)

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
- ``--path``: Output file path (required)

PM2.5 Data Commands
-------------------

pm25
~~~~

Get PM2.5 data for geographic regions defined by GeoJSON files.

.. code-block:: bash

   # Analyze PM2.5 data for complete region
   vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11

   # Analyze PM2.5 data grouped by state
   vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11 --group_by state_name

   # Analyze PM2.5 data grouped by multiple columns (state and district)
   vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11 --group_by state_name,district_name


**Parameters:**

- ``--geojson_path``: Path to GeoJSON file defining the region (required)
- ``--year``: Year for data (required)
- ``--month``: Month (1-12) (optional, annual data if not provided)
- ``--combine``: Combine data within polygon (flag)

Help and Information
--------------------

cli-help
~~~~~~~~

Get detailed help for the CLI:

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

The CLI provides clear error messages and exit codes:

- **Exit code 0**: Success
- **Exit code 1**: General error or user interruption
- **Exit code 2**: Invalid arguments or usage

Common error scenarios and solutions:

- **Network timeout**: Check internet connection and try again
- **Invalid city/station**: Use list commands to find valid names/IDs
- **File permission errors**: Ensure write access to output directory
- **Invalid coordinates**: Check latitude (-90 to 90) and longitude (-180 to 180) ranges