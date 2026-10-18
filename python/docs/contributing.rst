Contributing
============

We accept contributions. This checklist keeps the procedure short and consistent.

Quick setup
-----------

1. Fork the repository and clone your fork.
2. Make a development environment and install the extras:

   .. code-block:: bash

      python -m venv .venv
      source .venv/bin/activate  # Windows: .venv\Scripts\activate
      pip install -e ".[dev]"

Quality checks
--------------

Before you push your changes, run the standard quality checks:

.. code-block:: bash

   make format
   make lint
   make test
   make test-cov

Write small tests. Use mocks for remote services. Keep each change small.

Documentation
-------------

When you change the docs, make sure that the docs build without errors:

.. code-block:: bash

   make docs

Workflow
--------

- Make a feature branch: ``git checkout -b feature/your-topic``
- Make the change. Add tests and docs if necessary.
- Stage and commit the change with a short message
- Push to your fork and open a pull request. Describe the change and how you did a test of it.

Support
-------

In a bug report, give the Python version, the vayuayan version, and the OS. Also give the steps that cause the bug, and the errors. In a feature request, describe the use case. Also tell us if you can help to make the feature.

License
-------

When you contribute, you agree that your code uses the MIT License.