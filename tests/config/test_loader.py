"""Tests for the configuration loader module.

This module contains comprehensive tests for ConfigLoader class and
functional API, including file loading, includes, merging, and caching.
"""

# pylint: disable=protected-access,missing-function-docstring,import-outside-toplevel,unused-argument,line-too-long
# Reason: Tests exercise internals, rely on pytest fixtures, and inline imports for targeted behaviour.

import os
import pathlib
import time
from typing import Any

import pytest
from box import Box

from kstlib.config import (
    get_config,
    load_config,
    load_from_env,
    load_from_file,
    require_config,
)
from kstlib.config.exceptions import (
    ConfigCircularIncludeError,
    ConfigFileNotFoundError,
    ConfigFormatError,
    ConfigNotLoadedError,
)


def test_minimal_yaml(copy_fixture: Any, monkeypatch: Any, tmp_path: Any) -> None:
    copy_fixture("config", "minimal.yml", dest_name="kstlib.conf.yml")
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.meta.name == "kstlib"


def test_basic_include(copy_fixture: Any, monkeypatch: Any, tmp_path: Any) -> None:
    copy_fixture("config", "kstlib.conf.yml")
    copy_fixture("config", "included.json")
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.foo == "root"
    assert config.bar == "from_json"


def test_relative_include(copy_fixture: Any, monkeypatch: Any, tmp_path: Any) -> None:
    copy_fixture("config", "with_relative_include.yml", dest_name="kstlib.conf.yml")
    copy_fixture("config", "included.toml")
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.foo == "root"
    assert config.baz == "from_toml"


def test_absolute_include(tmp_path: Any, monkeypatch: Any) -> None:
    abs_ini = tmp_path / "included_absolute.ini"
    abs_ini.write_text("[section]\nmykey=abs_value\n", encoding="utf-8")
    abs_yml = tmp_path / "absolute_include.yml"
    abs_yml.write_text(f"foo: root\ninclude: {abs_ini}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = load_config(filename="absolute_include.yml")
    assert config.foo == "root"
    assert config.section.mykey == "abs_value"


def test_circular_include(copy_fixture: Any, monkeypatch: Any, tmp_path: Any) -> None:
    copy_fixture("config", "circular1.yml")
    copy_fixture("config", "circular2.yml")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigCircularIncludeError):
        load_config(filename="circular1.yml")


def test_missing_include(copy_fixture: Any, monkeypatch: Any, tmp_path: Any) -> None:
    missing_include = tmp_path / "kstlib.conf.yml"
    missing_include.write_text("include: missing_file.yml\nfoo: root\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigFileNotFoundError):
        load_config()


@pytest.mark.parametrize(
    "zone, expected_author",
    [
        ("config_dir_conf.yml", "TOTO - dir config"),
        ("home_conf.yml", "TITI - home config"),
        ("cwd_conf.yml", "MIKI - cwd config"),
    ],
    ids=["dir config", "home config", "cwd config"],
)
def test_zone_override(
    copy_fixture: Any, monkeypatch: Any, tmp_path: Any, zone: Any, expected_author: Any, cfg_loader: Any
) -> None:
    # Always put the fallback in place, but it's always overwritten here
    # Copy fallback to a location, so it always exists
    fallback = tmp_path / "package_fallback.yml"
    copy_fixture("config", "package_fallback.yml", dest_name=fallback)
    # Patch the fallback loader to use this file (optionally, sinon laisse package)
    monkeypatch.setattr(cfg_loader, "_load_default_config", lambda encoding: cfg_loader._load_yaml_file(fallback))

    # Simulate .config, home, cwd
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()

    # Always put config_dir_conf at .config (lowest user layer)
    copy_fixture("config", "config_dir_conf.yml", dest_name=config_dir / "kstlib.conf.yml")
    # Always put home_conf at ~ (unless zone == config_dir only)
    if zone != "config_dir_conf.yml":
        copy_fixture("config", "home_conf.yml", dest_name=home_dir / "kstlib.conf.yml")
    # Always put cwd_conf at cwd (unless testing home only)
    if zone == "cwd_conf.yml":
        copy_fixture("config", "cwd_conf.yml", dest_name=cwd_dir / "kstlib.conf.yml")

    # Patch home and cwd for the loader
    monkeypatch.setattr(pathlib.Path, "home", lambda: home_dir)
    monkeypatch.chdir(cwd_dir if zone == "cwd_conf.yml" else (home_dir if zone == "home_conf.yml" else config_dir))

    config = load_config()
    assert config.meta.author == expected_author


# ============================================================================
# NEW TESTS: Phase 1 + Phase 3 improvements
# ============================================================================


def test_load_config_from_arbitrary_path(tmp_path: Any) -> None:
    """Test loading config from explicit file path."""
    config_path = tmp_path / "custom" / "location" / "myconfig.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("app:\n  name: testapp\n  port: 8080\n", encoding="utf-8")

    config = load_config(path=config_path)
    assert config.app.name == "testapp"
    assert config.app.port == 8080


def test_load_config_path_not_found(tmp_path: Any) -> None:
    """Test that loading from non-existent path raises ConfigFileNotFoundError."""
    non_existent = tmp_path / "does_not_exist.yml"

    with pytest.raises(ConfigFileNotFoundError, match="Config file not found"):
        load_config(path=non_existent)


def test_strict_format_enforcement(tmp_path: Any) -> None:
    """Test that strict_format blocks includes with different formats."""
    main = tmp_path / "main.yml"
    inc_json = tmp_path / "include.json"

    inc_json.write_text('{"foo": "bar"}', encoding="utf-8")
    main.write_text(f"include: {inc_json.name}\nroot: true\n", encoding="utf-8")

    # Without strict: should work
    config = load_config(path=main, strict_format=False)
    assert config.foo == "bar"
    assert config.root is True

    # With strict: should fail
    with pytest.raises(ConfigFormatError, match="Include format mismatch"):
        load_config(path=main, strict_format=True)


def test_strict_format_same_format_ok(tmp_path: Any) -> None:
    """Test that strict_format allows includes with same format."""
    main = tmp_path / "main.yml"
    inc = tmp_path / "include.yml"

    inc.write_text("included_key: included_value\n", encoding="utf-8")
    main.write_text(f"include: {inc.name}\nroot_key: root_value\n", encoding="utf-8")

    # With strict: should work since both are .yml
    config = load_config(path=main, strict_format=True)
    assert config.included_key == "included_value"
    assert config.root_key == "root_value"


def test_unsupported_config_format(tmp_path: Any, cfg_loader: Any) -> None:
    """Test that unsupported file format raises ConfigFormatError."""
    xml_file = tmp_path / "config.xml"
    xml_file.write_text("<config></config>", encoding="utf-8")

    with pytest.raises(ConfigFormatError, match="Unsupported config file type"):
        cfg_loader._load_any_config_file(xml_file)


def test_get_config_singleton(copy_fixture: Any, tmp_path: Any, monkeypatch: Any, cfg_loader: Any) -> None:
    """Test that get_config returns the same instance."""
    copy_fixture("config", "minimal.yml", dest_name="kstlib.conf.yml")
    monkeypatch.chdir(tmp_path)

    # Clear singleton
    cfg_loader.clear_config()

    config1 = get_config()
    config2 = get_config()

    assert config1 is config2  # Same object in memory


def test_get_config_force_reload(tmp_path: Any, monkeypatch: Any, cfg_loader: Any) -> None:
    """Test that force_reload actually reloads the config."""
    conf_file = tmp_path / "kstlib.conf.yml"
    conf_file.write_text("test:\n  version: 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Clear singleton
    cfg_loader.clear_config()

    config1 = get_config()
    assert config1.test.version == 1

    # Modify the file
    conf_file.write_text("test:\n  version: 2\n", encoding="utf-8")

    config2 = get_config()  # Without reload
    assert config2.test.version == 1  # Still old value

    config3 = get_config(force_reload=True)  # With reload
    assert config3.test.version == 2  # New value


def test_get_config_max_age(tmp_path: Any, monkeypatch: Any, cfg_loader: Any) -> None:
    """Test that max_age triggers automatic refresh when the cache is stale."""
    conf_file = tmp_path / "kstlib.conf.yml"
    conf_file.write_text("test:\n  version: 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg_loader.clear_config()
    config1 = get_config(max_age=0.01)
    assert config1.test.version == 1

    time.sleep(0.02)
    conf_file.write_text("test:\n  version: 2\n", encoding="utf-8")

    config2 = get_config(max_age=0.01)
    assert config2.test.version == 2


def test_require_config_not_loaded(cfg_loader: Any) -> None:
    """Test that require_config raises if config not loaded."""
    cfg_loader.clear_config()

    with pytest.raises(ConfigNotLoadedError, match="Configuration not loaded yet"):
        require_config()


def test_require_config_after_load(copy_fixture: Any, monkeypatch: Any, tmp_path: Any, cfg_loader: Any) -> None:
    """Test that require_config works after config is loaded."""
    copy_fixture("config", "minimal.yml", dest_name="kstlib.conf.yml")
    monkeypatch.chdir(tmp_path)

    # Clear and load
    cfg_loader.clear_config()
    get_config()

    # Should not raise
    config = require_config()
    assert config is not None


def test_load_from_file_helper(tmp_path: Any) -> None:
    """Test load_from_file() convenience function."""
    config_path = tmp_path / "app.yml"
    config_path.write_text("db:\n  host: localhost\n  port: 5432\n", encoding="utf-8")

    config = load_from_file(config_path)
    assert config.db.host == "localhost"
    assert config.db.port == 5432

    # Test with string path
    config2 = load_from_file(str(config_path))
    assert config2.db.host == "localhost"


def test_load_from_file_strict_format(tmp_path: Any) -> None:
    """Test load_from_file() with strict_format."""
    main = tmp_path / "main.yml"
    inc = tmp_path / "inc.json"  # Different format

    inc.write_text('{"key": "value"}', encoding="utf-8")
    main.write_text(f"include: {inc.name}\n", encoding="utf-8")

    # Without strict: OK
    config1 = load_from_file(main, strict_format=False)
    assert config1.key == "value"

    # With strict: FAIL
    with pytest.raises(ConfigFormatError, match="Include format mismatch"):
        load_from_file(main, strict_format=True)


def test_load_from_env_success(tmp_path: Any, monkeypatch: Any) -> None:
    """Test load_from_env() with valid environment variable."""
    config_path = tmp_path / "env_config.yml"
    config_path.write_text("service:\n  name: myservice\n  port: 9000\n", encoding="utf-8")

    monkeypatch.setenv("CONFIG_PATH", str(config_path))

    config = load_from_env()
    assert config.service.name == "myservice"
    assert config.service.port == 9000


def test_load_from_env_custom_var(tmp_path: Any, monkeypatch: Any) -> None:
    """Test load_from_env() with custom environment variable name."""
    config_path = tmp_path / "custom.yml"
    config_path.write_text("custom: true\n", encoding="utf-8")

    monkeypatch.setenv("MY_APP_CONFIG", str(config_path))

    config = load_from_env("MY_APP_CONFIG")
    assert config.custom is True


def test_load_from_env_not_set() -> None:
    """Test that load_from_env() raises if env var not set."""
    # Make sure env var doesn't exist
    if "NONEXISTENT_VAR" in os.environ:
        del os.environ["NONEXISTENT_VAR"]

    with pytest.raises(ValueError, match="Environment variable 'NONEXISTENT_VAR' is not set"):
        load_from_env("NONEXISTENT_VAR")


def test_load_from_env_empty_string(monkeypatch: Any) -> None:
    """Test that load_from_env() raises if env var is empty."""
    monkeypatch.setenv("EMPTY_CONFIG", "")

    with pytest.raises(ValueError, match="is not set or empty"):
        load_from_env("EMPTY_CONFIG")


def test_tomli_import_error(tmp_path: Any, monkeypatch: Any, cfg_loader: Any) -> None:
    """Test that TOML loading fails gracefully without tomli."""
    # Mock tomli as None
    original_tomli = cfg_loader.tomli
    monkeypatch.setattr(cfg_loader, "tomli", None)

    toml_file = tmp_path / "test.toml"
    toml_file.write_text('foo = "bar"\n', encoding="utf-8")

    try:
        with pytest.raises(ConfigFormatError, match="TOML support requires"):
            cfg_loader._load_toml_file(toml_file)
    finally:
        # Restore original tomli
        monkeypatch.setattr(cfg_loader, "tomli", original_tomli)


def test_json_file_not_found(tmp_path: Any, cfg_loader: Any) -> None:
    """Test that loading a missing JSON file raises ConfigFileNotFoundError."""
    json_file = tmp_path / "nonexistent.json"

    with pytest.raises(ConfigFileNotFoundError, match="Config file not found"):
        cfg_loader._load_json_file(json_file)


def test_ini_file_not_found(tmp_path: Any, cfg_loader: Any) -> None:
    """Test that loading a missing INI file raises ConfigFileNotFoundError."""
    ini_file = tmp_path / "nonexistent.ini"

    with pytest.raises(ConfigFileNotFoundError, match="Config file not found"):
        cfg_loader._load_ini_file(ini_file)


def test_yaml_file_not_found(tmp_path: Any, cfg_loader: Any) -> None:
    """Test that loading a missing YAML file raises ConfigFileNotFoundError."""
    yaml_file = tmp_path / "nonexistent.yml"

    with pytest.raises(ConfigFileNotFoundError, match="Config file not found"):
        cfg_loader._load_yaml_file(yaml_file)


def test_toml_file_not_found(tmp_path: Any, cfg_loader: Any) -> None:
    """Test that loading a missing TOML file raises ConfigFileNotFoundError."""
    toml_file = tmp_path / "nonexistent.toml"

    with pytest.raises(ConfigFileNotFoundError, match="Config file not found"):
        cfg_loader._load_toml_file(toml_file)


def test_config_loader_custom_encoding(tmp_path: Any, monkeypatch: Any) -> None:
    """Test ConfigLoader with custom encoding."""
    import kstlib.config as cfg

    # Create a config file with UTF-8 content
    conf_file = tmp_path / "test.yml"
    conf_file.write_text("app:\n  name: 'Tëst Àpp'\n", encoding="utf-8")

    # Test with custom encoding
    loader = cfg.ConfigLoader(encoding="utf-8")
    config = loader.load_from_file(conf_file)

    assert config.app.name == "Tëst Àpp"


def test_config_loader_strict_format_in_constructor(tmp_path: Any) -> None:
    """Test ConfigLoader with strict_format set in constructor."""
    import kstlib.config as cfg

    # Create YAML files
    base_file = tmp_path / "base.yml"
    base_file.write_text("base: value1\n", encoding="utf-8")

    included_file = tmp_path / "included.yml"
    included_file.write_text("included: value2\n", encoding="utf-8")

    main_file = tmp_path / "main.yml"
    main_file.write_text("include: included.yml\nmain: value3\n", encoding="utf-8")

    # Test strict format enforcement
    loader = cfg.ConfigLoader(strict_format=True)
    config = loader.load_from_file(main_file)

    assert config.included == "value2"
    assert config.main == "value3"


def test_load_config_with_path_parameter(tmp_path: Any) -> None:
    """Test load_config() with explicit path parameter."""
    conf_file = tmp_path / "explicit.yml"
    conf_file.write_text("explicit:\n  test: true\n", encoding="utf-8")

    config = load_config(path=conf_file)

    assert config.explicit.test is True


def test_clear_config(cfg_loader: Any) -> None:
    """Test clear_config() function."""
    from kstlib.config import clear_config

    # Load a config first
    cfg_loader._default_loader._cache = Box({"test": "data"})

    # Clear
    clear_config()

    # Cache should be cleared
    assert cfg_loader._default_loader._cache is None


def test_config_loader_from_file_factory(tmp_path: Any) -> None:
    """Test ConfigLoader.from_file() factory method."""
    import kstlib.config as cfg

    conf_file = tmp_path / "factory.yml"
    conf_file.write_text("factory:\n  method: from_file\n", encoding="utf-8")

    config = cfg.ConfigLoader.from_file(conf_file)

    assert config.factory.method == "from_file"


def test_config_loader_from_env_factory(tmp_path: Any, monkeypatch: Any) -> None:
    """Test ConfigLoader.from_env() factory method."""
    import kstlib.config as cfg

    conf_file = tmp_path / "env_factory.yml"
    conf_file.write_text("env:\n  method: from_env\n", encoding="utf-8")

    monkeypatch.setenv("TEST_CONFIG_PATH", str(conf_file))

    config = cfg.ConfigLoader.from_env("TEST_CONFIG_PATH")

    assert config.env.method == "from_env"


def test_config_loader_from_cascading_factory(tmp_path: Any, monkeypatch: Any) -> None:
    """Test ConfigLoader.from_cascading() factory method."""
    import kstlib.config as cfg

    conf_file = tmp_path / "kstlib.conf.yml"
    conf_file.write_text("cascading:\n  method: from_cascading\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    config = cfg.ConfigLoader.from_cascading()

    assert config.cascading.method == "from_cascading"


def test_load_default_config_missing(monkeypatch: Any, tmp_path: Any, cfg_loader: Any) -> None:
    """Test _load_default_config when package config file is missing."""
    # Temporarily replace __file__ to point to a location without config
    fake_file = tmp_path / "fake_config.py"
    fake_file.write_text("# fake", encoding="utf-8")

    monkeypatch.setattr(cfg_loader, "__file__", str(fake_file))

    result = cfg_loader._load_default_config()

    # Should return empty dict when config file doesn't exist
    assert result == {}


def test_no_config_found_anywhere(tmp_path: Any, monkeypatch: Any, cfg_loader: Any) -> None:
    """Test that load_config raises error when no config is found anywhere."""
    # Create empty directories
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    config_dir = home_dir / ".config"
    config_dir.mkdir()
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()

    # Mock locations to empty directories
    monkeypatch.setattr(pathlib.Path, "home", lambda: home_dir)
    monkeypatch.chdir(cwd_dir)

    # Mock _load_default_config to return empty dict
    monkeypatch.setattr(cfg_loader, "_load_default_config", lambda encoding: {})

    with pytest.raises(ConfigFileNotFoundError, match="No configuration file found"):
        load_config("nonexistent.yml")


# ============================================================================
# ConfigLoader Class Tests (OOP API)
# ============================================================================


def test_config_loader_instance_load_method(tmp_path: Any, monkeypatch: Any) -> None:
    """Test ConfigLoader instance load() method with cascading."""
    import kstlib.config as cfg

    conf_file = tmp_path / "kstlib.conf.yml"
    conf_file.write_text("instance:\n  test: load_method\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    loader = cfg.ConfigLoader()
    config = loader.load()

    assert config.instance.test == "load_method"


def test_config_loader_instance_load_from_file(tmp_path: Any) -> None:
    """Test ConfigLoader instance load_from_file() method."""
    import kstlib.config as cfg

    conf_file = tmp_path / "direct.yml"
    conf_file.write_text("direct:\n  method: load_from_file\n", encoding="utf-8")

    loader = cfg.ConfigLoader()
    config = loader.load_from_file(conf_file)

    assert config.direct.method == "load_from_file"


def test_config_loader_instance_load_from_env(tmp_path: Any, monkeypatch: Any) -> None:
    """Test ConfigLoader instance load_from_env() method."""
    import kstlib.config as cfg

    conf_file = tmp_path / "env_test.yml"
    conf_file.write_text("env_test:\n  loaded: true\n", encoding="utf-8")

    monkeypatch.setenv("LOADER_TEST_PATH", str(conf_file))

    loader = cfg.ConfigLoader()
    config = loader.load_from_env("LOADER_TEST_PATH")

    assert config.env_test.loaded is True


def test_config_loader_instance_caching(tmp_path: Any) -> None:
    """Test that ConfigLoader instances can load configurations independently."""
    import kstlib.config as cfg

    conf_file = tmp_path / "cache_test.yml"
    conf_file.write_text("cache:\n  value: 1\n", encoding="utf-8")

    loader = cfg.ConfigLoader()

    # First load
    config1 = loader.load_from_file(conf_file)
    assert config1.cache.value == 1

    # Second load returns a new Box object (no caching in load_from_file)
    config2 = loader.load_from_file(conf_file)
    assert config1 is not config2  # Different objects
    assert config1.cache.value == config2.cache.value  # But same content


def test_config_loader_strict_format_inheritance(tmp_path: Any) -> None:
    """Test that strict_format is properly inherited in ConfigLoader."""
    import kstlib.config as cfg

    # Create YAML with TOML include (should fail in strict mode)
    toml_file = tmp_path / "included.toml"
    toml_file.write_text('[section]\nkey = "value"\n', encoding="utf-8")

    yaml_file = tmp_path / "main.yml"
    yaml_file.write_text("include: included.toml\nmain: true\n", encoding="utf-8")

    # Strict mode should fail
    strict_loader = cfg.ConfigLoader(strict_format=True)

    with pytest.raises(ConfigFormatError, match="Include format mismatch"):
        strict_loader.load_from_file(yaml_file)

    # Non-strict mode should work
    normal_loader = cfg.ConfigLoader(strict_format=False)
    config = normal_loader.load_from_file(yaml_file)

    assert config.main is True
    assert config.section.key == "value"


def test_config_loader_encoding_inheritance(tmp_path: Any) -> None:
    """Test that encoding is properly inherited in ConfigLoader."""
    import kstlib.config as cfg

    # Create file with special characters
    conf_file = tmp_path / "utf8_test.yml"
    conf_file.write_text("text: 'Spëcïal Chàrs 你好 🎉'\n", encoding="utf-8")

    loader = cfg.ConfigLoader(encoding="utf-8")
    config = loader.load_from_file(conf_file)

    assert "Spëcïal" in config.text
    assert "你好" in config.text
    assert "🎉" in config.text


def test_config_loader_multiple_instances(tmp_path: Any) -> None:
    """Test that multiple ConfigLoader instances work independently."""
    import kstlib.config as cfg

    file1 = tmp_path / "config1.yml"
    file1.write_text("name: config1\n", encoding="utf-8")

    file2 = tmp_path / "config2.yml"
    file2.write_text("name: config2\n", encoding="utf-8")

    loader1 = cfg.ConfigLoader()
    loader2 = cfg.ConfigLoader()

    config1 = loader1.load_from_file(file1)
    config2 = loader2.load_from_file(file2)

    # Each loader operates independently
    assert config1.name == "config1"
    assert config2.name == "config2"
    assert config1 is not config2  # Different config objects
    assert loader1 is not loader2  # Different loader instances


def test_config_loader_with_includes_and_strict(tmp_path: Any) -> None:
    """Test ConfigLoader handles includes correctly with strict mode."""
    import kstlib.config as cfg

    # Create YAML files (same format)
    base = tmp_path / "base.yml"
    base.write_text("base_key: base_value\n", encoding="utf-8")

    extended = tmp_path / "extended.yml"
    extended.write_text("extended_key: extended_value\n", encoding="utf-8")

    main = tmp_path / "main.yml"
    main.write_text("include:\n  - base.yml\n  - extended.yml\nmain_key: main_value\n", encoding="utf-8")

    loader = cfg.ConfigLoader(strict_format=True)
    config = loader.load_from_file(main)

    assert config.base_key == "base_value"
    assert config.extended_key == "extended_value"
    assert config.main_key == "main_value"


def test_config_loader_load_with_custom_filename(tmp_path: Any, monkeypatch: Any) -> None:
    """Test ConfigLoader.load() with custom filename."""
    import kstlib.config as cfg

    custom_file = tmp_path / "custom.conf.yml"
    custom_file.write_text("custom:\n  filename: true\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    loader = cfg.ConfigLoader()
    config = loader.load("custom.conf.yml")

    assert config.custom.filename is True


def test_config_loader_auto_discovery_cascading(tmp_path: Any, monkeypatch: Any) -> None:
    """Test that auto-discovery loads configuration via cascading search."""
    import kstlib.config as cfg

    conf_file = tmp_path / "kstlib.conf.yml"
    conf_file.write_text("auto:\n  source: cascade\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    loader = cfg.ConfigLoader()

    assert loader.config.auto.source == "cascade"


def test_config_loader_auto_discovery_env(tmp_path: Any, monkeypatch: Any) -> None:
    """Test that auto-discovery can pull configuration from environment variables."""
    import kstlib.config as cfg

    conf_file = tmp_path / "env.yml"
    conf_file.write_text("auto_env:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("AUTO_ENV_CONFIG", str(conf_file))

    loader = cfg.ConfigLoader(auto_source="env", auto_env_var="AUTO_ENV_CONFIG")

    assert loader.config.auto_env.enabled is True


def test_config_loader_auto_discovery_file(tmp_path: Any) -> None:
    """Test that auto-discovery loads from an explicit file path."""
    import kstlib.config as cfg

    conf_file = tmp_path / "explicit.yml"
    conf_file.write_text("auto_file:\n  path: true\n", encoding="utf-8")

    loader = cfg.ConfigLoader(auto_source="file", auto_path=conf_file)

    assert loader.config.auto_file.path is True


def test_config_loader_auto_discovery_file_requires_path() -> None:
    """Test that auto-discovery raises when a file source lacks a path."""
    import kstlib.config as cfg

    with pytest.raises(ConfigNotLoadedError, match="auto_path must be provided"):
        cfg.ConfigLoader(auto_source="file")


def test_config_loader_purge_cache_merge(tmp_path: Any) -> None:
    """Test that purge_cache controls whether fresh data replaces or merges cache."""
    import kstlib.config as cfg

    first = tmp_path / "first.yml"
    first.write_text("section:\n  value: 1\n  keep: true\n", encoding="utf-8")
    second = tmp_path / "second.yml"
    second.write_text("section:\n  value: 2\n  extra: merged\n", encoding="utf-8")

    loader = cfg.ConfigLoader(auto_discovery=False)
    loader.load_from_file(first)
    merged = loader.load_from_file(second, purge_cache=False)

    assert merged.section.value == 2
    assert merged.section.keep is True
    assert merged.section.extra == "merged"


def test_config_loader_rejects_auto_and_legacy_kwargs(tmp_path: Any) -> None:
    """Ensure providing both dataclass auto config and legacy kwargs fails."""
    import kstlib.config as cfg
    from kstlib.config.loader import AutoDiscoveryConfig

    auto = AutoDiscoveryConfig(
        enabled=False,
        source="file",
        filename="ignored.yml",
        env_var="IGNORED",
        path=tmp_path / "ignored.yml",
    )

    with pytest.raises(ValueError, match="cannot be combined"):
        cfg.ConfigLoader(auto=auto, auto_discovery=False)


def test_config_loader_rejects_unknown_auto_kwargs() -> None:
    """Ensure unexpected auto_* keywords raise TypeError."""
    import kstlib.config as cfg

    extra_kwargs: dict[str, Any] = {"auto_unknown": True}
    with pytest.raises(TypeError, match="Unexpected auto configuration keywords"):
        cfg.ConfigLoader(auto_discovery=False, **extra_kwargs)


def test_config_loader_auto_file_source_resolves_path(tmp_path: Any) -> None:
    """Ensure auto_path values are normalized to resolved Path objects."""
    import kstlib.config as cfg

    candidate = tmp_path / "custom.yml"
    loader = cfg.ConfigLoader(auto_discovery=False, auto_source="file", auto_path=candidate)

    assert loader.auto.source == "file"
    assert loader.auto.path == candidate.resolve()
