"""
Configuration Module Examples
==============================

This package contains comprehensive examples for the kstlib config module.

All examples are:
- Fully executable
- Self-contained
- Well-documented
- Ready for Sphinx/ReadTheDocs integration

Quick Start
-----------

Run individual examples::

    python examples/config/01_basic_usage.py
    python examples/config/02_includes.py
    # ... etc

Or run all examples::

    python examples/config/run_all_examples.py

Example Modules
---------------

.. autosummary::
   :toctree: _autosummary

   01_basic_usage
   02_includes
   03_cascading_search
   04_env_variable
   05_strict_format
   06_error_handling
   07_deep_merge

Configuration Files
-------------------

All example configuration files are located in the ``configs/`` subdirectory:

- ``basic.yml`` - Simple YAML configuration
- ``with_includes.yml`` - YAML with multi-format includes
- ``database.toml`` - TOML database configuration
- ``features.json`` - JSON feature flags
- ``server.ini`` - INI server configuration
- ``strict_yaml.yml`` - YAML-only strict mode demo
- ``merge_demo.yml`` - Deep merge demonstration

See Also
--------

- :mod:`kstlib.config` - Configuration module API
- :mod:`kstlib.exceptions` - Exception hierarchy
"""

# Note: This is an examples package, not a library module.
# Examples are meant to be executed as scripts, not imported.
# Therefore, no __all__ is needed.
