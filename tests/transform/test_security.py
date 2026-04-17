"""Security tests for kstlib.transform."""

from __future__ import annotations

import threading
import time
import zlib
from typing import Any

import pytest

from kstlib.transform import chain as chain_module
from kstlib.transform.chain import DANGEROUS_MODULES, TransformChain
from kstlib.transform.config import (
    PatchConfig,
    PrimitiveConfig,
    TransformChainConfig,
    TransformConfig,
)
from kstlib.transform.exceptions import (
    CallableError,
    DecodeError,
    DecompressError,
    ParseError,
    TransformConfigError,
)
from kstlib.transform.primitives import (
    base64_decode,
    json_parse,
    xml_parse,
    zlib_decompress,
)
from kstlib.transform.validators import (
    MAX_INPUT_SIZE,
    validate_callable_module,
)

_CFG_B64 = PrimitiveConfig(name="base64")
_CFG_ZLIB = PrimitiveConfig(name="zlib")
_CFG_JSON = PrimitiveConfig(name="json")
_CFG_XML = PrimitiveConfig(name="xml")


# ============================================================================
# Synthetic helper module for the CALLABLE_TIMEOUT tests below.
#
# We register a fake module in sys.modules so that importlib.import_module
# (used by chain._apply_callable) can resolve "kstlib_test_callables:<name>"
# without depending on pytest's sys.path setup. The chain code does:
#     importlib.import_module(module_path)
# which checks sys.modules first, so registering a ModuleType instance
# there is the cleanest portable approach (works in any test runner,
# any rootdir, any importmode).
# ============================================================================

import sys as _sys  # noqa: E402
import types as _types  # noqa: E402

_TEST_CALLABLES_MODULE_NAME = "kstlib_test_callables"


def _fast_callable(data: Any, **_: Any) -> Any:
    """Return data unchanged immediately. Used to test the happy path."""
    return data


def _slow_callable(data: Any, **_: Any) -> Any:
    """Sleep 2 seconds, longer than the patched 0.1s test timeout."""
    time.sleep(2.0)
    return data


def _raising_callable(data: Any, **_: Any) -> Any:
    """Raise ValueError immediately. Used to test the exception path."""
    raise ValueError("intentional failure for test")


_test_callables_module = _types.ModuleType(_TEST_CALLABLES_MODULE_NAME)
_test_callables_module._fast_callable = _fast_callable  # type: ignore[attr-defined]
_test_callables_module._slow_callable = _slow_callable  # type: ignore[attr-defined]
_test_callables_module._raising_callable = _raising_callable  # type: ignore[attr-defined]
_sys.modules[_TEST_CALLABLES_MODULE_NAME] = _test_callables_module


class TestXmlSecurity:
    """XML security: XXE, billion laughs, DOCTYPE."""

    def test_doctype_with_external_entity_rejected(self) -> None:
        """DOCTYPE declarations with external entities are rejected by defusedxml."""
        malicious = '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root>&xxe;</root>'
        with pytest.raises(ParseError):
            xml_parse(malicious, _CFG_XML)

    def test_large_xml_rejected(self) -> None:
        """Oversized XML input is rejected."""
        large = "<root>" + "x" * (50 * 1024 * 1024 + 1) + "</root>"
        with pytest.raises(ParseError, match="exceeds limit"):
            xml_parse(large, _CFG_XML)


class TestZlibBomb:
    """Zlib bomb protection."""

    def test_high_ratio_rejected(self) -> None:
        """High decompression ratio is rejected."""
        # Compress highly repetitive data for high ratio
        bomb_data = b"\x00" * 10_000_000  # 10MB of zeros
        compressed = zlib.compress(bomb_data)
        # The ratio will be very high
        with pytest.raises(DecompressError, match="ratio"):
            zlib_decompress(compressed, _CFG_ZLIB)


class TestInputSizeLimits:
    """Input size validation."""

    def test_base64_oversized(self) -> None:
        """Oversized base64 input is rejected before decode."""
        huge = "A" * (MAX_INPUT_SIZE + 1)
        with pytest.raises(DecodeError, match="exceeds limit"):
            base64_decode(huge, _CFG_B64)

    def test_json_oversized(self) -> None:
        """Oversized JSON input is rejected before parse."""
        huge = '{"x": "' + "a" * (50 * 1024 * 1024) + '"}'
        with pytest.raises(ParseError, match="exceeds limit"):
            json_parse(huge, _CFG_JSON)


class TestCallableWhitelist:
    """Callable module whitelist enforcement."""

    def test_module_not_in_whitelist(self) -> None:
        """Module not in whitelist raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="not in allowed_callable_modules"):
            validate_callable_module("os:system", frozenset({"safe.module"}))

    def test_module_in_whitelist(self) -> None:
        """Module in whitelist passes."""
        validate_callable_module("safe.module:func", frozenset({"safe.module"}))

    def test_submodule_in_whitelist(self) -> None:
        """Submodule of whitelisted parent passes."""
        validate_callable_module("safe.module.sub:func", frozenset({"safe.module"}))

    def test_empty_whitelist_blocks_all(self) -> None:
        """Empty whitelist blocks all external callables."""
        with pytest.raises(TransformConfigError, match="not in allowed_callable_modules"):
            validate_callable_module("any.module:func", frozenset())

    def test_partial_name_no_match(self) -> None:
        """Module name that starts similarly but is different is blocked."""
        with pytest.raises(TransformConfigError):
            validate_callable_module("safe.modulex:func", frozenset({"safe.module"}))


class TestExceptionSafety:
    """Exception messages must not leak data content."""

    def test_base64_error_no_data_leak(self) -> None:
        """DecodeError message does not contain the input data."""
        secret_data = "SECRET_TOKEN_12345_abcdef"
        try:
            base64_decode(secret_data, _CFG_B64)
        except DecodeError as exc:
            assert secret_data not in str(exc)
            assert "SECRET" not in str(exc)

    def test_json_error_no_data_leak(self) -> None:
        """ParseError message does not contain the input data."""
        secret_data = '{"password": "super_secret_123"} invalid'
        try:
            json_parse(secret_data, _CFG_JSON)
        except ParseError as exc:
            assert "super_secret" not in str(exc)
            assert "password" not in str(exc)

    def test_zlib_error_no_data_leak(self) -> None:
        """DecompressError message does not contain the input data."""
        secret_bytes = b"SECRET_BINARY_DATA_xyz"
        try:
            zlib_decompress(secret_bytes, _CFG_ZLIB)
        except DecompressError as exc:
            assert "SECRET" not in str(exc)


class TestValidatorEdgeCases:
    """Edge cases in validators."""

    def test_mapping_empty_key_rejected(self) -> None:
        """Empty mapping key raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="key must not be empty"):
            PatchConfig(replace={"": "value"})

    def test_mapping_oversized_key(self) -> None:
        """Oversized mapping key raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="key too long"):
            PatchConfig(replace={"x" * 5000: "v"})

    def test_mapping_oversized_value(self) -> None:
        """Oversized mapping value raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="value too long"):
            PatchConfig(replace={"k": "x" * 5000})

    def test_callable_target_no_colon(self) -> None:
        """Callable target without colon raises TransformConfigError."""
        with pytest.raises(TransformConfigError, match="Invalid callable target"):
            PatchConfig(callable="no_colon_here")

    def test_hex_string_invalid(self) -> None:
        """Invalid hex string in zlib options raises TransformConfigError."""
        with pytest.raises(TransformConfigError):
            PrimitiveConfig(name="zlib", options={"prepend_bytes": "ghij"})


# ============================================================================
# CALLABLE_TIMEOUT enforcement
# ============================================================================


def _build_callable_chain(target: str) -> TransformChain:
    """Build a minimal chain that runs a callable patch on bytes input.

    Forward = bytes (decode utf-8 -> str), patch = callable, backward = bytes.
    The chain takes string input and applies the callable to it.
    """
    return TransformChain(
        TransformChainConfig(
            name="timeout_test",
            forward=(PrimitiveConfig(name="bytes"),),
            patch=PatchConfig(callable=target),
        ),
        allowed_modules=frozenset({_TEST_CALLABLES_MODULE_NAME}),
    )


class TestCallableTimeout:
    """Hard wall-clock timeout for patch callables.

    All tests patch ``kstlib.transform.chain.CALLABLE_TIMEOUT`` to 0.1
    seconds via monkeypatch. Never use the real 30s default in tests.
    """

    def test_callable_completes_in_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A fast callable completes well within the timeout window."""
        monkeypatch.setattr(chain_module, "CALLABLE_TIMEOUT", 0.1)
        chain = _build_callable_chain(
            "kstlib_test_callables:_fast_callable",
        )
        # The chain forward decodes b"data" -> "data", patch returns it unchanged
        assert chain.patch("data") == "data"

    def test_callable_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A callable that sleeps longer than CALLABLE_TIMEOUT raises CallableError."""
        monkeypatch.setattr(chain_module, "CALLABLE_TIMEOUT", 0.1)
        chain = _build_callable_chain(
            "kstlib_test_callables:_slow_callable",
        )
        start = time.monotonic()
        with pytest.raises(CallableError, match="timed out after"):
            chain.patch("data")
        elapsed = time.monotonic() - start
        # The error must fire close to the timeout, not the full 2 second sleep.
        # Allow generous margin for slow CI runners.
        assert elapsed < 1.0, f"timeout fired too late: {elapsed:.3f}s"

    def test_callable_raises_before_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A callable that raises is wrapped in CallableError (existing behavior)."""
        monkeypatch.setattr(chain_module, "CALLABLE_TIMEOUT", 0.1)
        chain = _build_callable_chain(
            "kstlib_test_callables:_raising_callable",
        )
        with pytest.raises(CallableError, match="intentional failure"):
            chain.patch("data")

    def test_no_thread_leak_on_normal_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """10 successful calls do not leave dangling threads behind."""
        monkeypatch.setattr(chain_module, "CALLABLE_TIMEOUT", 0.1)
        chain = _build_callable_chain(
            "kstlib_test_callables:_fast_callable",
        )

        baseline = threading.active_count()
        for _ in range(10):
            chain.patch("data")
        # Give Python a moment to reap any joined daemon threads
        time.sleep(0.05)
        after = threading.active_count()
        # Allow a small slack for transient threads from the test runner
        assert after - baseline <= 1, f"thread leak suspected: baseline={baseline}, after 10 calls={after}"

    def test_timeout_works_from_non_main_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The timeout fires correctly when chain.patch is called from a worker thread."""
        monkeypatch.setattr(chain_module, "CALLABLE_TIMEOUT", 0.1)
        chain = _build_callable_chain(
            "kstlib_test_callables:_slow_callable",
        )

        captured_error: list[BaseException] = []

        def _outer_worker() -> None:
            try:
                chain.patch("data")
            except BaseException as exc:  # noqa: BLE001
                captured_error.append(exc)

        outer = threading.Thread(target=_outer_worker, daemon=True)
        outer.start()
        outer.join(timeout=2.0)

        assert not outer.is_alive(), "outer worker did not finish"
        assert len(captured_error) == 1
        assert isinstance(captured_error[0], CallableError)
        assert "timed out after" in str(captured_error[0])


# ============================================================================
# C1 regression: callable allowlist bypass via direct TransformChain
# ============================================================================


class TestCallableAllowlistBypass:
    """Regression tests for C1: callable bypass via direct construction."""

    def test_direct_construction_os_system_rejected(self) -> None:
        """Direct TransformChain with callable='os:system' is rejected (fail-closed)."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="os:system"),
            ),
            # No allowed_modules -> fail-closed
        )
        with pytest.raises(CallableError, match="require allowed_callable_modules"):
            chain.patch("data")

    def test_direct_construction_no_whitelist_rejects_any_callable(self) -> None:
        """Direct TransformChain without allowed_modules rejects any callable."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="mymod:safe_fn"),
            ),
        )
        with pytest.raises(CallableError, match="require allowed_callable_modules"):
            chain.patch("data")

    def test_dangerous_module_rejected_even_with_whitelist(self) -> None:
        """DANGEROUS_MODULES are rejected even if explicitly whitelisted."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="os:system"),
            ),
            allowed_modules=frozenset({"os"}),
        )
        with pytest.raises(CallableError, match="DANGEROUS_MODULES blacklist"):
            chain.patch("data")

    def test_dangerous_submodule_rejected(self) -> None:
        """Submodules of DANGEROUS_MODULES are also rejected (os.path:join)."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="os.path:join"),
            ),
            allowed_modules=frozenset({"os.path"}),
        )
        with pytest.raises(CallableError, match="DANGEROUS_MODULES blacklist"):
            chain.patch("data")

    def test_from_config_passes_allowed_modules(self) -> None:
        """TransformChain.from_config passes allowed_callable_modules correctly."""
        config = TransformConfig(
            chains={
                "test": TransformChainConfig(
                    name="test",
                    forward=(PrimitiveConfig(name="base64"),),
                    patch=PatchConfig(callable="kstlib_test_callables:_fast_callable"),
                ),
            },
            allowed_callable_modules=frozenset({_TEST_CALLABLES_MODULE_NAME}),
        )
        chain = TransformChain.from_config("test", config)
        result = chain.patch("data")
        assert result == "data"

    def test_module_not_in_whitelist_rejected_at_runtime(self) -> None:
        """Module not in whitelist is rejected at patch() time."""
        chain = TransformChain(
            TransformChainConfig(
                name="test",
                forward=(PrimitiveConfig(name="base64"),),
                patch=PatchConfig(callable="kstlib_test_callables:_fast_callable"),
            ),
            allowed_modules=frozenset({"other.module"}),
        )
        with pytest.raises(CallableError, match="not in allowed_callable_modules"):
            chain.patch("data")

    def test_dangerous_modules_constant_frozen(self) -> None:
        """DANGEROUS_MODULES contains expected modules and is a frozenset."""
        assert isinstance(DANGEROUS_MODULES, frozenset)
        for mod in ("os", "sys", "subprocess", "builtins", "importlib", "pickle"):
            assert mod in DANGEROUS_MODULES
