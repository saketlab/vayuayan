Command Line Interface
======================

``vayuayan`` shows air quality in India in the terminal. Run it with no command
for a menu, or use one of the commands below.

.. code-block:: bash

   vayuayan                     # open the menu
   vayuayan live                # air quality near you
   vayuayan live anand vihar    # one station; no quotes needed
   vayuayan live mumbai         # every station of a city, worst first
   vayuayan history powai 2025  # a year as a calendar heatmap
   vayuayan find anand vihar    # look up stations
   vayuayan --help

Commands
--------

live
~~~~

Show the current air quality.

.. code-block:: bash

   vayuayan live
   vayuayan live powai
   vayuayan live site_5112
   vayuayan live mumbai --state Maharashtra
   vayuayan live --lat 19.07 --lon 72.87

``PLACE`` is a station name, part of a name, a station ID or a city. A station
shows a panel with the AQI, the category, the main pollutant, the place, the
coordinates, the station ID and the time of the reading in IST. A city shows
all its stations, worst AQI first.

With no place, the command finds your approximate location from your IP
address and shows the nearest station that has a reading. Offline stations are
skipped. If no station has a fresh reading, it shows the nearest older one and
says so.

.. note::

   ``vayuayan live`` with no place sends your IP address to
   `ip-api.com <http://ip-api.com>`_. The IP address is never shown or stored.
   Give a place, or ``--lat`` and ``--lon``, to avoid the lookup.

Options: ``--city``, ``--state`` to narrow a name; ``--lat`` and ``--lon``
instead of your IP location.

**The state of a reading.** Each reading is exactly one of:

.. list-table::
   :header-rows: 1
   :widths: 15 60 10

   * - Status
     - Meaning
     - Exit code
   * - ``live``
     - CPCB has an AQI at most 3 hours old.
     - 0
   * - ``stale``
     - CPCB's latest AQI is more than 3 hours old, or has no time.
     - 0
   * - ``offline``
     - The station is not reporting, or is not in the feed.
     - 5
   * - ``no_reading``
     - The station reported at a known time, but with no AQI.
     - 5
   * - ``fetch_failed``
     - The feed could not be fetched. This says nothing about the station.
     - 6

**What the pollutant numbers mean.** The values in CPCB's live feed are AQI
sub-indices on the 0-500 scale, not concentrations in µg/m³. The table labels
them that way:

- *24-hour avg* is the feed's ``avg``. The AQI is the highest of these.
- *Latest hour* is ``Hourly_sub_index``.
- *Lowest hour* and *Highest hour* are ``min`` and ``max``.

This was checked by comparing the feed with CPCB's report export for one
station and period. Concentrations of 13.57 to 15.17 µg/m³ of SO2 appear in the
feed as 17 to 19, which are their sub-indices. Carbon monoxide in the feed
reaches values such as 107, which cannot be mg/m³.

CPCB's feed can lag behind its other data. Check the time of the reading.

history
~~~~~~~

Show the daily AQI of a place.

.. code-block:: bash

   vayuayan history powai 2025
   vayuayan history powai 2025 --month 11
   vayuayan history powai 2025 --standard us
   vayuayan history delhi 2024 --save delhi.csv
   vayuayan history powai 2025 --computed --bulletin

A station or a city with a year shows a heatmap with months down and days
across. Each cell holds the number of its AQI category, so the map still reads
without colour. A dot means no data. Below it are the mean, the worst and best
days, the days with data and a count per category. A city also has a table by
month.

``YEAR`` defaults to the last complete year.

Options:

- ``--month``: one month, 1-12 or a name.
- ``--standard``: ``india`` (default) or ``us``. Each value is coloured on the
  scale of its own standard, and the output names the standard and shows its
  legend. ``india`` uses CPCB's published daily AQI. ``us`` computes the US AQI
  from a station's raw readings, which downloads much more data and needs one
  station.
- ``--computed``: compute India's AQI from raw readings instead of using the
  published value. CPCB validates its data before publishing, so the values can
  differ. Needs one station.
- ``--bulletin``: use days that end at 4 PM, like CPCB's daily bulletin. Implies
  ``--computed``.
- ``--save FILE``: write the days to a ``.csv``, ``.json`` or ``.parquet`` file, sorted ascending. Parquet needs ``pip install "vayuayan[parquet]"``. ``live``, ``find`` and ``stations`` take ``--save`` too.

**Readings for any period.** With ``--from`` and ``--to``, the command gives
measured concentrations from CPCB's report export, for one station or for all
stations of a city:

.. code-block:: bash

   vayuayan history delhi --from 2026-11-08 --to 2026-11-09 --hourly --save x.csv
   vayuayan history powai --from 2026-11-08 --to 2026-11-08 --every 15min

``--to`` with a date includes that whole day. ``--every`` takes ``15min``,
``30min``, ``hourly`` (default), ``4hour``, ``8hour`` or ``daily``.
``--pollutants`` takes a list such as ``PM2.5,NOx``. The terminal shows a summary
per pollutant; ``--save`` or ``--json`` give every reading.

find
~~~~

List the stations that match a name, with ID, name, city, state and coordinates.

.. code-block:: bash

   vayuayan find anand vihar
   vayuayan find powai --save powai.csv

stations
~~~~~~~~

List monitoring stations. The terminal shows 40 rows with a hint; ``--all`` or
``--limit`` change that.

.. code-block:: bash

   vayuayan stations --state Kerala
   vayuayan stations --city Delhi --save delhi.csv
   vayuayan stations --all

pm25
~~~~

Satellite PM2.5 for the polygons of a GeoJSON file.

.. code-block:: bash

   vayuayan pm25 districts.geojson 2023 --month 11
   vayuayan pm25 districts.geojson 2023 --group-by state_name,district_name

Options: ``--month``, ``--group-by``, ``--version`` (``V5``, ``V6`` or
``V6GL03``, the default) and ``--region`` (``GL``, ``AS``, ``EU``, ``NA`` or
``AF``).

Scripts and agents
------------------

Every command accepts these options, before or after its name:

- ``--json``: print one JSON document on stdout and nothing else. Progress and
  warnings go to stderr.
- ``--no-input``: never prompt. Prompts also never appear when stdin is not a
  terminal, or with ``--json``.
- ``--debug``: show the full error when something fails.

Each document has ``status``, ``command`` and ``message``, then the fields of
the command. ``status`` is ``ok``, ``ambiguous``, ``not_found``, ``no_data``,
``network_error``, ``location_unknown``, ``usage_error`` or ``error``.

.. code-block:: json

   {"status": "ambiguous", "command": "live", "message": "Several places match 'bandra kurla'.",
    "query": "bandra kurla",
    "matches": [{"kind": "station", "id": "site_5392", "name": "Bandra Kurla Complex, Mumbai - IITM",
                 "city": "Mumbai", "state": "Maharashtra", "latitude": 19.053536, "longitude": 72.84643}]}

When a station name is shared by several cities, live and history use the
city with the most stations and list the others in also_matches.

For a station, ``live`` has ``reading``; for a city, ``readings``; each reading
has its own ``status`` from the table above. A match has ``kind`` ``station``
or ``city``. ``find`` lists every match with status ``ok``, because several
matches are its normal answer. ``stations`` always returns every row with
``--json``.

Exit codes
----------

.. list-table::
   :header-rows: 1
   :widths: 10 70

   * - Code
     - Meaning
   * - 0
     - Success
   * - 1
     - Other error, such as a file that could not be written
   * - 2
     - Wrong command or options
   * - 3
     - Place or file not found
   * - 4
     - The name matches several places
   * - 5
     - The place exists but has no data
   * - 6
     - Network failure, CPCB down, or location lookup failed
   * - 130
     - Stopped with Ctrl-C

A city report that is only partly complete exits with 0. Its ``message`` says
so, and with ``--json`` the document also has ``partial`` and
``station_status``, the outcome of each station: ``ok``, ``no_data``,
``not_found``, ``ambiguous``, ``outage``, ``not_attempted`` or ``error``. When
CPCB is down before any station is fetched, the exit code is 6.

Colours
-------

The categories and colours of both standards come from ``vayuayan.constants``
and ``vayuayan.us_aqi``. Text on a coloured cell is black or white, whichever
has more contrast. The output honours ``NO_COLOR`` and uses no colour when
piped; category names and band numbers remain.
