# Kstlib Configuration Examples - Quick Reference

## 🎯 What's in this directory?

Complete, executable examples demonstrating kstlib's configuration module features.

## 📝 Example Files

| File                       | Description                         | Key Features                         |
| -------------------------- | ----------------------------------- | ------------------------------------ |
| `01_basic_usage.py`      | Getting started with config loading | Load files, dot notation, Box object |
| `02_includes.py`         | Multi-format configuration          | YAML + TOML + JSON + INI includes    |
| `03_cascading_search.py` | Auto-discovery of configs           | Priority-based search & merging      |
| `04_env_variable.py`     | Environment-based loading           | Container/Docker friendly            |
| `05_strict_format.py`    | Format enforcement                  | Consistency validation               |
| `06_error_handling.py`   | Exception handling                  | All error scenarios                  |
| `07_deep_merge.py`       | Configuration merging               | Nested dict merge behavior           |
| `08_multi_environment.py`| Multi-environment patterns          | Dev/staging/prod config management   |
| `09_auto_discovery.py`   | Auto-discovery presets              | AutoDiscoveryConfig workflows        |

## 🚀 Quick Start

```bash
# Run individual example
python examples/config/01_basic_usage.py

# Run all examples
python examples/config/run_all_examples.py
```

## 🔗 Related Files

- `README.md` - Full documentation for this directory
- `configs/` - Example configuration files
- `run_all_examples.py` - Test runner

## ✅ All Examples Tested

All examples are executable and tested. Run `run_all_examples.py` to verify.
