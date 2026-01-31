# REST API Client

Define your APIs in YAML, call them from CLI or Python. Pure declarative.

## TL;DR

```python
from kstlib.rapi import RapiClient, call

# Simple GET (uses kstlib.conf.yml config)
response = call("github.user")
print(response.data)  # {'login': 'octocat', ...}

# With path parameters
response = call("github.repos-issues", owner="KaminoU", repo="igcv3")

# Query params override YAML defaults
response = call("github.repos-list", per_page="50", page="2")

# POST with JSON body
response = call("myapi.create", body={"name": "test", "value": 42})

# Async support
response = await call_async("github.user")

# External config file
client = RapiClient.from_file("github.rapi.yml")
response = client.call("user")
```

## CLI

Quick API calls from the terminal with the same config.

### Quick Examples

```bash
# Simple GET (implicit call - no "call" subcommand needed)
kstlib rapi github.user

# With path parameters
kstlib rapi github.repos-issues owner=KaminoU repo=igcv3

# Query parameters (override YAML defaults)
kstlib rapi github.repos-list per_page=50 page=2

# POST with JSON body
kstlib rapi myapi.create -b '{"name": "test"}'

# Body from file (curl-like syntax)
kstlib rapi myapi.create -b @payload.json

# Output to file (for scripting)
kstlib rapi github.user -o user.json

# Full response with metadata
kstlib rapi github.user -f full -o result.json

# Custom headers
kstlib rapi github.user -H "X-Debug: true"

# List available endpoints
kstlib rapi list
kstlib rapi list github --verbose

# TRACE mode for debugging
kstlib -vvv rapi github.user
```

### Commands

| Command | Description |
| - | - |
| `kstlib rapi <api>.<endpoint> [args...]` | Make API call (implicit) |
| `kstlib rapi list [API]` | List configured endpoints |

### Call Options

| Option | Short | Description |
| - | - | - |
| `--format` | `-f` | Output format: `json` (default), `text`, `full` |
| `--out` | `-o` | Write output to file |
| `--body` | `-b` | JSON body or `@filename` to read from file |
| `--header` | `-H` | Custom header (repeatable) |
| `--quiet` | `-q` | Suppress status messages |

### Verbosity Levels

```bash
kstlib rapi github.user          # Normal output
kstlib -v rapi github.user       # Debug logging
kstlib -vv rapi github.user      # Verbose debug
kstlib -vvv rapi github.user     # TRACE: body, params, elapsed time
```

### Exit Codes

| Code | Meaning |
| - | - |
| 0 | Success (HTTP 2xx/3xx) |
| 1 | Error (HTTP 4xx/5xx, network error, invalid config) |

## Configuration

### In kstlib.conf.yml

```yaml
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
          query:              # Default query parameters
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

Load via include patterns:

```yaml
# kstlib.conf.yml
rapi:
  include:
    - "*.rapi.yml"
    - "apis/*.rapi.yml"
```

Or load directly:

```python
client = RapiClient.from_file("github.rapi.yml")
client = RapiClient.discover()  # Auto-discover *.rapi.yml in cwd
```

### Hard Limits

| Parameter | Default | Hard Min | Hard Max |
| - | - | - | - |
| `timeout` | 30.0 | 1.0 | 300.0 |
| `max_response_size` | 10MB | - | 100MB |
| `max_retries` | 3 | 0 | 10 |
| `retry_delay` | 1.0 | 0.1 | 60.0 |
| `retry_backoff` | 2.0 | 1.0 | 5.0 |

## Key Features

- **Config-Driven**: Define APIs in YAML, call by name
- **CLI and Python**: Same config for both interfaces
- **Query Override**: YAML defaults can be overridden at runtime
- **External Files**: `*.rapi.yml` for modular API definitions
- **Auto-Discovery**: `RapiClient.discover()` finds local configs
- **Multi-Source Credentials**: SOPS, environment, files, keyring
- **File Output**: `-o file.json` for scripting
- **TRACE Logging**: `-vvv` for detailed debugging

## Path and Query Parameters

### Path Parameters

Use `{param}` placeholders:

```yaml
endpoints:
  repos-issues:
    path: "/repos/{owner}/{repo}/issues"
```

```python
# Python
response = client.call("github.repos-issues", owner="KaminoU", repo="igcv3")
```

```bash
# CLI
kstlib rapi github.repos-issues owner=KaminoU repo=igcv3
```

### Query Parameters

#### YAML Defaults

```yaml
endpoints:
  repos-list:
    path: "/user/repos"
    query:
      sort: updated
      per_page: "10"
```

#### Runtime Override

Arguments **override** YAML defaults:

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
kstlib rapi github.repos-list                         # defaults
kstlib rapi github.repos-list per_page=50             # override one
kstlib rapi github.repos-list sort=created per_page=100  # override both
```

#### Pagination

```bash
kstlib rapi github.repos-list page=1 -o page1.json
kstlib rapi github.repos-list page=2 -o page2.json
kstlib rapi github.repos-list page=3 -o page3.json
```

### Request Body

```python
# Python
response = client.call("myapi.create", body={"name": "test", "value": 42})
```

```bash
# CLI: inline JSON
kstlib rapi myapi.create -b '{"name": "test", "value": 42}'

# CLI: from file (curl-like)
kstlib rapi myapi.create -b @data.json
```

## Common Patterns

### Error Handling

```python
from kstlib.rapi import RapiClient, EndpointNotFoundError, RequestError

client = RapiClient()

# Pattern 1: Check response.ok
response = client.call("github.repos-get", owner="foo", repo="bar")
if response.ok:
    print("Success:", response.data)
else:
    print(f"Error: {response.status_code}")

# Pattern 2: Exception handling
try:
    response = client.call("myapi.slow-endpoint")
except RequestError as e:
    print(f"Request failed: {e}")
    print(f"Retryable: {e.retryable}")
```

### Response Inspection

```python
response = client.call("github.user")

response.ok           # True if 2xx status
response.status_code  # HTTP status code
response.data         # Parsed JSON (dict or list)
response.text         # Raw response text
response.headers      # Response headers dict
response.elapsed      # Request duration in seconds
response.endpoint_ref # "github.user"
```

### Custom Headers

```python
response = client.call(
    "myapi.endpoint",
    headers={"X-Request-ID": "abc-123", "X-Debug": "true"}
)
```

### Async Requests

```python
import asyncio
from kstlib.rapi import RapiClient

async def main():
    client = RapiClient()

    # Single async call
    response = await client.call_async("github.user")

    # Concurrent requests
    results = await asyncio.gather(
        client.call_async("github.repos-list", page="1"),
        client.call_async("github.repos-list", page="2"),
        client.call_async("github.repos-list", page="3"),
    )

asyncio.run(main())
```

## Credentials

### Configuration

```yaml
# kstlib.conf.yml
credentials:
  github_token:
    type: sops
    path: "secrets/github.sops.json"
    key: "access_token"

  api_key:
    type: env
    var: "MY_API_KEY"

rapi:
  apis:
    github:
      credentials: github_token  # Reference by name
      auth_type: bearer
```

### Credential Types

| Type | Keys | Description |
| - | - | - |
| `env` | `var` | Environment variable |
| `file` | `path`, `token_path` | File with jq-like extraction |
| `sops` | `path`, `key` | SOPS-encrypted file |
| `keyring` | `service`, `username` | System keyring |

### Authentication Types

| Auth Type | Header Format |
| - | - |
| `bearer` | `Authorization: Bearer <token>` |
| `basic` | `Authorization: Basic <base64(user:pass)>` |
| `api_key` | `X-API-Key: <key>` |

## Troubleshooting

### Endpoint not found

Use full reference `api.endpoint`:

```bash
# Instead of:
kstlib rapi user  # May be ambiguous

# Use:
kstlib rapi github.user
```

### Credential resolution failed

Check credential source:

```bash
# For env credentials
echo $GITHUB_TOKEN

# For SOPS files
sops -d secrets/github.sops.json
```

### TRACE debugging

```bash
kstlib -vvv rapi github.user
```

Shows: URL, headers, body sent, body received, elapsed time.

## API Reference

Full autodoc: {doc}`../../api/rapi`

| Class | Description |
| - | - |
| `RapiClient` | Main client for making API calls |
| `RapiResponse` | Response object with data, status, elapsed time |
| `RapiConfigManager` | Manages API and endpoint configuration |

| Function | Description |
| - | - |
| `call` | Convenience function for single sync call |
| `call_async` | Convenience function for single async call |

| Exception | Description |
| - | - |
| `RapiError` | Base exception for rapi module |
| `CredentialError` | Credential resolution failed |
| `EndpointNotFoundError` | Endpoint not in config |
| `EndpointAmbiguousError` | Short reference matches multiple endpoints |
| `RequestError` | HTTP request failed |
| `ResponseTooLargeError` | Response exceeds max_response_size |
