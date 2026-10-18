.. meta::
   :description: vayuayan is a Python package and CLI that gets and analyzes air quality data: WUSTL ACAG satellite PM2.5 (1998-2024) and CPCB India AQI monitoring (historical and live).
   :keywords: air quality, PM2.5, pollution, AQI, CPCB, India, WUSTL ACAG, satellite, Python, air pollution data

vayuayan: Collect and Analyze Air Quality and Pollution Data
============================================================

A Python package that gets and analyzes air quality data from many sources:

.. image:: https://img.shields.io/pypi/v/vayuayan.svg
   :target: https://pypi.org/project/vayuayan/
   :alt: PyPI version

.. image:: https://img.shields.io/pypi/pyversions/vayuayan.svg
   :target: https://pypi.org/project/vayuayan/
   :alt: Python versions

.. image:: https://img.shields.io/github/license/saketlab/vayuayan.svg
   :target: https://github.com/saketlab/vayuayan/blob/main/python/LICENSE
   :alt: License

An R package with the same functions is documented at
`vayuayan.saketlab.org/R <https://vayuayan.saketlab.org/R/>`_.

Overview
--------

vayuayan gives a simple interface to pollution data from the Central Pollution Control Board (CPCB) of India and from WUSTL ACAG. It supports:

- **Air Quality Index (AQI) data**: Historical and live air quality measurements
- **PM2.5 data**: Fine particulate matter data for a geographic region in a GeoJSON file
- **Live data**: Live air quality parameters of monitoring stations
- **Location**: The package finds your location and the nearest station

Quick Start
-----------

Installation
~~~~~~~~~~~~

.. code-block:: bash

   pip install vayuayan

Basic Usage
~~~~~~~~~~~

.. code-block:: python

   from vayuayan import CPCBHistorical, CPCBLive, PM25Client

   # Initialize clients
   aqi_client = CPCBHistorical()
   live_client = CPCBLive()
   pm25_client = PM25Client()

   # Get available states
   states = aqi_client.get_state_list()
   print(states)

   # Get live AQI data for your location
   location = live_client.get_system_location()
   nearest_station = live_client.get_nearest_station()
   live_data = live_client.get_live_aqi_data()

Command Line Interface
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # List available states
   vayuayan list_states

   # Get city data for Mumbai in 2024
   vayuayan city_data --city "Mumbai" --year 2024 --path "mumbai_aqi.csv"

   # Get live AQI data for your location
   vayuayan live_aqi --path "current_aqi.json"

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   quickstart
   cli_reference
   examples
   contributing

Jupyter Notebooks
==================

The ``notebooks/`` directory has interactive notebooks with examples:

.. toctree::
   :maxdepth: 1

   notebooks/README
   notebooks/01_getting_started
   notebooks/02_historical_data_analysis
   notebooks/03_live_monitoring
   notebooks/04_pm25_regional_analysis

API Reference
=============

.. toctree::
   :maxdepth: 2

   api_reference

Release History
===============

.. toctree::
   :maxdepth: 1

   history


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

