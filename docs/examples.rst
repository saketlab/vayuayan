Examples
========

This section provides comprehensive examples of using vayuayan for various use cases.

Basic AQI Data Retrieval
-------------------------

Getting State and City Information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBHistorical

   # Initialize the client
   client = CPCBHistorical()

   # Get all available states
   states = client.get_state_list()
   print("Available states:")
   for state in states:
       print(f"- {state}")

   # Get cities in Maharashtra
   cities = client.get_city_list("Maharashtra")
   print("\nCities in Maharashtra:")
   for city in cities:
       print(f"- {city}")

   # Get stations in Mumbai
   stations = client.get_station_list("Mumbai")
   print("\nStations in Mumbai:")
   for station in stations:
       print(f"- {station}")

Downloading Historical Data
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBHistorical
   import pandas as pd

   client = CPCBHistorical()

   # Download city-level data
   try:
       data = client.download_past_year_aqi_data_city_level("Mumbai", "2024", "mumbai_2024.csv")
       
       # Read and analyze the data
       df = pd.read_csv("mumbai_2024.csv")
       print(f"Downloaded {len(df)} records for Mumbai 2024")
       print(df.head())
       
   except Exception as e:
       print(f"Error downloading data: {e}")

Live AQI Data
-------------

Location-Based AQI Monitoring
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBLive
   import json

   # Initialize live client
   live_client = CPCBLive()

   # Get your current location
   location = live_client.get_system_location()
   print(f"Your location: Lat {location['lat']}, Lon {location['lon']}")

   # Find nearest monitoring station
   nearest_station = live_client.get_nearest_station()
   print(f"Nearest station: {nearest_station}")

   # Get current AQI data
   current_aqi = live_client.get_live_aqi_data()
   
   # Save to file
   with open("current_aqi.json", "w") as f:
       json.dump(current_aqi, f, indent=2)
   
   print("Current AQI data saved to current_aqi.json")

Historical Live Data
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBLive
   from datetime import datetime, timedelta

   live_client = CPCBLive()

   # Get data for specific date and time
   target_date = "2024-03-15"
   target_hour = 14  # 2 PM

   historical_data = live_client.get_live_aqi_data(
       station_id="site_5964",
       date=target_date,
       hour=target_hour
   )

   print(f"AQI data for {target_date} at {target_hour}:00:")
   if historical_data:
       for param, value in historical_data.items():
           print(f"  {param}: {value}")

PM2.5 Regional Analysis
-----------------------

Basic Regional Stats
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import PM25Client
   import geopandas as gpd

   # Initialize PM2.5 client
   pm25_client = PM25Client()

   # Load a sample GeoJSON (you need to provide your own)
   geojson_path = "mumbai_boundaries.geojson"

   try:
       # Get PM2.5 statistics for the region
       stats = pm25_client.get_pm25_stats(geojson_path, 2024, 3)
       
       print(f"PM2.5 Statistics for March 2024:")
       print(f"  Mean: {stats['mean']:.2f} μg/m³")
       print(f"  Std Dev: {stats['std']:.2f} μg/m³")
       print(f"  Count: {stats['count']} pixels")
       
   except Exception as e:
       print(f"Error processing PM2.5 data: {e}")

Multi-Polygon Analysis
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import PM25Client
   import pandas as pd

   pm25_client = PM25Client()

   # Analyze each polygon separately
   geojson_path = "districts.geojson"
   
   try:
       results = pm25_client.get_pm25_stats_by_polygon(
           geojson_path, 
           2024, 
           3, 
           group_by="district_name"
       )
       
       # Convert to DataFrame for analysis
       df = pd.DataFrame(results)
       
       print("PM2.5 by District (March 2024):")
       print(df[['district_name', 'mean', 'std']].to_string(index=False))
       
       # Find districts with highest pollution
       worst_districts = df.nlargest(3, 'mean')
       print("\nMost polluted districts:")
       for _, row in worst_districts.iterrows():
           print(f"  {row['district_name']}: {row['mean']:.2f} μg/m³")
           
   except Exception as e:
       print(f"Error in multi-polygon analysis: {e}")

Advanced Use Cases
------------------

Air Quality Monitoring Dashboard
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBHistorical, CPCBLive
   import pandas as pd
   import time
   from datetime import datetime

   class AQIMonitor:
       def __init__(self):
           self.aqi_client = CPCBHistorical()
           self.live_client = CPCBLive()
           
       def monitor_location(self, duration_minutes=60, interval_minutes=5):
           """Monitor AQI for specified duration"""
           
           # Find nearest station
           station = self.live_client.get_nearest_station()
           station_id = station.get('station_id')
           
           print(f"Monitoring station: {station.get('station_name', station_id)}")
           print(f"Duration: {duration_minutes} minutes")
           print("-" * 50)
           
           monitoring_data = []
           end_time = time.time() + (duration_minutes * 60)
           
           while time.time() < end_time:
               try:
                   # Get current data
                   data = self.live_client.get_live_aqi_data(station_id=station_id)
                   
                   if data:
                       timestamp = datetime.now()
                       data['timestamp'] = timestamp
                       monitoring_data.append(data)
                       
                       print(f"{timestamp.strftime('%H:%M:%S')} - AQI: {data.get('AQI', 'N/A')}")
                   
                   # Wait for next reading
                   time.sleep(interval_minutes * 60)
                   
               except KeyboardInterrupt:
                   print("\nMonitoring stopped by user")
                   break
               except Exception as e:
                   print(f"Error: {e}")
                   time.sleep(30)  # Wait 30 seconds before retry
           
           # Save monitoring data
           if monitoring_data:
               df = pd.DataFrame(monitoring_data)
               filename = f"aqi_monitoring_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
               df.to_csv(filename, index=False)
               print(f"\nMonitoring data saved to {filename}")
           
           return monitoring_data

   # Usage
   monitor = AQIMonitor()
   # Monitor for 1 hour, checking every 5 minutes
   monitor.monitor_location(duration_minutes=60, interval_minutes=5)

Batch Data Processing
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBHistorical
   import pandas as pd
   from concurrent.futures import ThreadPoolExecutor
   import os

   class BatchProcessor:
       def __init__(self):
           self.client = CPCBHistorical()
           
       def download_city_data(self, city, year):
           """Download data for a single city"""
           try:
               filename = f"{city}_{year}.csv"
               self.client.download_past_year_AQI_data_city_level(city, str(year), filename)
               return {"city": city, "year": year, "status": "success", "file": filename}
           except Exception as e:
               return {"city": city, "year": year, "status": "error", "error": str(e)}
       
       def batch_download(self, cities, years, max_workers=3):
           """Download data for multiple cities and years"""
           
           tasks = [(city, year) for city in cities for year in years]
           results = []
           
           print(f"Starting batch download for {len(tasks)} tasks...")
           
           with ThreadPoolExecutor(max_workers=max_workers) as executor:
               # Submit all tasks
               futures = [executor.submit(self.download_city_data, city, year) 
                         for city, year in tasks]
               
               # Collect results
               for i, future in enumerate(futures):
                   result = future.result()
                   results.append(result)
                   
                   status = "✓" if result["status"] == "success" else "✗"
                   print(f"{status} {result['city']} {result['year']} - {result['status']}")
           
           # Summary
           successful = [r for r in results if r["status"] == "success"]
           failed = [r for r in results if r["status"] == "error"]
           
           print(f"\nBatch download complete:")
           print(f"  Successful: {len(successful)}")
           print(f"  Failed: {len(failed)}")
           
           return results

   # Usage
   processor = BatchProcessor()
   
   # Download data for multiple cities and years
   cities = ["Mumbai", "Delhi", "Bangalore", "Chennai"]
   years = [2022, 2023, 2024]
   
   results = processor.batch_download(cities, years)

Error Handling and Retry Logic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBLive
   from vayuayan.exceptions import NetworkError
   import time
   import logging

   # Set up logging
   logging.basicConfig(level=logging.INFO)
   logger = logging.getLogger(__name__)

   class RobustCPCBHistorical:
       def __init__(self, max_retries=3, retry_delay=5):
           self.client = CPCBLive()
           self.max_retries = max_retries
           self.retry_delay = retry_delay
       
       def get_data_with_retry(self, station_id=None, coords=None):
           """Get AQI data with retry logic"""
           
           for attempt in range(self.max_retries + 1):
               try:
                   if coords:
                       data = self.client.get_live_aqi_data(coords=coords)
                   else:
                       data = self.client.get_live_aqi_data(station_id=station_id)
                   
                   logger.info("Successfully retrieved AQI data")
                   return data
                   
               except NetworkError as e:
                   logger.warning(f"Network error on attempt {attempt + 1}: {e}")
                   
                   if attempt < self.max_retries:
                       logger.info(f"Retrying in {self.retry_delay} seconds...")
                       time.sleep(self.retry_delay)
                   else:
                       logger.error("Max retries exceeded")
                       raise
                       
               except Exception as e:
                   logger.error(f"Unexpected error: {e}")
                   raise
       
       def continuous_monitoring(self, interval_seconds=300):
           """Continuously monitor AQI with error recovery"""
           
           logger.info("Starting continuous monitoring...")
           
           while True:
               try:
                   data = self.get_data_with_retry()
                   
                   if data:
                       timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                       aqi = data.get('AQI', 'N/A')
                       logger.info(f"{timestamp} - AQI: {aqi}")
                   
                   time.sleep(interval_seconds)
                   
               except KeyboardInterrupt:
                   logger.info("Monitoring stopped by user")
                   break
               except Exception as e:
                   logger.error(f"Critical error: {e}")
                   logger.info(f"Waiting {self.retry_delay} seconds before restart...")
                   time.sleep(self.retry_delay)

   # Usage
   robust_client = RobustCPCBHistorical(max_retries=5, retry_delay=10)
   
   # Get data with automatic retry
   data = robust_client.get_data_with_retry()
   
   # Start continuous monitoring (Ctrl+C to stop)
   # robust_client.continuous_monitoring(interval_seconds=300)  # Every 5 minutes