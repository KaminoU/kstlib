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

# Multipart file upload (auto-detected from Content-Type)
kstlib rapi transfer.packages-upload -b @package.json

# Raw output (no Rich, pipeable to jq)
kstlib rapi github.user --raw | jq '.login'

# Minified JSON (compact single-line)
kstlib rapi github.user --minify --out user.json

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
| `kstlib rapi <api>.<endpoint> [args...]` | Make API call (implicit shortcut) |
| `kstlib rapi call <api>.<endpoint> [args...]` | Make API call (explicit form) |
| `kstlib rapi list [API]` | List configured endpoints |

```{note}
`kstlib rapi <api>.<endpoint>` is a shortcut for
`kstlib rapi call <api>.<endpoint>`; both forms are strictly equivalent and
accept the same options. The explicit `call` form is recommended in scripts
(stable, unambiguous) and remains available whenever you prefer to spell the
resolution out.
```

### Call Options

| Option | Short | Description |
| - | - | - |
| `--format` | `-f` | Output format: `json` (default), `text`, `full` |
| `--out` | `-o` | Write output to file |
| `--body` | `-b` | JSON body or `@filename` to read from file |
| `--header` | `-H` | Custom header (repeatable) |
| `--quiet` | `-q` | Suppress status messages |
| `--raw` | | Output raw JSON without Rich formatting (pipeable) |
| `--minify` | | Output compact single-line JSON |
| `--pick` | `-p` | Extract a single value via ad-hoc JMESPath |
| `--extract` | | Extract named values `key=jmespath` (repeatable) |
| `--show-id` | | Print the resolved resource id (config-driven heuristic) |
| `--show-ids` | | Print all resolved resource ids (config-driven heuristic) |
| `--show-extracted` | | Print values declared by the endpoint `extract:` directive (`[KEY]` optional) |

The five extraction flags are mutually exclusive. See
[Response Extraction](#response-extraction) below for the decision table and the
JMESPath cheat-sheet.

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
    extract:                       # named values, see Response Extraction
      issue_ids: "[*].id"
```

An endpoint can also declare an `extract:` map (named JMESPath values, exposed
on `response.extracted` and via `--show-extracted`) and a `server:` directive;
see [Response Extraction](#response-extraction) and
[Multi-server patterns](#multi-server-patterns) for the full semantics.

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

### Defaults and Server Profiles

When using `include:` to load external files, declare shared configuration once
in `rapi.defaults`. All included files inherit these values:

```yaml
rapi:
  defaults:
    base_url: https://${VIYA_HOST}
    credentials:
      type: file
      path: ~/.sas/credentials.json
      token_path: ".Default['access-token']"
    auth: bearer
    headers:
      Accept: application/json
      Content-Type: application/json

  include:
    - "./*/root.rapi.yml"
```

### Multi-server patterns

Two distinct patterns exist for multi-server workflows. They solve
different problems, so picking the right one matters.

#### Pattern A - `${VAR}` env vars (same API, different environments)

**Use when**: same API schema, different environments (e.g. SAS Viya
source vs target migration, dev vs staging vs prod).

**How**: declare a single `defaults` block with `${VAR}` placeholders.
The substitution is applied globally at YAML load time, so
`token_path` natively supports dynamic profile selection.

```yaml
rapi:
  defaults:
    base_url: https://${VIYA_HOST}
    credentials:
      type: file
      path: ~/.sas/credentials.json
      token_path: ".${ACTIVE_VIYA:-Default}['access-token']"
    auth: bearer
```

```bash
# Switch environment by changing two env vars
export VIYA_HOST=viya-source.example.com ACTIVE_VIYA=source
kstlib rapi transfer.export-jobs-create

export VIYA_HOST=viya-target.example.com ACTIVE_VIYA=target
kstlib rapi transfer.packages-upload
```

The `~/.sas/credentials.json` file holds named profiles (managed by
`sas-admin auth login`):

```json
{
  "Default": {"access-token": "...", "refresh-token": "..."},
  "source":  {"access-token": "...", "refresh-token": "..."},
  "target":  {"access-token": "...", "refresh-token": "..."}
}
```

`${ACTIVE_VIYA:-Default}` selects which profile is read. Each kstlib
invocation re-loads the YAML and re-expands the env vars, so switching
environment is just a matter of exporting two variables before each
command.

**Caveat**: in a long-running process, the env vars are baked in at
`load_rapi_config()` time. Changing them mid-process has no effect.
For CLI use this is a non-issue.

#### Pattern B - `rapi.servers` profiles (heterogeneous APIs)

**Use when**: a single project talks to multiple unrelated APIs with
different stacks and auth (e.g. github + jira + slack).

**How**: declare named profiles in `rapi.servers`. Each profile
overrides `base_url`, `credentials`, `auth`, and/or `headers`. Defaults
are inherited via deep merge (profile values win).

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

Resolve in Python:

```python
from kstlib.rapi import load_rapi_config

manager = load_rapi_config()

github = manager.resolve_server("github")
# github.base_url -> "https://api.github.com"
# github.auth    -> "bearer"  (inherited from defaults)
# github.headers -> {"Accept": "application/vnd.github+json", ...}

jira = manager.resolve_server("jira")
# jira.base_url -> "https://mycompany.atlassian.net"
# jira.auth    -> "api_key"  (overrides defaults)

default = manager.resolve_server(None)
# Returns defaults wrapped as ServerConfig(name="defaults", ...)

manager.server_names  # ["github", "jira"]
```

**Merge rules**: server values override defaults. For `headers` and
`credentials`, the merge is recursive (add or replace individual keys).

**Validation**: server names must match `[a-zA-Z][a-zA-Z0-9_-]*`
(max 64 chars). Only `base_url`, `credentials`, `auth`, and `headers`
keys are allowed. URL schemes are restricted to `http` and `https`.
Max 20 server profiles.

#### Decision matrix

| Question | Pattern |
|---|---|
| Same API schema, different hostnames? | A (env vars) |
| Different APIs (github + jira + ...)? | B (`rapi.servers`) |
| Need to switch env in shell scripts? | A |
| Need typed profiles inside Python code? | B |
| SAS Viya source/target migration? | **Always A** |

**Anti-pattern**: declaring SAS Viya source/target as
`rapi.servers.source` and `rapi.servers.target`. This duplicates
credential files and headers for nothing - use Pattern A instead.

#### The `server:` directive in `*.rapi.yml` files

Pattern B (`rapi.servers`) supports two YAML directives that pin a
specific endpoint or an entire API file to a named server profile. This
is useful when a project bundles many `*.rapi.yml` files and you want
each one to default to a specific backend without forcing the caller
to pass `--server` every time.

**File-level** (`server:` at the top of a `*.rapi.yml` file): all
endpoints in the file inherit this server unless they declare their own:

```yaml
# transfer/import-jobs.rapi.yml
name: transfer-import-jobs
server: target          # File-level: default for every endpoint below

endpoints:
  list:
    path: /transfer/packages
    method: GET
    # No server: directive here -> uses file-level "target"
```

**Endpoint-level** (`server:` inside an endpoint definition): overrides
the file-level value for this specific endpoint:

```yaml
endpoints:
  upload:
    path: /transfer/packages
    method: POST
    server: target      # Endpoint-level: explicit override
```

**Cascade priority** (highest to lowest):

1. Runtime override (CLI ``--server`` flag or ``call(server=...)`` kwarg)
2. Endpoint-level ``server:`` in the YAML file
3. File-level ``server:`` at the top of the YAML file
4. None - uses the static API config (no server resolution)

**Validation at load time**:

- If ``rapi.servers`` is configured and the directive references a
  known profile: validated and accepted.
- If ``rapi.servers`` is configured but the directive references an
  **unknown** profile: raises ``ServerNotFoundError`` immediately
  (fail fast at load, not at first request).
- If ``rapi.servers`` section is **absent**: logs a warning per
  reference (not fatal - the user may add the section later).

**Programmatic usage** with the ``server=`` kwarg:

```python
from kstlib.rapi import RapiClient

client = RapiClient()

# Use the github profile (overrides any server: directive in YAML)
response = client.call("github.repos-list", server="github")

# Async mirror
response = await client.call_async("github.user", server="github")

# Module-level convenience also accepts server=
from kstlib.rapi import call
response = call("github.user", server="github")
```

When a server is in effect, the request build pipeline applies the
profile in three places:

- **base_url** is replaced by ``server.base_url``
- **credentials** are resolved from the inline ``server.credentials``
  dict via ``CredentialResolver.resolve_inline`` (no name lookup,
  no caching - each call re-resolves)
- **headers** are layered between API and endpoint headers in the
  cascade ``api < server < endpoint < runtime``
- **auth_type** falls back to ``server.auth`` when present, otherwise
  to ``api_config.auth_type``, otherwise to ``"bearer"``

If the resolved server name does not exist in ``rapi.servers``, a
``ServerNotFoundError`` is raised before any HTTP call is made.
Passing ``server=None`` (the default) preserves the legacy behavior:
the static ``ApiConfig`` is used unchanged.

### Hard Limits

| Parameter | Default | Hard Min | Hard Max |
| - | - | - | - |
| `timeout` | 30.0 | 1.0 | 300.0 |
| `max_response_size` | 10MB | - | 100MB |
| `max_retries` | 3 | 0 | 10 |
| `retry_delay` | 1.0 | 0.1 | 60.0 |
| `retry_backoff` | 2.0 | 1.0 | 5.0 |
| `max_upload_size` | 100MB | - | 100MB |

## Key Features

- **Config-Driven**: Define APIs in YAML, call by name
- **CLI and Python**: Same config for both interfaces
- **Query Override**: YAML defaults can be overridden at runtime
- **External Files**: `*.rapi.yml` for modular API definitions
- **Auto-Discovery**: `RapiClient.discover()` finds local configs
- **Multi-Source Credentials**: SOPS, environment, files, keyring
- **Multipart Upload**: Auto-detected from Content-Type, uses httpx native `files=`
- **Output Modes**: `--raw` (pipeable), `--minify` (compact), `--quiet` (no Rich)
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

## Multipart File Upload

For endpoints that expect `multipart/form-data` (file uploads), set the `Content-Type` header:

```yaml
endpoints:
  packages-upload:
    path: /transfer/packages
    method: POST
    headers:
      Content-Type: multipart/form-data
      Accept: application/vnd.sas.summary+json
```

kstlib auto-detects multipart mode from the Content-Type header and handles boundary generation via httpx:

```bash
# Upload a file (auto-detected as multipart from endpoint config)
kstlib rapi transfer.packages-upload -b @package.json
```

```python
# Python: pass @filepath string
response = client.call("transfer.packages-upload", body="@package.json")

# Python: pass FilePayload for in-memory data
from kstlib.rapi import FilePayload

payload = FilePayload(filename="data.csv", data=b"a,b\n1,2", content_type="text/csv")
response = client.call("transfer.packages-upload", body=payload)
```

Optional fine-tuning via `multipart:` section:

```yaml
endpoints:
  upload:
    path: /upload
    method: POST
    headers:
      Content-Type: multipart/form-data
    multipart:
      field_name: dataFile           # default: "file"
      content_type: application/zip  # default: auto-detected from extension
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

## Response Extraction

REST payloads bury the value you actually want (an id, a count, a next-page
link) inside nested JSON. RAPI offers three ways to pull it out, from
zero-config to fully explicit.

### Heuristic accessors (zero-config)

A `RapiResponse` exposes convenience accessors tuned for HAL / SAS Viya style
collections. They work out of the box and never raise:

```python
# Collection {"count": 42, "items": [{"id": "a"}, {"id": "b"}]}
coll = client.call("myapi.items-list")
coll.count      # 42
coll.ids        # ['a', 'b']  (list[str], never None)
coll.has_next   # True when a links[?rel=='next'] entry is present
coll.next_url   # the next-page href (str | None)

# Single resource {"id": "abc-123", "name": "report"}
item = client.call("myapi.item-get", id="abc-123")
item.id         # 'abc-123'  (str | None)
```

The key lists are config-driven and overridable in `kstlib.conf.yml` without
touching code:

```yaml
rapi:
  extraction:
    id_keys: ["id", "uri", "name", "key", "objectId"]
    ids_paths: ["items[*].id", "members[*].id", "results[*].id", "data[*].id", "value[*].id"]
    count_keys: ["count", "total", "totalCount"]
```

An override is hardened on load (max 32 entries; `id_keys` / `count_keys` are
field names up to 64 chars; `ids_paths` are JMESPath expressions up to 512 chars
that must compile). An invalid override is ignored with a `WARNING [SECURITY]`
and that list is disabled, rather than crashing the client.

### Endpoint `extract:` directive (per-endpoint contract)

When a payload does not fit the heuristic, declare a `key: jmespath` map on the
endpoint in its `*.rapi.yml`. Each value is a JMESPath expression against the
parsed JSON body, except the reserved `$body` keyword, which captures the raw
response text (for non-JSON endpoints such as `text/plain`). Expressions are
compiled when the config loads (invalid ones fail fast), and the results land in
`response.extracted`, taking priority over the heuristic accessors:

Given a JSON payload from `GET /jobs/{id}`:

```json
{"result": {"state": "RUNNING", "worker": {"host": "node-7"}}}
```

and a `text/plain` body `RUNNING` from `GET /jobs/{id}/state`, declare:

```yaml
# jobs.rapi.yml
endpoints:
  job-status:                      # JSON response -> JMESPath on the parsed body
    method: GET
    path: /jobs/{id}
    extract:
      state: result.state         # "result" is a payload key, not a keyword
      worker: result.worker.host  # "state" / "worker" are names you choose

  job-state:                       # text/plain response -> $body grabs the raw text
    method: GET
    path: /jobs/{id}/state
    extract:
      value: $body                 # reserved keyword: the entire raw body
```

```python
resp = client.call("jobs.job-status", id="abc")
resp.extracted.state    # 'RUNNING'
resp.extracted.worker   # 'node-7'

# text/plain endpoint: $body returns the raw body
st = client.call("jobs.job-state", id="abc")
st.extracted.value      # 'RUNNING'
```

The keys on the left are the business names you pick; the values are standard
JMESPath evaluated against the payload, except `$body`, which captures the
whole raw response text (never a fragment) for non-JSON endpoints.

### `.get()` escape hatch and strict `.json()`

```python
resp.get("result.items[?ok].id")  # ad-hoc JMESPath, None on miss, never raises
resp.json()                       # strict dict|list, raises RapiError if not JSON
```

### CLI extraction flags

The same capabilities are exposed on `kstlib rapi`. The five flags are mutually
exclusive (at most one per call):

| Flag | Mode | Use when |
| - | - | - |
| `--show-id` | heuristic | You want the resource id and trust the config-driven keys (zero JMESPath). Exits 1 if none found. |
| `--show-ids` | heuristic | You want every id from a collection, one per line for piping. Empty result is OK (exit 0). |
| `--pick <jmespath>` | ad-hoc | You know the exact path and want one value. You spell out the JMESPath. Exits 1 if empty. |
| `--extract key=<jmespath>` | ad-hoc, named | You want several named values at once (repeatable). Empty result is OK (exit 0). |
| `--show-extracted [key[,key...]]` | declared | The endpoint declares an `extract:` map and you want declared keys by their business names, without re-typing the JMESPath. **One key** prints that value and exits 1 if it is missing or its expression matched nothing (like `--pick`); an empty collection is OK (exit 0). **Several keys** (comma or space separated) print a JSON object subset (exit 0): a key whose expression matched nothing appears as `null`, only an unknown key fails. **The bare flag** prints all declared keys as a JSON dict. A missing `extract:` directive always fails. Quote keys with spaces (`"v1 v2"`) or join with commas (`v1,v2`). |

```bash
# Heuristic: id of a single resource (pipeable, exit 1 if missing)
kstlib rapi myapi.item-get id=abc-123 --show-id

# Heuristic: every id of a collection, one per line
kstlib rapi myapi.items-list --show-ids | while read id; do echo "got $id"; done

# Ad-hoc: pick one value
kstlib rapi github.user --pick login

# Ad-hoc: several named values
kstlib rapi github.user --extract login=login --extract id=id

# Declared: a key from the endpoint extract: map above, by business name
kstlib rapi jobs.job-status abc --show-extracted state

# Declared: a subset of keys, as a JSON object (comma or quoted spaces)
kstlib rapi jobs.job-status abc --show-extracted state,progress

# Declared: every key from the extract: map, as a JSON dict
kstlib rapi jobs.job-status abc --show-extracted
```

Rule of thumb: reach for `--show-id` / `--show-ids` when the config heuristic
already knows your payload shape; reach for `--show-extracted` when the endpoint
declares an `extract:` map (the JMESPath lives in the YAML, you type the business
name); reach for `--pick` / `--extract` when you want to spell out the JMESPath
yourself or pull non-id fields.

### JMESPath cheat-sheet

`--pick`, `--extract`, the endpoint `extract:` map, and `response.get()` all
take [JMESPath](https://jmespath.org/) expressions. Common, spec-guaranteed
patterns:

| Expression | Result |
| - | - |
| `result.state` | nested field access |
| `items[*].id` | project a field across a list |
| `items[0].id` / `items[-1].id` | first / last element |
| `items[?ok].id` | filter (`ok` truthy), then project |
| `items[?state=='DONE'].id` | filter by equality |
| `items[?state != 'FAILED'].id` | filter by inequality |
| `items[?state=='DONE' && ok].id` | combine predicates with `&&` / `\|\|` |
| `items[?starts_with(name, 'pre')].id` | string functions: `starts_with`, `contains`, `ends_with` |
| `length(items)` | built-in function |
| `items[*].id \| [0]` | pipe to post-process |
| `{id: id, name: user.name}` | multiselect into a new shape |

```{warning}
**Date-range filters are not spec-guaranteed.** An expression like
`items[?created > '2026-01-01']` happens to work on `jmespath.py` for
zero-padded ISO-8601 strings, but the JMESPath specification reserves the
ordering operators (`>`, `>=`, `<`, `<=`) for **numbers**; a string operand
makes the comparison yield `null` (the item is filtered out). This is
non-spec behavior: it is not guaranteed and may break on a future or different
implementation. For durable filtering, use `starts_with(created, '2026-01')`
or compare a numeric timestamp field instead. See the
[JMESPath specification](https://jmespath.org/specification.html).
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
| `ServerConfig` | Resolved server profile (from `resolve_server()`) |

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
| `ServerNotFoundError` | Named server profile not in config |
