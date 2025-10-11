Installation
============

Requirements
------------

vayuayan requires Python 3.7 or higher and the following packages:

- requests>=2.25.0
- pandas>=1.3.0
- openpyxl==3.1.5
- urllib3>=1.26.0
- geopandas>=1.1.1
- geopy>=2.4.1
- rioxarray>=0.19.0
- xarray>=2025.9.0
- netCDF4>=1.7.2

Install from PyPI
-----------------

The recommended way to install vayuayan is via pip:

.. code-block:: bash

   pip install vayuayan

Development Installation
------------------------

If you want to contribute to vayuayan or install the latest development version:

.. code-block:: bash

   git clone https://github.com/saketkc/vayuayan.git
   cd vayuayan
   pip install -e ".[dev]"

This will install vayuayan in development mode with all development dependencies including:

- pytest (for testing)
- black (for code formatting)
- flake8 (for linting)
- mypy (for type checking)
- pre-commit (for git hooks)

Verification
------------

To verify your installation, run:

.. code-block:: python

   import vayuayan
   print(vayuayan.__version__)

Or test the command line interface:

.. code-block:: bash

   vayuayan --help