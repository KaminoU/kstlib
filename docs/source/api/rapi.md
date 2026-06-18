# REST API Client

Config-driven REST API client: define your APIs in YAML, call them from CLI or Python.

## Overview

The `rapi` module provides a **declarative approach** to REST API calls. Instead of
hardcoding URLs, headers, and authentication in your code, you define everything in
configuration files and call endpoints by name.

```python
from kstlib.rapi import call, RapiClient

# Quick call using config
response = call("github.user")
print(response.data)  # {"login": "octocat", ...}

# Client instance for multiple calls
client = RapiClient()
response = client.call("github.repos-issues", owner="KaminoU", repo="igcv3")
```

**Benefits:**

- **Single source of truth**: API definitions live in YAML, not scattered in code
- **CLI and Python**: Same config works for both `kstlib rapi` CLI and Python code
- **Credential management**: Automatic token resolution from SOPS, env vars, or files
- **Override at runtime**: Default query params can be overridden per-call

## Configuration

### In kstlib.conf.yml

Define APIs in your main configuration file:

```yaml
# kstlib.conf.yml
rapi:
  apis:
    github:
      base_url: "https://api.github.com"
      credentials: github_token
      auth_type: bearer
      headers:
        Accept: "application/vnd.github+json"
        User-Agent: "my-app/1.0"
      endpoints:
        user:
          path: "/user"
        repos-list:
          path: "/user/repos"
          query:
            sort: updated
            per_page: "10"
        repos-issues:
          path: "/repos/{owner}/{repo}/issues"
          method: GET
```

### External *.rapi.yml Files

For larger projects, define APIs in separate files:

```yaml
# github.rapi.yml
name: github
base_url: "https://api.github.com"

credentials:
  type: sops
  config: github_token

headers:
  Accept: "application/vnd.github+json"
  User-Agent: "my-app/1.0"

endpoints:
  user:
    path: "/user"
  repos-list:
    path: "/user/repos"
    query:
      sort: updated
      per_page: "10"
  repos-issues:
    path: "/repos/{owner}/{repo}/issues"
```

Load external files via include patterns:

```yaml
# kstlib.conf.yml
rapi:
  include:
    - "*.rapi.yml"
    - "apis/*.rapi.yml"
```

Or load directly in Python:

```python
client = RapiClient.from_file("github.rapi.yml")
client = RapiClient.discover()  # Auto-discover *.rapi.yml in current directory
```

### Named Server Profiles

The ``rapi.servers`` section is for **heterogeneous APIs** (different
stacks, different auth) bundled into a single project. Each profile
inherits from ``rapi.defaults`` via deep merge and overrides what
matters (``base_url``, ``credentials``, ``auth``, ``headers``).

```yaml
rapi:
  defaults:
    auth: bearer
    headers:
      Accept: application/json

  servers:
    github:
      base_url: https://api.github.com
      credentials:
        type: env
        var: GITHUB_TOKEN
      headers:
        Accept: application/vnd.github+json
        X-GitHub-Api-Version: "2022-11-28"
    jira:
      base_url: https://mycompany.atlassian.net
      auth: api_key
      credentials:
        type: env
        var: JIRA_API_KEY
```

```python
manager = load_rapi_config()
github  = manager.resolve_server("github")  # Merged: github + defaults
jira    = manager.resolve_server("jira")    # Merged: jira   + defaults
default = manager.resolve_server(None)      # Defaults wrapped as ServerConfig
manager.server_names                        # ["github", "jira"]
```

```{note}
For **same API, different environments** (e.g. SAS Viya source/target
migration), do **not** use ``rapi.servers``. Use the ``${VAR}`` env var
pattern in ``rapi.defaults`` instead - the substitution is applied
globally at YAML load time, so ``token_path`` supports dynamic profile
selection natively. See {doc}`../features/rapi/index` for the decision
matrix and full examples.
```

See {doc}`../features/rapi/index` for full details, the decision
matrix, and validation rules.

## Endpoints and Parameters

### Path Parameters

Use `{param}` placeholders in the path:

```yaml
endpoints:
  repos-issues:
    path: "/repos/{owner}/{repo}/issues"
```

```python
# Python: pass as keyword arguments
response = client.call("github.repos-issues", owner="KaminoU", repo="igcv3")
```

```bash
# CLI: pass as key=value
kstlib rapi github.repos-issues owner=KaminoU repo=igcv3
```

### Query Parameters

#### Default Values

Define default query parameters in YAML:

```yaml
endpoints:
  repos-list:
    path: "/user/repos"
    query:
      sort: updated
      per_page: "10"
```

#### Override at Runtime

Runtime arguments **override** YAML defaults:

```python
# Uses defaults: sort=updated, per_page=10
response = client.call("github.repos-list")

# Override per_page, keep sort=updated
response = client.call("github.repos-list", per_page="50")

# Override both
response = client.call("github.repos-list", sort="created", per_page="100")
```

```bash
# CLI: same behavior
kstlib rapi github.repos-list                    # defaults
kstlib rapi github.repos-list per_page=50        # override one
kstlib rapi github.repos-list sort=created per_page=100  # override both
```

#### Pagination

For APIs with pagination, override the `page` parameter:

```bash
kstlib rapi github.repos-list page=1
kstlib rapi github.repos-list page=2
kstlib rapi github.repos-list page=3
```

### Request Body

#### Python

```python
response = client.call("myapi.create-item", body={"name": "test", "value": 42})
```

#### CLI

```bash
# Inline JSON
kstlib rapi myapi.create-item --body '{"name": "test", "value": 42}'

# From file (curl-like syntax)
kstlib rapi myapi.create-item --body @data.json
kstlib rapi myapi.create-item -b @data.json
```

## CLI Usage

### Basic Syntax

```bash
kstlib rapi <api>.<endpoint> [key=value ...]
```

```{tip}
**Shortcut for single-API projects**: The `<api>.` prefix is always required for clarity
and script portability. If you work frequently with one API, create a shell alias:

- **PowerShell**: `function brapi { kstlib rapi binance.$args }`
- **Bash/Zsh**: `alias brapi='kstlib rapi binance.'`

Then use: `brapi balance` instead of `kstlib rapi binance.balance`
```

### Examples

```bash
# Simple GET
kstlib rapi github.user

# With path parameters
kstlib rapi github.repos-issues owner=KaminoU repo=igcv3

# With query parameters (override defaults)
kstlib rapi github.repos-list per_page=50 page=2

# POST with body from file
kstlib rapi myapi.create-item -b @payload.json

# Custom headers
kstlib rapi github.user -H "X-Debug: true"

# Output to file (for scripting)
kstlib rapi github.user -o user.json

# Full response with metadata
kstlib rapi github.user -f full -o result.json

# List available endpoints
kstlib rapi list
kstlib rapi list github  # filter by API
kstlib rapi list --verbose  # show methods and auth

# Extraction: resolved resource id (config-driven heuristic; exit 1 if none)
kstlib rapi github.user --show-id

# Extraction: every id of a collection, one per line (pipeable)
kstlib rapi myapi.items-list --show-ids

# Extraction: one value via ad-hoc JMESPath
kstlib rapi github.user --pick login

# Extraction: several named values (key=jmespath, repeatable)
kstlib rapi github.user --extract login=login --extract id=id

# Extraction: a key declared by the endpoint extract: directive, by name
kstlib rapi myapi.item-get abc-123 --show-extracted object_ids

# Extraction: a subset of declared keys, as a JSON object
kstlib rapi myapi.item-get abc-123 --show-extracted object_ids,status

# Extraction: all keys declared by the extract: directive (JSON dict)
kstlib rapi myapi.item-get abc-123 --show-extracted
```

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--format` | `-f` | Output format: `json` (default), `text`, `full` |
| `--out` | `-o` | Write output to file |
| `--body` | `-b` | JSON body or `@filename` |
| `--header` | `-H` | Custom header (repeatable) |
| `--server` | `-s` | Named server profile from `rapi.servers` config |
| `--quiet` | `-q` | Suppress status messages |
| `--raw` | | Output raw JSON without Rich formatting (pipeable) |
| `--minify` | | Output compact single-line JSON |
| `--pick` | `-p` | Extract a single value via ad-hoc JMESPath (e.g. `--pick data.id`) |
| `--extract` | | Extract named values `key=jmespath` (repeatable) |
| `--show-id` | | Print the resolved resource id (config-driven heuristic) |
| `--show-ids` | | Print all resolved resource ids (config-driven heuristic) |
| `--show-extracted` | | Print values declared by the endpoint `extract:` directive (`[KEY[,KEY...]]` optional) |

The five extraction flags are mutually exclusive (at most one per call).
`--show-id` and `--pick` exit 1 when the value is empty (a scripting guard);
`--show-ids` and `--extract` treat an empty result as legitimate (exit 0).
`--show-extracted` adapts its failure policy to the output form. With a single
key it behaves like `--pick`: it exits 1 when the key is missing or its
expression matched nothing (a declared key holding an empty collection is still
legitimate, exit 0). With several comma/space-separated keys it prints a JSON
object subset and exits 0; a declared key whose expression matched nothing
appears as `null`, and only an unknown key fails. The bare flag prints all
declared keys; a missing `extract:` directive always fails. See
{doc}`../features/rapi/index` for the decision table and JMESPath cheat-sheet.

### Server Profile Selection

The `--server` (or `-s`) flag picks a named profile from the
`rapi.servers` section of `kstlib.conf.yml`. It overrides any
`server:` directive declared in the `*.rapi.yml` file (file or
endpoint level). Use it for heterogeneous APIs (github + jira + ...).

```bash
# Use the github profile (overrides any server: directive in YAML)
kstlib rapi --server github github.repos-list

# Short form
kstlib rapi -s jira jira.issues-search

# Unknown server name exits 1 with the list of available profiles
kstlib rapi --server ghost github.user
# -> Error: Server profile not found: 'ghost'. Available: ['github', 'jira']
```

For SAS Viya source/target migration (same API, different environments),
use the `${ACTIVE_VIYA}` env var pattern instead of `--server`. See
{doc}`../features/rapi/index` for the decision matrix.

### Verbosity and Tracing

```bash
kstlib rapi github.user          # normal output
kstlib -v rapi github.user       # debug logging
kstlib -vv rapi github.user      # verbose debug
kstlib -vvv rapi github.user     # TRACE: shows body, params, elapsed time
```

## Python API

### Quick Functions

```python
from kstlib.rapi import call, call_async

# Synchronous
response = call("github.user")

# Asynchronous
response = await call_async("github.user")
```

### Client Instance

```python
from kstlib.rapi import RapiClient

# From kstlib.conf.yml
client = RapiClient()

# From external file
client = RapiClient.from_file("github.rapi.yml")

# Auto-discover *.rapi.yml files
client = RapiClient.discover()

# Make calls
response = client.call("github.user")
response = client.call("github.repos-issues", owner="KaminoU", repo="igcv3")

# With body
response = client.call("myapi.create", body={"key": "value"})

# With custom headers
response = client.call("myapi.get", headers={"X-Custom": "value"})
```

### Response Object

```python
response = client.call("github.user")

response.ok          # True if 2xx status
response.status_code # HTTP status code
response.data        # Parsed JSON (dict or list)
response.text        # Raw response text
response.headers     # Response headers
response.elapsed     # Request duration in seconds
response.endpoint_ref # "github.user"

# Extraction accessors (config-driven heuristic; an extract: directive wins)
response.id          # resolved resource id (str | None)
response.ids         # all resource ids (list[str], never None)
response.count       # collection size (int | None)
response.next_url    # next-page URL from HAL/Viya links (str | None)
response.has_next    # True when a next-page link is present
response.extracted   # values from an endpoint extract: directive (Box)

response.get("user.login")  # ad-hoc JMESPath escape hatch (None on miss, never raises)
response.json()             # strict parsed JSON (dict|list), raises RapiError if not JSON
```

The heuristic accessors read HAL / SAS Viya style payloads out of the box and
are tuned via the `rapi.extraction` config section. See
{doc}`../features/rapi/index` for the full extraction guide (endpoint
`extract:` directive, CLI flags, and JMESPath cheat-sheet).

```python
# Collection {"count": 42, "items": [{"id": "a"}, {"id": "b"}]}
coll = client.call("myapi.items-list")
coll.count      # 42
coll.ids        # ['a', 'b']
coll.has_next   # True when a links[?rel=='next'] entry is present

# Single resource {"id": "abc-123", "name": "report"}
client.call("myapi.item-get", id="abc-123").id   # 'abc-123'
```

## Credentials

### Configuration

```yaml
# In kstlib.conf.yml
credentials:
  github_token:
    type: sops
    path: "secrets/github.sops.json"
    key: "access_token"

  api_key:
    type: env
    key: "MY_API_KEY"

rapi:
  apis:
    github:
      credentials: github_token  # Reference by name
```

### Inline Credentials (*.rapi.yml)

```yaml
# github.rapi.yml
credentials:
  type: sops
  config: github_token  # References credentials section in kstlib.conf.yml
```

### Supported Sources

| Type | Parameters | Description |
|------|------------|-------------|
| `sops` | `path`, `fields` | SOPS-encrypted files |
| `env` | `fields` | Environment variables |
| `file` | `path`, `fields` | Plain text/JSON files |
| `keyring` | `service`, `username` | System keyring |

### Generic Fields Mapping

All credential types support a generic `fields:` mapping for flexible credential extraction.
This allows APIs requiring more than key/secret (e.g., passphrase for Coinbase/KuCoin/OKX).

```yaml
# Generic fields mapping (recommended)
credentials:
  type: sops  # or env, file
  path: "./tokens/exchange.sops.yml"
  fields:
    key: api_key           # Required - maps to CredentialRecord.value
    secret: api_secret     # Optional - maps to CredentialRecord.secret
    passphrase: passphrase # Optional - maps to CredentialRecord.extras["passphrase"]
    account_id: account    # Optional - any extra field goes to extras dict
```

**Field mapping rules:**
- `key` is **required** and maps to `CredentialRecord.value`
- `secret` is **optional** and maps to `CredentialRecord.secret`
- All other fields map to `CredentialRecord.extras` dict

**Environment variables example:**

```yaml
credentials:
  type: env
  fields:
    key: COINBASE_API_KEY
    secret: COINBASE_API_SECRET
    passphrase: COINBASE_PASSPHRASE
```

**Legacy format (still supported):**

```yaml
# Legacy - key_field/secret_field (backwards compatible)
credentials:
  type: sops
  path: "./tokens/binance.sops.yml"
  key_field: api_key
  secret_field: secret_key
```

## HMAC Authentication

For APIs requiring HMAC signature (Binance, Kraken, etc.), configure the `auth` section:

```yaml
# binance.rapi.yml
name: binance
base_url: "https://testnet.binance.vision"

credentials:
  type: sops
  path: "./tokens/binance.sops.yml"
  fields:
    key: api_key
    secret: secret_key

auth:
  type: hmac
  algorithm: sha256          # sha256 (Binance) or sha512 (Kraken)
  timestamp_field: timestamp # Query param name for timestamp
  signature_field: signature # Query param name for signature
  signature_format: hex      # hex (Binance) or base64 (Kraken)
  key_header: X-MBX-APIKEY   # Header for API key

endpoints:
  balance:
    path: "/api/v3/account"
    method: GET

  my-trades:
    path: "/api/v3/myTrades"
    method: GET
    query:
      symbol: BTCUSDT
      limit: "10"
```

### HMAC Options

| Option | Description | Example |
|--------|-------------|---------|
| `algorithm` | Hash algorithm | `sha256`, `sha512` |
| `timestamp_field` | Query param for timestamp (ms) | `timestamp`, `nonce` |
| `signature_field` | Query param for signature | `signature`, `sign` |
| `signature_format` | Signature encoding | `hex`, `base64` |
| `key_header` | Header for API key | `X-MBX-APIKEY`, `API-Key` |
| `sign_body` | Sign request body instead of query string | `true`, `false` |
| `nonce_field` | Alternative to timestamp_field | `nonce` |

### Public Endpoints (No Auth)

For APIs with mixed public/private endpoints, disable auth per-endpoint with `auth: false`:

```yaml
endpoints:
  # Public - no signature needed
  ticker-price:
    path: "/api/v3/ticker/price"
    method: GET
    auth: false
    query:
      symbol: BTCUSDT

  # Private - HMAC signature applied
  balance:
    path: "/api/v3/account"
    method: GET
    # auth: true (default)
```

```{note}
By default, all endpoints inherit API-level authentication (`auth: true`).
Set `auth: false` on public endpoints to skip credential resolution and signature generation.
```

## Safeguards for Dangerous Endpoints

For destructive operations (DELETE, PUT), kstlib requires explicit confirmation to prevent accidental data loss.

### Configuration

Define a `safeguard` string on dangerous endpoints:

```yaml
endpoints:
  delete-user:
    path: "/users/{user_id}"
    method: DELETE
    safeguard: "DELETE USER {user_id}"
```

By default, DELETE and PUT methods require a safeguard. Configure this in `kstlib.conf.yml`:

```yaml
rapi:
  safeguard:
    required_methods:
      - DELETE
      - PUT
```

### Calling Safeguarded Endpoints

```python
from kstlib.rapi import RapiClient
from kstlib.rapi.exceptions import ConfirmationRequiredError

client = RapiClient()

# Without confirmation - raises ConfirmationRequiredError
try:
    client.call("admin.delete-user", user_id="123")
except ConfirmationRequiredError as e:
    print(f"Required: {e.expected}")  # "DELETE USER 123"

# With correct confirmation - proceeds
client.call("admin.delete-user", user_id="123", confirm="DELETE USER 123")
```

```{warning}
If an endpoint uses a method in `required_methods` but lacks a `safeguard` string,
`SafeguardMissingError` is raised at config load time (not at runtime).
```

### Exchange Examples

**Binance** (SHA256, hex, query string):

```yaml
auth:
  type: hmac
  algorithm: sha256
  timestamp_field: timestamp
  signature_field: signature
  signature_format: hex
  key_header: X-MBX-APIKEY
```

**Kraken** (SHA512, base64, nonce):

```yaml
auth:
  type: hmac
  algorithm: sha512
  nonce_field: nonce
  signature_field: sign
  signature_format: base64
  key_header: API-Key
```

```bash
# Test HMAC signing
cd examples/rapi/binance
kstlib rapi binance.balance        # Signed request
kstlib -vvv rapi binance.balance   # TRACE mode to see signature details
```

## API Reference

### Client

```{eval-rst}
.. autoclass:: kstlib.rapi.RapiClient
   :members:
   :show-inheritance:

.. autoclass:: kstlib.rapi.RapiResponse
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.rapi.FilePayload
   :members:
   :show-inheritance:
   :no-index:

.. autofunction:: kstlib.rapi.call

.. autofunction:: kstlib.rapi.call_async
```

### Configuration

```{eval-rst}
.. autoclass:: kstlib.rapi.RapiConfigManager
   :members:
   :show-inheritance:

.. autoclass:: kstlib.rapi.ApiConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.rapi.EndpointConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.rapi.MultipartConfig
   :members:
   :show-inheritance:
   :no-index:

.. autoclass:: kstlib.rapi.ServerConfig
   :members:
   :show-inheritance:
   :no-index:

.. autofunction:: kstlib.rapi.load_rapi_config
```

### Credentials

```{eval-rst}
.. autoclass:: kstlib.rapi.CredentialResolver
   :members:
   :show-inheritance:

.. autoclass:: kstlib.rapi.CredentialRecord
   :members:
   :show-inheritance:
   :no-index:
```

### Exceptions

```{eval-rst}
.. autoexception:: kstlib.rapi.RapiError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.CredentialError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.EndpointNotFoundError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.EndpointAmbiguousError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.RequestError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.ResponseTooLargeError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.ConfirmationRequiredError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.SafeguardMissingError
   :members:
   :show-inheritance:

.. autoexception:: kstlib.rapi.ServerNotFoundError
   :members:
   :show-inheritance:
```
