"""REST API wrapper module (config-driven).

This module provides a config-driven REST API client with multi-source
credential resolution and detailed logging.

Features:
    - Config-driven endpoints from kstlib.conf.yml or external *.rapi.yml files
    - Auto-discovery of *.rapi.yml files in current directory
    - Multi-source credentials (env, file, sops, provider)
    - Header merging at three levels (service, endpoint, runtime)
    - Automatic retry with exponential backoff
    - TRACE-level logging for debugging
    - Hard limits with deep defense

Quick Start:
    >>> from kstlib.rapi import call
    >>> response = call("httpbin.get_ip")  # doctest: +SKIP
    >>> response.data  # doctest: +SKIP
    {'origin': '...'}

With Client Instance:
    >>> from kstlib.rapi import RapiClient
    >>> client = RapiClient()  # doctest: +SKIP
    >>> response = client.call("httpbin.post_data", body={"key": "value"})  # doctest: +SKIP

From External YAML File:
    >>> from kstlib.rapi import RapiClient
    >>> client = RapiClient.from_file("github.rapi.yml")  # doctest: +SKIP
    >>> response = client.call("github.user")  # doctest: +SKIP

Auto-Discovery:
    >>> from kstlib.rapi import RapiClient
    >>> client = RapiClient.discover()  # Finds *.rapi.yml in cwd  # doctest: +SKIP
    >>> client.list_apis()  # doctest: +SKIP
    ['github', 'slack']

Async:
    >>> from kstlib.rapi import call_async
    >>> response = await call_async("httpbin.get_ip")  # doctest: +SKIP

Configuration:
    Configure endpoints in kstlib.conf.yml:

    .. code-block:: yaml

        rapi:
          limits:
            timeout: 30
            max_response_size: "10M"
            max_retries: 3

          api:
            httpbin:
              base_url: "https://httpbin.org"
              endpoints:
                get_ip:
                  path: "/ip"
                post_data:
                  path: "/post"
                  method: POST

    Or use external *.rapi.yml files (simplified format):

    .. code-block:: yaml

        # github.rapi.yml
        name: github
        base_url: "https://api.github.com"
        credentials:
          type: sops
          path: "./tokens/github.sops.json"
          token_path: ".access_token"
        auth:
          type: bearer
        endpoints:
          user:
            path: "/user"
          repos:
            path: "/user/repos"
"""

from kstlib.rapi.client import RapiClient, RapiResponse, call, call_async
from kstlib.rapi.config import (
    ApiConfig,
    EndpointConfig,
    HmacConfig,
    RapiConfigManager,
    load_rapi_config,
)
from kstlib.rapi.credentials import CredentialRecord, CredentialResolver
from kstlib.rapi.exceptions import (
    CredentialError,
    EndpointAmbiguousError,
    EndpointNotFoundError,
    RapiError,
    RequestError,
    ResponseTooLargeError,
)

__all__ = [
    "ApiConfig",
    "CredentialError",
    "CredentialRecord",
    "CredentialResolver",
    "EndpointAmbiguousError",
    "EndpointConfig",
    "EndpointNotFoundError",
    "HmacConfig",
    "RapiClient",
    "RapiConfigManager",
    "RapiError",
    "RapiResponse",
    "RequestError",
    "ResponseTooLargeError",
    "call",
    "call_async",
    "load_rapi_config",
]
