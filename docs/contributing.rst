Contributing
============

We welcome contributions—this checklist keeps the process short and consistent.

Quick setup
-----------

1. Fork the repository and clone your fork.
2. Create a development environment and install extras:

   .. code-block:: bash

      python -m venv .venv
      source .venv/bin/activate  # Windows: .venv\Scripts\activate
      pip install -e ".[dev]"
      pre-commit install

Quality checks
--------------

Run the standard quality gates before pushing:

.. code-block:: bash

   make format
   make lint
   make test
   make test-cov

Write focused tests, mock remote services, and keep changes small.

Documentation
-------------

Verify the docs build cleanly when you touch them:

.. code-block:: bash

   make docs

Workflow
--------

- Work on a feature branch: ``git checkout -b feature/your-topic``
- Implement the change with tests and docs as needed
- Stage and commit with a concise message
- Push to your fork and open a pull request describing the change and validation

Support
-------

For bug reports include Python version, vayuayan version, OS, reproduction steps, and any errors. Feature requests should explain the use case and whether you can help implement it.

License
-------

By contributing you agree your code is released under the MIT License.