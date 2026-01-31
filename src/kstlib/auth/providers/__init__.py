"""Authentication providers for OAuth2/OIDC."""

from __future__ import annotations

from kstlib.auth.providers.base import AbstractAuthProvider, AuthProviderConfig
from kstlib.auth.providers.oauth2 import OAuth2Provider
from kstlib.auth.providers.oidc import OIDCProvider

__all__ = [
    "AbstractAuthProvider",
    "AuthProviderConfig",
    "OAuth2Provider",
    "OIDCProvider",
]
