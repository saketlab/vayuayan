Quick Start Guide
=================

Basic Usage
-----------

Python API
~~~~~~~~~~~

First, import the necessary clients:

.. code-block:: python

   from vayuayan import CPCBHistorical, CPCBLive, PM25Client

AQI Data (Historical)
~~~~~~~~~~~~~~~~~~~~~~

Get historical air quality data:

.. code-block:: python

   # Initialize AQI client
   aqi_client = CPCBHistorical()

   # Get list of available states
   states = aqi_client.get_state_list()
   print(states)

   # Get cities in a state
   cities = aqi_client.get_city_list("Maharashtra")
   print(cities)

   # Get stations in a city
   stations = aqi_client.get_station_list("Mumbai")
   print(stations)

   # Download city-level data for a year
   aqi_client.download_past_year_AQI_data_cityLevel("Mumbai", "2024", "mumbai_aqi.csv")

Live AQI Data
~~~~~~~~~~~~~

Get real-time air quality data:

.. code-block:: python

   # Initialize Live AQI client
   live_client = CPCBLive()

   # Get your system location
   location = live_client.get_system_location()
   print(f"Your location: {location}")

   # Find nearest monitoring station
   nearest_station = live_client.get_nearest_station()
   print(f"Nearest station: {nearest_station}")

   # Get live AQI data
   live_data = live_client.get_live_aqi_data()
   print(live_data)

PM2.5 Data
~~~~~~~~~~

Get PM2.5 data for geographic regions:

.. code-block:: python

   # Initialize PM2.5 client
   pm25_client = PM25Client()

   # Get PM2.5 stats for a GeoJSON region
   stats = pm25_client.get_pm25_stats("region.geojson", 2024, 3)
   print(f"PM2.5 statistics: {stats}")

Command Line Interface
----------------------

List Available Data
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # List all states
   vayuayan list_states

   # List cities in Maharashtra
   vayuayan list_cities "Maharashtra"

   # List stations in Mumbai
   vayuayan list_stations "Mumbai"

Download Historical Data
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Download city-level AQI data
   vayuayan city_data --city "Mumbai" --year 2024 --path "mumbai_aqi.csv"

   # Download station-level AQI data
   vayuayan station_data --station_id "site_5964" --year 2024 --path "station_aqi.csv"

Live Data Access
~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Get your current location
   vayuayan locate_me

   # Find nearest station
   vayuayan nearest_station

   # Get live AQI data
   vayuayan live_aqi --path "current_aqi.json"

   # Get live AQI for specific coordinates
   vayuayan live_aqi --lat 19.0760 --lon 72.8777 --path "mumbai_aqi.json"

PM2.5 Regional Data
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Get PM2.5 data for a region
   vayuayan pm25 --geojson_path "region.geojson" --year 2024 --month 3 --combine

Error Handling
--------------

The library includes robust error handling:

.. code-block:: python

   from vayuayan import CPCBHistorical
   from vayuayan.exceptions import NetworkError

   client = CPCBHistorical()
   
   try:
       data = client.get_state_list()
   except NetworkError as e:
       print(f"Network error occurred: {e}")
   except Exception as e:
       print(f"Unexpected error: {e}")

Next Steps
----------

- Explore the :doc:`api_reference` for detailed API documentation
- Check out :doc:`examples` for more advanced usage patterns
- See :doc:`cli_reference` for complete command line options