# Configuration Module Examples

This directory contains practical, executable examples demonstrating the features of kstlib's configuration module.

## 📚 Examples Overview

Each example is self-contained, well-documented, and can be run independently.

### 01. Basic Usage (`01_basic_usage.py`)

Learn the fundamentals:

- Loading a configuration file
- Accessing values with dot notation
- Working with the Box object

```bash
python 01_basic_usage.py
```

### 02. Configuration with Includes (`02_includes.py`)

Multi-format configuration composition:

- Using the `include` key
- Merging YAML, TOML, JSON, and INI files
- Override behavior

```bash
python 02_includes.py
```

### 03. Cascading Search (`03_cascading_search.py`)

Automatic configuration discovery:

- Search order and priorities
- Location-based merging
- Singleton pattern

```bash
python 03_cascading_search.py
```

### 04. Environment Variables (`04_env_variable.py`)

Container-friendly configuration:

- Loading from environment variables
- Custom variable names
- Error handling

```bash
python 04_env_variable.py
```

### 05. Strict Format Mode (`05_strict_format.py`)

Format consistency enforcement:

- Strict format validation
- Format mismatch detection
- Use cases

```bash
python 05_strict_format.py
```

### 06. Error Handling (`06_error_handling.py`)

Comprehensive error scenarios:

- File not found
- Unsupported formats
- Circular includes
- Uninitialized config access

```bash
python 06_error_handling.py
```

### 07. Deep Merge (`07_deep_merge.py`)

Configuration merging behavior:

- Nested dictionary merging
- List replacement
- Override priorities

```bash
python 07_deep_merge.py
```

### 08. Multi-Environment Pattern (`08_multi_environment.py`)

Practical patterns for managing configurations across environments:

- Environment-specific loaders
- Factory helpers for quick setup
- Environment variable and cascading workflows

```bash
python 08_multi_environment.py
```

### 09. Auto-Discovery Presets (`09_auto_discovery.py`)

``AutoDiscoveryConfig`` in action:

- File-bound presets for deterministic loading
- Environment variable driven presets
- Manual presets that defer IO until later

```bash
python 09_auto_discovery.py
```

## 🚀 Running All Examples

Execute all examples in sequence:

```bash
python run_all_examples.py
```

This will run each example and display the results.

## 📁 Directory Structure

```text
examples/config/
├── README.md                    # This file
├── run_all_examples.py          # Run all examples
├── 01_basic_usage.py
├── 02_includes.py
├── 03_cascading_search.py
├── 04_env_variable.py
├── 05_strict_format.py
├── 06_error_handling.py
├── 07_deep_merge.py
├── 08_multi_environment.py
├── 09_auto_discovery.py
└── configs/                     # Example configuration files
    ├── basic.yml
    ├── with_includes.yml
    ├── database.toml
    ├── features.json
    ├── server.ini
    ├── strict_yaml.yml
    ├── strict_extended.yml
    ├── merge_demo.yml
    └── merge_base.yml
```

## 💡 Tips

1. **Run from project root**: Examples are designed to run from the project root directory
2. **Virtual environment**: Make sure kstlib is installed: `pip install -e .`
3. **Python version**: Requires Python 3.10+ for TOML support

## 🔗 Related Files

- [Quick Reference](QUICKREF.md) - Summary of all examples
- [Main Documentation](../../README.md) - Project overview
