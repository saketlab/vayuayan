Installation
============

Requirements
------------

vayuayan needs Python 3.9 or higher and these packages:

- requests>=2.25.0
- pandas>=2.0
- openpyxl==3.1.5
- urllib3>=1.26.0
- geopandas>=1.1.1
- rioxarray>=0.19.0
- xarray>=2025.9.0
- netCDF4>=1.7.2

Install from PyPI
-----------------

We recommend that you install vayuayan with pip:

.. code-block:: bash

   pip install vayuayan

Development Installation
------------------------

Install the latest development version from GitHub:

.. code-block:: bash

   pip install git+https://github.com/saketlab/vayuayan.git

To contribute to vayuayan, use these commands:

.. code-block:: bash

   git clone https://github.com/saketlab/vayuayan.git
   cd vayuayan
   pip install -e ".[dev]"

These commands install vayuayan in development mode with the development dependencies:

- pytest (for tests)
- ruff (to format and lint the code)
- mypy (to do a type check)

Verification
------------

To make sure that the installation is correct, run:

.. code-block:: python

   import vayuayan
   print(vayuayan.__version__)

Or do a test of the command line interface:

.. code-block:: bash

   vayuayan --help