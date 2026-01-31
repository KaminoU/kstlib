"""Tests for lazy loading utilities."""

from __future__ import annotations

import sys
from typing import Any

from kstlib.utils.lazy import lazy_factory


class TestLazyFactory:
    """Tests for the lazy_factory decorator."""

    def test_defers_import_until_called(self) -> None:
        """Module is not imported until factory is called."""
        # Use a module we know exists but isn't imported yet in this test
        module_name = "kstlib.secrets.providers.sops"

        # Ensure it's not already imported
        if module_name in sys.modules:
            del sys.modules[module_name]

        @lazy_factory(module_name, "SOPSProvider")
        def factory(**_kwargs: Any) -> Any: ...

        # Module should not be imported yet
        assert module_name not in sys.modules

        # Call the factory
        provider = factory()

        # Now it should be imported
        assert module_name in sys.modules
        assert provider.__class__.__name__ == "SOPSProvider"

    def test_passes_kwargs_to_class(self) -> None:
        """Keyword arguments are passed to the class constructor."""

        @lazy_factory("kstlib.secrets.providers.kwargs", "KwargsProvider")
        def factory(**_kwargs: Any) -> Any: ...

        provider = factory(secrets={"key": "value"})

        # Verify the provider was created with the secrets
        from kstlib.secrets.models import SecretRequest

        record = provider.resolve(SecretRequest(name="key"))
        assert record is not None
        assert record.value == "value"

    def test_preserves_function_metadata(self) -> None:
        """Decorator preserves the original function's metadata."""

        @lazy_factory("kstlib.secrets.providers.environment", "EnvironmentProvider")
        def my_custom_factory(**_kwargs: Any) -> Any:
            """Custom factory docstring."""

        assert my_custom_factory.__name__ == "my_custom_factory"
        assert my_custom_factory.__doc__ == "Custom factory docstring."
