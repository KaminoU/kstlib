"""Tests for config-driven resource limits."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from kstlib.limits import (
    DEFAULT_CIRCUIT_MAX_FAILURES,
    DEFAULT_CIRCUIT_RESET_TIMEOUT,
    DEFAULT_HALF_OPEN_MAX_CALLS,
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_MAX_ATTACHMENT_SIZE,
    DEFAULT_MAX_ATTACHMENTS,
    DEFAULT_MAX_CACHE_FILE_SIZE,
    DEFAULT_MAX_SOPS_CACHE_ENTRIES,
    DEFAULT_RAPI_JSON_INDENT,
    DEFAULT_RAPI_XML_PRETTY,
    DEFAULT_SHUTDOWN_TIMEOUT,
    HARD_MAX_ATTACHMENT_SIZE,
    HARD_MAX_ATTACHMENTS,
    HARD_MAX_CACHE_FILE_SIZE,
    HARD_MAX_CIRCUIT_FAILURES,
    HARD_MAX_CIRCUIT_RESET_TIMEOUT,
    HARD_MAX_HALF_OPEN_CALLS,
    HARD_MAX_HEARTBEAT_INTERVAL,
    HARD_MAX_SHUTDOWN_TIMEOUT,
    HARD_MAX_SOPS_CACHE_ENTRIES,
    HARD_MIN_CIRCUIT_FAILURES,
    HARD_MIN_HEARTBEAT_INTERVAL,
    HARD_MIN_SHUTDOWN_TIMEOUT,
    CacheLimits,
    MailLimits,
    RapiRenderConfig,
    ResilienceLimits,
    SopsLimits,
    get_cache_limits,
    get_mail_limits,
    get_rapi_render_config,
    get_resilience_limits,
    get_sops_limits,
)


class TestMailLimits:
    """Tests for MailLimits dataclass."""

    def test_max_attachment_size_display(self) -> None:
        """Display property returns human-readable size."""
        limits = MailLimits(max_attachment_size=25 * 1024 * 1024, max_attachments=10)
        assert "MiB" in limits.max_attachment_size_display or "25" in limits.max_attachment_size_display

    def test_frozen_dataclass(self) -> None:
        """MailLimits is immutable."""
        limits = MailLimits(max_attachment_size=1024, max_attachments=5)
        with pytest.raises(AttributeError):
            limits.max_attachment_size = 2048  # type: ignore[misc]


class TestCacheLimits:
    """Tests for CacheLimits dataclass."""

    def test_max_file_size_display(self) -> None:
        """Display property returns human-readable size."""
        limits = CacheLimits(max_file_size=50 * 1024 * 1024)
        assert "MiB" in limits.max_file_size_display or "50" in limits.max_file_size_display

    def test_frozen_dataclass(self) -> None:
        """CacheLimits is immutable."""
        limits = CacheLimits(max_file_size=1024)
        with pytest.raises(AttributeError):
            limits.max_file_size = 2048  # type: ignore[misc]


class TestSopsLimits:
    """Tests for SopsLimits dataclass."""

    def test_frozen_dataclass(self) -> None:
        """SopsLimits is immutable."""
        limits = SopsLimits(max_cache_entries=64)
        with pytest.raises(AttributeError):
            limits.max_cache_entries = 128  # type: ignore[misc]


class TestGetMailLimits:
    """Tests for get_mail_limits function."""

    def test_defaults_when_no_config(self) -> None:
        """Use defaults when no config is provided."""
        limits = get_mail_limits(config={})
        assert limits.max_attachment_size == DEFAULT_MAX_ATTACHMENT_SIZE
        assert limits.max_attachments == DEFAULT_MAX_ATTACHMENTS

    def test_reads_from_config(self) -> None:
        """Read limits from config mapping."""
        config = {
            "mail": {
                "limits": {
                    "max_attachment_size": "10M",
                    "max_attachments": 15,
                }
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachment_size == 10 * 1024 * 1024
        assert limits.max_attachments == 15

    def test_clamps_to_hard_max_attachment_size(self) -> None:
        """Clamp attachment size to hard maximum."""
        config = {
            "mail": {
                "limits": {
                    "max_attachment_size": "100M",  # Exceeds hard limit
                }
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachment_size == HARD_MAX_ATTACHMENT_SIZE

    def test_clamps_to_hard_max_attachments(self) -> None:
        """Clamp attachment count to hard maximum."""
        config = {
            "mail": {
                "limits": {
                    "max_attachments": 100,  # Exceeds hard limit
                }
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachments == HARD_MAX_ATTACHMENTS

    def test_clamps_attachments_minimum_to_one(self) -> None:
        """Ensure at least 1 attachment is allowed."""
        config = {
            "mail": {
                "limits": {
                    "max_attachments": 0,
                }
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachments == 1

    def test_handles_invalid_attachment_size(self) -> None:
        """Fall back to default for invalid size string."""
        config = {
            "mail": {
                "limits": {
                    "max_attachment_size": "invalid",
                }
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachment_size == DEFAULT_MAX_ATTACHMENT_SIZE

    def test_handles_invalid_attachment_count(self) -> None:
        """Fall back to default for invalid count."""
        config = {
            "mail": {
                "limits": {
                    "max_attachments": "not_a_number",
                }
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachments == DEFAULT_MAX_ATTACHMENTS

    def test_handles_none_config(self) -> None:
        """Handle None config gracefully."""
        limits = get_mail_limits(config=None)
        assert limits.max_attachment_size == DEFAULT_MAX_ATTACHMENT_SIZE
        assert limits.max_attachments == DEFAULT_MAX_ATTACHMENTS


class TestGetCacheLimits:
    """Tests for get_cache_limits function."""

    def test_defaults_when_no_config(self) -> None:
        """Use defaults when no config is provided."""
        limits = get_cache_limits(config={})
        assert limits.max_file_size == DEFAULT_MAX_CACHE_FILE_SIZE

    def test_reads_from_config(self) -> None:
        """Read limits from config mapping."""
        config = {
            "cache": {
                "file": {
                    "max_file_size": "75M",
                }
            }
        }
        limits = get_cache_limits(config=config)
        assert limits.max_file_size == 75 * 1024 * 1024

    def test_clamps_to_hard_max(self) -> None:
        """Clamp file size to hard maximum."""
        config = {
            "cache": {
                "file": {
                    "max_file_size": "500M",  # Exceeds hard limit
                }
            }
        }
        limits = get_cache_limits(config=config)
        assert limits.max_file_size == HARD_MAX_CACHE_FILE_SIZE

    def test_handles_invalid_size(self) -> None:
        """Fall back to default for invalid size string."""
        config = {
            "cache": {
                "file": {
                    "max_file_size": "invalid",
                }
            }
        }
        limits = get_cache_limits(config=config)
        assert limits.max_file_size == DEFAULT_MAX_CACHE_FILE_SIZE

    def test_handles_none_config(self) -> None:
        """Handle None config gracefully."""
        limits = get_cache_limits(config=None)
        assert limits.max_file_size == DEFAULT_MAX_CACHE_FILE_SIZE


class TestGetSopsLimits:
    """Tests for get_sops_limits function."""

    def test_defaults_when_no_config(self) -> None:
        """Use defaults when no config is provided."""
        limits = get_sops_limits(config={})
        assert limits.max_cache_entries == DEFAULT_MAX_SOPS_CACHE_ENTRIES

    def test_reads_from_config(self) -> None:
        """Read limits from config mapping."""
        config = {
            "secrets": {
                "sops": {
                    "max_cache_entries": 128,
                }
            }
        }
        limits = get_sops_limits(config=config)
        assert limits.max_cache_entries == 128

    def test_clamps_to_hard_max(self) -> None:
        """Clamp cache entries to hard maximum."""
        config = {
            "secrets": {
                "sops": {
                    "max_cache_entries": 1000,  # Exceeds hard limit
                }
            }
        }
        limits = get_sops_limits(config=config)
        assert limits.max_cache_entries == HARD_MAX_SOPS_CACHE_ENTRIES

    def test_clamps_minimum_to_one(self) -> None:
        """Ensure at least 1 cache entry is allowed."""
        config = {
            "secrets": {
                "sops": {
                    "max_cache_entries": 0,
                }
            }
        }
        limits = get_sops_limits(config=config)
        assert limits.max_cache_entries == 1

    def test_handles_invalid_entries(self) -> None:
        """Fall back to default for invalid entries."""
        config = {
            "secrets": {
                "sops": {
                    "max_cache_entries": "not_a_number",
                }
            }
        }
        limits = get_sops_limits(config=config)
        assert limits.max_cache_entries == DEFAULT_MAX_SOPS_CACHE_ENTRIES

    def test_handles_none_config(self) -> None:
        """Handle None config gracefully."""
        limits = get_sops_limits(config=None)
        assert limits.max_cache_entries == DEFAULT_MAX_SOPS_CACHE_ENTRIES


class TestGetNestedEdgeCases:
    """Tests for edge cases in config traversal."""

    def test_non_mapping_in_path(self) -> None:
        """Handle non-mapping values in traversal path."""
        config = {
            "mail": "not_a_dict",  # Should cause traversal to fail gracefully
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachment_size == DEFAULT_MAX_ATTACHMENT_SIZE

    def test_partial_config_path(self) -> None:
        """Handle partially missing config paths."""
        config: dict[str, dict[str, str]] = {
            "mail": {
                # Missing "limits" key
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachment_size == DEFAULT_MAX_ATTACHMENT_SIZE

    def test_deeply_nested_none(self) -> None:
        """Handle None at various levels of nesting."""
        config = {
            "mail": {
                "limits": None,
            }
        }
        limits = get_mail_limits(config=config)
        assert limits.max_attachment_size == DEFAULT_MAX_ATTACHMENT_SIZE


class TestResilienceLimits:
    """Tests for ResilienceLimits dataclass."""

    def test_frozen_dataclass(self) -> None:
        """ResilienceLimits is immutable."""
        limits = ResilienceLimits(
            heartbeat_interval=10.0,
            shutdown_timeout=30.0,
            circuit_max_failures=5,
            circuit_reset_timeout=60.0,
            circuit_half_open_calls=1,
            watchdog_timeout=30.0,
        )
        with pytest.raises(AttributeError):
            limits.heartbeat_interval = 20.0  # type: ignore[misc]


class TestGetResilienceLimits:
    """Tests for get_resilience_limits function."""

    def test_defaults_when_no_config(self) -> None:
        """Use defaults when no config is provided."""
        limits = get_resilience_limits(config={})
        assert limits.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL
        assert limits.shutdown_timeout == DEFAULT_SHUTDOWN_TIMEOUT
        assert limits.circuit_max_failures == DEFAULT_CIRCUIT_MAX_FAILURES
        assert limits.circuit_reset_timeout == DEFAULT_CIRCUIT_RESET_TIMEOUT
        assert limits.circuit_half_open_calls == DEFAULT_HALF_OPEN_MAX_CALLS

    def test_reads_from_config(self) -> None:
        """Read limits from config mapping."""
        config = {
            "resilience": {
                "heartbeat": {"interval": 15},
                "shutdown": {"timeout": 45},
                "circuit_breaker": {
                    "max_failures": 3,
                    "reset_timeout": 90,
                    "half_open_max_calls": 2,
                },
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.heartbeat_interval == 15.0
        assert limits.shutdown_timeout == 45.0
        assert limits.circuit_max_failures == 3
        assert limits.circuit_reset_timeout == 90.0
        assert limits.circuit_half_open_calls == 2

    def test_clamps_to_hard_maximums(self) -> None:
        """Clamp values to hard maximums."""
        config = {
            "resilience": {
                "heartbeat": {"interval": 9999},
                "shutdown": {"timeout": 9999},
                "circuit_breaker": {
                    "max_failures": 9999,
                    "reset_timeout": 99999,
                    "half_open_max_calls": 9999,
                },
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.heartbeat_interval == HARD_MAX_HEARTBEAT_INTERVAL
        assert limits.shutdown_timeout == HARD_MAX_SHUTDOWN_TIMEOUT
        assert limits.circuit_max_failures == HARD_MAX_CIRCUIT_FAILURES
        assert limits.circuit_reset_timeout == HARD_MAX_CIRCUIT_RESET_TIMEOUT
        assert limits.circuit_half_open_calls == HARD_MAX_HALF_OPEN_CALLS

    def test_clamps_to_hard_minimums(self) -> None:
        """Clamp values to hard minimums."""
        config = {
            "resilience": {
                "heartbeat": {"interval": 0.001},
                "shutdown": {"timeout": 0.001},
                "circuit_breaker": {
                    "max_failures": 0,
                    "reset_timeout": 0.001,
                    "half_open_max_calls": 0,
                },
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.heartbeat_interval == HARD_MIN_HEARTBEAT_INTERVAL
        assert limits.shutdown_timeout == HARD_MIN_SHUTDOWN_TIMEOUT
        assert limits.circuit_max_failures == HARD_MIN_CIRCUIT_FAILURES

    def test_handles_invalid_heartbeat_interval(self) -> None:
        """Fall back to default for invalid heartbeat interval."""
        config = {
            "resilience": {
                "heartbeat": {"interval": "not_a_number"},
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL

    def test_handles_invalid_shutdown_timeout(self) -> None:
        """Fall back to default for invalid shutdown timeout."""
        config = {
            "resilience": {
                "shutdown": {"timeout": "invalid"},
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.shutdown_timeout == DEFAULT_SHUTDOWN_TIMEOUT

    def test_handles_invalid_circuit_max_failures(self) -> None:
        """Fall back to default for invalid circuit max failures."""
        config = {
            "resilience": {
                "circuit_breaker": {"max_failures": "invalid"},
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.circuit_max_failures == DEFAULT_CIRCUIT_MAX_FAILURES

    def test_handles_invalid_circuit_reset_timeout(self) -> None:
        """Fall back to default for invalid circuit reset timeout."""
        config = {
            "resilience": {
                "circuit_breaker": {"reset_timeout": "invalid"},
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.circuit_reset_timeout == DEFAULT_CIRCUIT_RESET_TIMEOUT

    def test_handles_invalid_half_open_max_calls(self) -> None:
        """Fall back to default for invalid half_open_max_calls."""
        config = {
            "resilience": {
                "circuit_breaker": {"half_open_max_calls": "invalid"},
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.circuit_half_open_calls == DEFAULT_HALF_OPEN_MAX_CALLS

    def test_handles_none_config(self) -> None:
        """Handle None config gracefully."""
        limits = get_resilience_limits(config=None)
        assert limits.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL

    def test_handles_type_error_on_conversion(self) -> None:
        """Handle TypeError during value conversion."""
        config = {
            "resilience": {
                "heartbeat": {"interval": {"nested": "dict"}},  # Can't convert dict to float
                "shutdown": {"timeout": ["list", "value"]},  # Can't convert list to float
                "circuit_breaker": {
                    "max_failures": {"nested": "dict"},
                    "reset_timeout": ["list", "value"],
                    "half_open_max_calls": {"nested": "dict"},
                },
            }
        }
        limits = get_resilience_limits(config=config)
        assert limits.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL
        assert limits.shutdown_timeout == DEFAULT_SHUTDOWN_TIMEOUT
        assert limits.circuit_max_failures == DEFAULT_CIRCUIT_MAX_FAILURES
        assert limits.circuit_reset_timeout == DEFAULT_CIRCUIT_RESET_TIMEOUT
        assert limits.circuit_half_open_calls == DEFAULT_HALF_OPEN_MAX_CALLS


class TestLoadConfigHelper:
    """Tests for _load_config internal helper."""

    def test_returns_none_on_import_error(self) -> None:
        """Return None when kstlib.config cannot be imported."""
        from kstlib import limits as limits_mod

        with patch.object(limits_mod, "_load_config") as mock_load:
            mock_load.return_value = None
            limits = get_resilience_limits(config=None)

        # Should use defaults when config loading fails
        assert limits.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL


class TestGetNestedHelper:
    """Tests for _get_nested internal helper."""

    def test_returns_default_for_none_config(self) -> None:
        """Return default when config is None."""
        from kstlib.limits import _get_nested

        result = _get_nested(None, "any", "path", default="fallback")
        assert result == "fallback"

    def test_traverses_nested_path(self) -> None:
        """Traverse nested config paths correctly."""
        from kstlib.limits import _get_nested

        config = {"level1": {"level2": {"level3": "value"}}}
        result = _get_nested(config, "level1", "level2", "level3", default="default")
        assert result == "value"

    def test_returns_default_for_missing_key(self) -> None:
        """Return default when key is missing."""
        from kstlib.limits import _get_nested

        config: dict[str, dict[str, dict[str, str]]] = {"level1": {"level2": {}}}
        result = _get_nested(config, "level1", "level2", "missing", default="fallback")
        assert result == "fallback"


# ─────────────────────────────────────────────────────────────────────────────
# RapiRenderConfig tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRapiRenderConfig:
    """Tests for RapiRenderConfig dataclass."""

    def test_frozen_dataclass(self) -> None:
        """RapiRenderConfig is immutable."""
        config = RapiRenderConfig(json_indent=2, xml_pretty=True)
        with pytest.raises(AttributeError):
            config.json_indent = 4  # type: ignore[misc]

    def test_allows_none_json_indent(self) -> None:
        """Allows None for json_indent to disable pretty-printing."""
        config = RapiRenderConfig(json_indent=None, xml_pretty=False)
        assert config.json_indent is None


class TestGetRapiRenderConfig:
    """Tests for get_rapi_render_config function."""

    def test_defaults_when_no_config(self) -> None:
        """Use defaults when no config is provided."""
        config = get_rapi_render_config(config={})
        assert config.json_indent == DEFAULT_RAPI_JSON_INDENT
        assert config.xml_pretty == DEFAULT_RAPI_XML_PRETTY

    def test_reads_from_config(self) -> None:
        """Read settings from config mapping."""
        conf = {
            "rapi": {
                "pretty_render": {
                    "json": 4,
                    "xml": False,
                }
            }
        }
        config = get_rapi_render_config(config=conf)
        assert config.json_indent == 4
        assert config.xml_pretty is False

    def test_json_zero_disables_pretty(self) -> None:
        """Setting json to 0 disables pretty-printing."""
        conf = {
            "rapi": {
                "pretty_render": {
                    "json": 0,
                }
            }
        }
        config = get_rapi_render_config(config=conf)
        assert config.json_indent is None

    def test_json_clamped_to_bounds(self) -> None:
        """JSON indent is clamped to 1-8 range."""
        conf_high = {
            "rapi": {
                "pretty_render": {
                    "json": 100,
                }
            }
        }
        config_high = get_rapi_render_config(config=conf_high)
        assert config_high.json_indent == 8

        conf_low = {
            "rapi": {
                "pretty_render": {
                    "json": -5,
                }
            }
        }
        config_low = get_rapi_render_config(config=conf_low)
        assert config_low.json_indent == 1

    def test_handles_invalid_json_indent(self) -> None:
        """Fall back to default for invalid JSON indent."""
        conf = {
            "rapi": {
                "pretty_render": {
                    "json": "not_a_number",
                }
            }
        }
        config = get_rapi_render_config(config=conf)
        assert config.json_indent == DEFAULT_RAPI_JSON_INDENT

    def test_handles_none_config(self) -> None:
        """Handle None config gracefully."""
        config = get_rapi_render_config(config=None)
        assert config.json_indent == DEFAULT_RAPI_JSON_INDENT
        assert config.xml_pretty == DEFAULT_RAPI_XML_PRETTY

    def test_xml_truthy_values(self) -> None:
        """XML pretty accepts truthy values."""
        conf_true = {
            "rapi": {
                "pretty_render": {
                    "xml": True,
                }
            }
        }
        config_true = get_rapi_render_config(config=conf_true)
        assert config_true.xml_pretty is True

        conf_false = {
            "rapi": {
                "pretty_render": {
                    "xml": False,
                }
            }
        }
        config_false = get_rapi_render_config(config=conf_false)
        assert config_false.xml_pretty is False
