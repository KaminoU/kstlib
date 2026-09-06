# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [3.8.0] - 2026-09-06

### Added

- `ConfigLoader.loaded_paths`, the files the last load actually read, as
  absolute resolved paths in read order and without duplicates. A
  configuration is assembled from a cascade of files and their includes, and
  until now only the resulting values were visible, never their sources, so
  no policy could be applied to the files themselves: refusing to start when
  an include holding secrets is readable by others, or failing when a file
  that was meant to contribute never did. A load replaces the value, a load
  merging into the cache extends it, and a load that raises leaves it
  untouched. The configuration file shipped inside the package is not
  listed: it belongs to the library, not to the caller, so a policy written
  for the caller's own files does not have to make an exception for it.

- `create_on_get` on the configuration entry points (`load_config`,
  `load_from_file`, `load_from_env`, `ConfigLoader` and its three factory
  methods). Reading a key that does not exist writes that key into the
  configuration object, so inspecting a configuration modifies it: a
  membership test, a fallback lookup, or a misspelled name leaves behind a
  key no file ever declared, and a later test for that section then answers
  True. Passing `create_on_get=False` returns the same default without
  storing anything, nested sections included. The default is unchanged, so
  existing callers see no difference.

### Changed

- TOML configuration is now read with `tomllib` from the standard library on
  Python 3.11 and later, and the `tomli` package is only declared for Python
  3.10. The two provide the same reading API, so installing `tomli` on 3.11+
  added a dependency the interpreter already carries. Behaviour is unchanged
  on every supported version, including the graceful failure on 3.10 without
  the package: reading TOML raises, importing the library does not.

### Deprecated

### Removed

### Fixed

- The clean-install import gate could pass on an environment that was no
  longer clean. Its environments were reused between runs, and the installer
  that populates them never removes anything, so a dependency dropped from the
  project would survive from an earlier run and keep the gate green on the
  very operation it exists to prove. These environments are now rebuilt from
  scratch on every run.
- `load_config` documented the opposite of what it does: it promised that a
  missing key returns an empty container, when it returns `None` and chained
  access through a missing section raises `AttributeError`. The documented
  contract now matches the behaviour, which is unchanged. The function was
  also missing from the API reference, where it now appears.
- The root `--help` of the CLI described the callback implementation instead
  of the tool. Typer promotes the docstring of the root callback to the
  application description when no help text is declared, so the first line
  every user read was "Initialize the root Typer app and handle --version
  eagerly.", a sentence written for a maintainer of the file. The root
  application now declares its own help text, as every subcommand group
  already did, and the callback keeps its docstring for whoever opens the
  source.
- The tests that exercise the command-line interface ran only on demand.
  They carry a marker that both the local matrix and continuous integration
  excluded, and no environment selected them back, so a regression in the
  `kstlib` console script could have reached a release without any gate
  seeing it. They now run in both, and on every supported Python version in
  continuous integration. Tests that require real infrastructure stay
  excluded, as before.
- A release could be published while the examples or the documentation build
  were failing. Neither job was a prerequisite of the publication step, so a
  tag published with both of them red. Publication now waits for the two of
  them. The documentation is gated on the errors Sphinx reports, never on its
  warnings, which only the stricter local build refuses. That verdict could
  not see the build itself fail either: the exit code of the command was
  discarded by the pipe carrying its output, leaving a search through that
  output as the only judge. The pipe now reports the failure.
- The overview that opens the configuration API reference quoted three signatures
  that did not match the functions they described. A reader comparing the summary
  with the generated reference just below it found two different answers, and the
  summary was the wrong one. The six entry points listed there now carry the
  signature the code declares.
- Three command-line tests for `secrets doctor` read the real `.sops.yaml` of
  whoever ran them, so they could only pass on a machine that has one and failed
  everywhere else. They now stub the SOPS configuration lookup.

### Security

## [3.7.1] - 2026-08-14

### Added

### Changed

### Deprecated

### Removed

### Fixed

- The package could not be imported from a clean install on Python 3.13 and
  above. Eleven modules imported `typing_extensions` at module level while it
  has never been a declared dependency, so the import only ever succeeded
  because some other installed package happened to provide it. That stopped
  being true at 3.13: the declared dependencies pull `typing_extensions` only
  through version markers that end there, and from that interpreter on,
  `kstlib.alerts`, `kstlib.auth`, `kstlib.cli`, `kstlib.db`, `kstlib.helpers`,
  `kstlib.mail`, `kstlib.rapi`, `kstlib.resilience`, `kstlib.ui` and
  `kstlib.websocket.manager` all raised `ModuleNotFoundError: No module named
  'typing_extensions'` on import. Those imports now sit under `TYPE_CHECKING`,
  as `kstlib.alerts.manager` already did: they serve only the `Self` return
  annotation of context managers and factories, which is never evaluated at run
  time, so no dependency is added and nothing changes for callers. This is not
  a regression of 3.7.0: the module-level import has been present in every
  published release since 1.0.0, and only became reachable once dependency sets
  stopped providing `typing_extensions` incidentally on newer interpreters. An
  installation gate now builds the wheel, installs it with its declared
  dependencies alone and imports every public module, on every supported Python
  version and in CI as well as locally, so the package is verified the way it is
  consumed rather than only the way it is developed.

- `markupsafe` is now a declared dependency. `kstlib.monitoring` imports
  `Markup` from it at module level and returns that type from `render_html()`,
  so it is part of the public surface, yet the package was only ever present
  because `jinja2` happens to install it. That is a weaker guarantee than it
  looks: `jinja2` requires `MarkupSafe>=2.0` with no upper bound, so a future
  breaking release would have been accepted, installed and left to fail inside
  kstlib, with no version constraint we could state because the package was not
  ours to constrain. It is now declared as `>=2.0,<4`: the lower bound is the
  one `jinja2` already imposes, so no existing installation is disturbed, and
  the upper bound is the protection that was missing. Nothing changes for
  callers, and no new package is pulled in. Unlike the case above, this one
  could not have been caught by the installation gate at all: no interpreter
  version removes the package that supplies it, so a clean install succeeds on
  every supported Python while the dependency stays unstated.

### Security

## [3.7.0] - 2026-08-13

### Added

- `kstlib.secure.parse_certificate()` turns DER-encoded X.509 bytes into a
  frozen `CertificateInfo`: validity window as timezone-aware UTC datetimes,
  signature algorithm and hash, public key type and size, serial and SHA-256
  fingerprint as lowercase hexadecimal, and the BasicConstraints CA flag. The
  input is treated as untrusted: it is size-bounded by `MAX_CERTIFICATE_SIZE`
  (64 KiB, overridable per call) before parsing, and every failure surfaces as
  `CertificateTooLargeError` or `InvalidCertificateError`, both catchable as
  `KstlibError` or as `ValueError`. The function performs no network access, no
  chain building and no revocation check, and reaches no verdict: expiry and
  weak-crypto thresholds stay with the caller. An algorithm that the installed
  `cryptography` does not recognize is legitimate data rather than corruption,
  so such a certificate still parses: the algorithm is reported as its dotted
  OID, the field derived from it (`signature_hash`, `public_key_size`) is
  `None`, and the remaining metadata is unaffected. A non-positive `max_size`
  is a wiring mistake rather than a verdict on the data, so it raises
  `ValueError` at the call site instead of rejecting every certificate as
  oversized.

### Changed

- `kstlib auth check` now reads the `x5c` certificate of a JWKS entry through
  the hardened parsing primitive, which changes what the certificate panel and
  the `x509_info` field of the JSON report show in three cases. The serial is
  now lowercase hexadecimal padded to an even number of digits, so a serial
  previously shown as `123` reads as `0123`. A certificate the primitive
  refuses, one whose serial is not positive, one larger than 64 KiB, or one
  carrying an unreadable extension, now yields no certificate details at all
  instead of partial ones. And an `x5c` entry is size-checked before being
  decoded, rather than decoded first. In every rejection case the rest of the
  token report is still produced, and a warning now states that a certificate
  was present but could not be read, so that case is no longer reported the
  same way as a JWKS entry that simply carries no certificate.

### Deprecated

### Removed

### Fixed

- `Stopwatch.lap()` reported a first lap of zero, instead of the elapsed
  interval, whenever the performance counter read exactly `0.0` when the
  stopwatch was started. Only the first lap was affected, and only for callers
  that substitute the clock (deterministic tests, simulated time): the system
  performance counter does not return `0.0`, so timings measured against the
  real clock were already correct.
- `kstlib.ops` was usable at run time but invisible to type checkers and
  editors. A consumer running `mypy --strict` over any use of the module got
  `Module "kstlib" has no attribute "ops"` and had to silence it with a
  `type: ignore`, and editors offered no completion for it. Every other
  subpackage reachable through the top-level package was already visible, so
  `ops` alone behaved this way.

### Security

## [3.6.2] - 2026-08-06

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

- Raised the `cryptography` lower bound from 46.0.7 to 50.0.0 (direct
  dependency, lockfile pin moved from 49.0.0 to 50.0.0), covering
  GHSA-g6cj-pr64-35w5 / CVE-2026-69247 (high): PKCS#7 `EnvelopedData`
  decryption reported failures in distinguishable ways, and with
  distinguishable timing, handing an attacker a Bleichenbacher oracle against
  the content-encryption key. Affected versions are >= 44.0.0 and < 50.0.0.
  kstlib never calls the PKCS#7 decryption helpers itself, so the bound is
  raised for the benefit of applications that resolve `cryptography` through
  this package.
- Bumped `setuptools` from 80.0.0 to 83.0.0 in the build requirements, and its
  lockfile pin from 80.10.2 to 83.0.0 (build backend, plus a documentation
  extra transitive via `sphinx-togglebutton`), covering GHSA-h35f-9h28-mq5c /
  CVE-2026-59890 (medium): `MANIFEST.in` exclusion rules were matched against
  file names byte for byte with no Unicode normalization, so on
  normalization-preserving filesystems a file the maintainer meant to exclude
  could still be packed into a source distribution. Affected versions
  are < 83.0.0.

## [3.6.1] - 2026-07-20

### Added

### Changed

### Deprecated

### Removed

### Fixed

- `kstlib.auth`: reusing one `AuthProviderConfig` object across `OIDCProvider`
  constructions no longer freezes endpoints permanently. The constructor used
  to write issuer-derived placeholder URLs (`{issuer}/authorize`,
  `{issuer}/token`) into the caller's config; on a later construction those
  placeholders, or previously discovered endpoints, were reclassified as
  operator-explicit and discovery never updated them again, so a transient
  IdP outage at first use left the provider emitting authorization URLs that
  404 until process restart. The constructor no longer mutates the caller's
  config, endpoints written by discovery stay refreshable on reconstruction
  (in-memory provenance marker), and truly explicit operator endpoints still
  win over discovery. `discovery_mode` now correctly reports `"auto"` instead
  of a spurious `"hybrid"` for a reused auto-discovery config.
- `kstlib.auth`: `OIDCProvider.get_authorization_url()` now raises
  `ConfigurationError` instead of silently emitting an issuer-derived
  authorization URL when no authorization endpoint is available after
  discovery (document without `authorization_endpoint` and no explicit
  `authorize_url` configured).

### Security

## [3.6.0] - 2026-07-14

### Added

- `kstlib.utils.http_trace`: HTTP trace redaction is now config-extensible. A
  new `extra_sensitive_keys` argument on `HTTPTraceLogger` and
  `create_trace_event_hooks` adds keys on top of the built-in floor without
  ever replacing it; entries containing `*` or `?` are matched as
  case-insensitive `fnmatch` wildcard patterns. Config-driven consumers can set
  `auth.trace.extra_sensitive_keys` in YAML (a list of key names or patterns);
  an invalid type fails fast with `ConfigError`, and the built-in floor of
  OAuth2/OIDC credentials can never be disabled through configuration.
- `kstlib.auth`: `OAuth2Provider.revoke()` (inherited by `OIDCProvider`) accepts
  a new keyword-only `kinds` argument to target a subset of tokens, for example
  `kinds=("refresh_token",)` for a service that only holds the refresh token. It
  defaults to revoking both tokens (unchanged behavior); an unknown kind raises
  `ValueError`. Targeting a single kind keeps the boolean result meaningful for
  that kind (RFC 7009 returns 200 even for an invalid token, so the aggregate
  result alone is not proof of revocation).

### Changed

- `kstlib.utils.http_trace`: trace-redaction key matching is now
  case-insensitive, so cased variants of a secret key (for example
  `Access_Token`) are redacted as well.
- `kstlib.utils.http_trace`: redaction now covers three surfaces (request and
  response body, request headers, and URL query string) using the same key set,
  so `extra_sensitive_keys` extends all three. The `Authorization` header is now
  shown with a redacted value instead of being dropped.

### Deprecated

### Removed

### Fixed

- `kstlib.auth`: `OAuth2Provider.revoke()` no longer sends a revocation POST
  with an empty `token` value when the access token is empty. The access token
  is now falsy-guarded symmetrically with the refresh token, so a refresh-only
  token set posts only the refresh token.

### Security

- `kstlib.utils.http_trace`: sensitive HTTP request headers are now redacted at
  TRACE level. Previously only the `Authorization` header was withheld, leaking
  `Cookie` (including session cookies re-emitted by the httpx cookie jar),
  `X-Api-Key`, `Proxy-Authorization` and similar credential headers in clear. A
  dedicated `HEADER_SENSITIVE_KEYS` floor now masks their value while keeping the
  header name visible. URL credentials are likewise masked on both request and
  response log lines: query-string parameters (for example `?access_token=...`)
  and inline `user:pass@` userinfo.
- `kstlib.utils.http_trace`: `DEFAULT_SENSITIVE_KEYS` now redacts OpenID Connect
  and OAuth 2.0 bearer credentials that could previously appear in clear in HTTP
  traces at TRACE level: `id_token`, `id_token_hint`, `assertion`,
  `client_assertion`, `subject_token`, `actor_token`, `device_code`,
  `registration_access_token`, and `initial_access_token`. Key matching stays
  exact, so non-secret siblings (`token_type`, `client_assertion_type`,
  `subject_token_type`) remain visible for debugging.

## [3.5.0] - 2026-07-12

### Added

- `kstlib.auth`: structural discriminant on authentication errors.
  `DiscoveryError.status_code` and `TokenExchangeError.status_code` expose the
  HTTP status answered by the identity provider (`None` when no HTTP response
  was received), and `TokenExchangeError.retryable` mirrors
  `TokenRefreshError.retryable` (`True` for transport failures and provider
  5xx answers, `False` for definitive 4xx rejections and local guards). All
  additive keyword arguments; existing raise sites and signatures unchanged.
- `kstlib.auth`: server-side consumption profile. New
  `exchange_code_stateless()` on `OAuth2Provider` and `OIDCProvider` for
  multi-user services whose login and callback are separate concurrent
  requests: the caller owns CSRF state and PKCE, so the method touches no
  per-flow instance state, emits no spurious `[SECURITY]` warning, and does
  not persist the returned token (token storage is keyed by provider name,
  not by end user; per-user persistence belongs to the caller). It raises
  the same structured `TokenExchangeError` contract as `exchange_code()`.
  New `server_side` flag on `AuthProviderConfig` (and in provider YAML)
  suppressing the "redirect_uri host is not localhost" warning when a public
  callback endpoint is the nominal configuration. Defaults unchanged: CLI
  flows keep their behavior and warnings.

### Changed

### Deprecated

### Removed

### Fixed

- `kstlib.auth`: the "provider answered an error" vs "provider unreachable"
  discriminant on token exchange was an implicit, undocumented and untested
  property (`TokenExchangeError.error_code` None vs non-None), silently
  breakable by any refactor, and did not exist at all on OIDC discovery
  (`DiscoveryError.reason` is a plain string that would have to be parsed).
  The contract is now documented on the exception classes, including the two
  local pre-network guard codes (`state_mismatch`, `pkce_missing`) that carry
  an `error_code` without any provider response, and locked by regression
  tests so a consumer can render honest error messages (a provider 4xx
  rejection is no longer presentable as "provider could not be reached").
- `kstlib.auth`: the `exchange_code` docstring claimed `code_verifier` was
  "ignored for basic OAuth2" while the implementation forwards it to the
  token endpoint; the docstring now matches the behavior. The OIDC `nonce`
  is now documented as generated for provider-side replay hardening but not
  verified in the returned ID token claims (strict nonce verification is the
  consumer's responsibility).
- Dev Keycloak bench (`infra/`): healthcheck never reached healthy (missing
  `Connection: close`, the check waited for an EOF that keep-alive never sends),
  realm import warning (`openid` listed as a client scope in `defaultClientScopes`),
  and boot crash on some Docker/WSL2 stacks (unpinned container hostname breaking
  the embedded H2 database resolution).

### Security

- `kstlib.auth`: `AuthProviderConfig.client_secret` is now excluded from the
  dataclass `repr()` (`field(repr=False)`, same treatment as tokens): the
  secret no longer leaks in clear text through logs, tracebacks or dumps of
  the config object.
- `kstlib.db`: bound parameters no longer leak into logs through the `aiosqlite`
  driver. The driver logs every operation at DEBUG level with a repr that includes
  the SQL statement AND its bound values, so any secret stored through
  `AsyncDatabase` or `ConnectionPool` leaked in plain text as soon as DEBUG logging
  was active (encryption protects the file at rest, not the logs). The process-wide
  `aiosqlite` logger is now capped at INFO when a pool is created; its own
  INFO/WARNING/ERROR diagnostics are preserved, and levels already at INFO or
  stricter are left untouched. New `driver_debug=True` keyword on both classes
  opts out for conscious troubleshooting.

## [3.4.2] - 2026-07-11

### Added

### Changed

### Deprecated

### Removed

- Dropped the unused `aiosmtplib` dependency: it was declared but never imported
  (the SMTP transport uses the standard library `smtplib`). Its removal closes
  GHSA-v3q9-hj7j-63hq / CVE-2026-53533 (medium): SMTP command injection via CR/LF
  in sender/recipient addresses, by eliminating the package from the dependency
  tree.

### Fixed

### Security

- Bumped `soupsieve` lockfile pin from 2.8.3 to 2.8.4 (transitive dependency,
  docs extra only via `furo` -> `beautifulsoup4`), covering
  GHSA-2wc2-fm75-p42x / CVE-2026-49476 (high): memory exhaustion when compiling
  large comma-separated CSS selector lists, and GHSA-836r-79rf-4m37 /
  CVE-2026-49477 (high): ReDoS via catastrophic backtracking in the selector
  parser.

## [3.4.1] - 2026-07-05

### Added

### Changed

- **Docs theme naming**: Sphinx/Furo custom CSS properties renamed from a
  legacy prefix to the `--kstlib-*` prefix already used by the API reference
  styling, and theme comments reworded generically. No visual change.

### Deprecated

### Removed

### Fixed

### Security

- Bumped `joserfc` lockfile pin from 1.6.5 to 1.7.2 (transitive dependency via
  `authlib`), covering GHSA-wphv-vfrh-23q5 / CVE-2026-48990 (medium): RFC 7797
  `b64=false` JWS payloads could bypass `JWSRegistry` payload-size limits
  during deserialization.

## [3.4.0] - 2026-06-25

### Added

- **NEW string primitives in `kstlib.transform`**: `split`, `tr`,
  `removeprefix`, and `removesuffix` slice and clean already-decoded text
  (literal separators only, no regex). `split` extracts a delimited field
  by index (or returns the full list), `tr` translates/deletes characters
  (Unix `tr` style), and `removeprefix`/`removesuffix` strip a known
  affix. They are forward-only extractors and can be driven entirely from
  a `transforms:` chain in YAML config (a chain with only `forward:` and
  no `backward:`); calling `.backward()` on such a chain raises a clear
  `TransformConfigError`. `split.keep_empty` defaults to `false`, which
  intentionally diverges from `str.split` (path-friendly). A regex
  primitive is deliberately deferred (ReDoS hardening).

### Changed

### Deprecated

### Removed

### Fixed

- `kstlib.transform` is now reachable via lazy top-level attribute access
  on the `kstlib` package (e.g. `import kstlib; kstlib.transform.transform(...)`),
  consistent with the other submodules.

### Security

## [3.3.1] - 2026-06-20

### Changed

- **CLI error output now goes to stderr** (previously stdout). Command errors,
  validation failures and tracebacks render to stderr across all `kstlib` CLI
  commands, so stdout stays clean for data/JSON in shell pipelines (Unix
  data/diagnostics separation).
- Locked `cryptography` to 49.0.0 (CI now tests the version users already
  resolve via the open `>=46.0.7` floor; pulls the newer bundled OpenSSL). The
  `pyproject.toml` floor is unchanged.

### Fixed

- **`kstlib rapi` no longer prints a raw traceback** on a missing or invalid
  path parameter: a clear error (exit code 1) is rendered instead
  (`httpx.InvalidURL` and missing-parameter errors are caught). Path parameters
  now reject control characters (e.g. newline) in addition to null bytes and
  path traversal.

## [3.3.0] - 2026-06-18

### Added

- **NEW `console.stream` config key** (`kstlib.logging`): route the Rich console
  log output to `stdout` (default) or `stderr` via `kstlib.logging.console.stream`.
  Routing logs to `stderr` keeps `stdout` clean for data/JSON in CLI pipelines
  (Unix data/diagnostics separation). Backward compatible (absent key = `stdout`);
  invalid values raise `ConfigError` (fail-fast).
- **`--show-extracted` accepts multiple keys** on `kstlib rapi`:
  `--show-extracted v1,v2` or `--show-extracted "v1 v2"` (comma/space separated)
  prints a JSON object of the requested extracted keys. A single key still prints
  its bare value; the bare flag still prints all keys.

## [3.2.0] - 2026-06-12

### Added

- **NEW response extraction accessors on `RapiResponse`** (`kstlib.rapi`):
  `.id`, `.ids`, `.count`, `.next_url`, `.has_next` resolve common identifiers
  out of HAL / SAS Viya style payloads, plus a `.get(jmespath)` escape hatch
  (never raises) and a strict `.json()` accessor. The heuristic key lists are
  config-driven and overridable via the new `rapi.extraction` section of
  `kstlib.conf.yml` without touching code.
- **NEW per-endpoint `extract:` directive** in `*.rapi.yml`: a `key: jmespath`
  map (with the reserved `$body` keyword for the raw response text) compiled
  when the config loads, so invalid expressions fail fast. Results populate
  `RapiResponse.extracted` and take priority over the heuristic accessors.
- **NEW CLI extraction flags on `kstlib rapi`**: `--pick <jmespath>` (`-p`,
  ad-hoc single value), `--extract key=jmespath` (named, repeatable),
  `--show-id` and `--show-ids` (config-driven heuristic). The four are mutually
  exclusive; `--show-id` / `--pick` exit 1 on an empty result, while
  `--show-ids` / `--extract` treat empty as a legitimate result (exit 0).
- **NEW `rapi.extraction` config section** (`id_keys`, `ids_paths`,
  `count_keys`) in the embedded `kstlib.conf.yml`: the single source of the
  extraction heuristic defaults, discoverable and overridable.
- **NEW CLI flag `--show-extracted [KEY]` on `kstlib rapi`**: print values
  declared by the endpoint `extract:` directive by their business name
  (`--show-extracted object_ids`), or every declared key as a JSON dict with
  the bare flag. Mutually exclusive with the four other extraction flags and
  compatible with `--raw` / `--minify` / `--out` / `--quiet`. Exits 1 when the
  requested key (or the whole directive) is missing or its expression matched
  nothing; a declared key holding an empty collection is a legitimate result
  (exit 0).

### Changed

### Deprecated

### Removed

### Fixed

- **Restored the implicit CLI endpoint routing** (`kstlib rapi <api>.<endpoint>`
  without the `call` subcommand) on Typer 0.26+. Typer 0.26 ships a vendored
  click whose `UsageError` is a distinct class from `click.UsageError`, so the
  previous exception-based redirect never matched and the shortcut failed with
  `No such command`. The redirect now rewrites the arguments before resolution,
  based on `get_command()` returning `None` for unknown names, a contract that
  holds across the whole supported Typer range (`>=0.19,<1`). The explicit
  `kstlib rapi call ...` form was never affected.

### Security

- **Hardened the `rapi.extraction.*` config input** (defense in depth): each
  overridden list is validated on resolution (max 32 entries; field names up to
  64 chars; `ids_paths` JMESPath expressions up to 512 chars that must compile).
  An invalid override is rejected with a `WARNING [SECURITY]` (naming the list
  and the violation, never the offending value) and that list degrades to empty
  instead of crashing the client at initialization.
- **Capped two RAPI config inputs** (defense in depth): endpoint `extract:`
  key names are limited to 64 chars (aligned with the other field-name gates)
  with bounded validation messages, and `*.rapi.yml` files larger than 10 MiB
  are rejected before parsing, mirroring the main config loader cap.

## [3.1.0] - 2026-06-01

### Added

- **NEW password hashing helpers** in `kstlib.secure`
  (`hash_password`, `verify_password`, `needs_rehash`), backed by Argon2id
  via the optional `argon2-cffi` dependency (`pip install kstlib[passwords]`).
  Cost parameters follow the `kwargs > kstlib config > defaults` cascade with
  OWASP-aligned defaults (RFC 9106 low-memory: `time_cost=3`,
  `memory_cost=65536` KiB, `parallelism=4`). Values resolved below the OWASP
  minimum baseline (19 MiB / `t=2`) are clamped up and a `WARNING [SECURITY]`
  is logged. Passwords longer than `MAX_PASSWORD_LENGTH` (4096 bytes) are
  rejected as an anti-DoS guard, and passwords and hashes are never written
  to the logs.
- **NEW exceptions `PasswordError` and `InvalidPasswordHashError`**
  (`kstlib.secure`), both under `KstlibError`. `verify_password` returns
  `False` on a wrong password and raises `InvalidPasswordHashError` only when
  the stored hash is corrupt or not a valid Argon2 hash.

## [3.0.0] - 2026-05-22

> **BREAKING changes** : `WebSocketManager.close()` semantic has changed
> (see Changed section below for full details and migration hint).

### Added

- **NEW `WebSocketManager.is_recoverable` property** for external
  watchdog consumers. Returns True when the connection is dead but NOT
  intentionally shutdown (`is_dead and not is_shutdown`). Helps
  distinguish accidental disconnects (graceful `close()` end-of-scope
  or reactive `kill()`) from intentional terminal shutdowns
  (`force_close()` or `shutdown()`). Watchdog consumers should use this
  property rather than `is_dead` to avoid restarting an intentional
  shutdown loop.
- **Logging caller context in `debug` and `trace` preset file format**
  (`src/kstlib/kstlib.conf.yml`) : log records emitted with these presets
  now include `[<filename>:<lineno> <funcName>]` for diagnostic visibility
  on post-mortem incident investigation. Console output remains unchanged
  (Rich `show_path=true` already provides visual caller location). Other
  presets (`dev`, `prod`, `trace_mail`) are not affected so clean
  production logs are preserved.
- **`MinifyRequiresRawError(RapiError)` exception**
  (`kstlib.rapi.exceptions`) : exported via `kstlib.rapi.__all__`.
  Surfaces the constraint that compact JSON (`minify`) is incompatible
  with Rich console rendering, so callers must request raw output too.
  The CLI emits the same constraint via `typer.BadParameter` for native
  Typer error formatting ; this exception is reserved for callers that
  need to raise it programmatically (for example, future pipeline
  steps exposing equivalent `minify` and `out` semantics). Default
  message exposed as the `DEFAULT_MESSAGE` class attribute and
  contains the canonical hint pointing to `--raw --minify`.
- **`AuthExpiredError(AuthError)` exception**
  (`kstlib.auth.errors`) : exported via `kstlib.auth.__all__`.
  Distinct from the existing `TokenExpiredError(TokenError)`. The two
  cover different lifecycle points : `AuthExpiredError` is raised by
  consumers (typically `kstlib.rapi.client`) on receiving an HTTP 401
  at runtime, signalling that a token which was valid at send time
  has been expired or invalidated by the identity provider during
  the session ; `TokenExpiredError` is raised by `kstlib.auth` when
  a loaded token is detected as already expired before the request
  is sent (client-side pre-flight check). The new class carries two
  optional attributes `token_source` (label such as
  `'~/.sas/credentials.json'`, `'env:KSTLIB_TOKEN'`,
  `'sops:secrets/api.sops.json'`) and `suggested_action` (re-auth
  hint such as `'Run: sas-admin auth login -u <user>'`), mirrored
  into the `details` dict for introspection. Used by upcoming runtime
  401 detection in `kstlib.rapi.client`.

### Changed

- **`WebSocketManager.close()` semantic now graceful (BREAKING v3.0.0)** :
  previously an alias for `force_close()` (State=CLOSED terminal, cannot
  reconnect). Now closes gracefully : State=DISCONNECTED non-terminal,
  reconnection remains possible via explicit `connect()` or auto-reconnect.
  Restores Python `async with` convention so `__aexit__` no longer
  prevents reconnection. The `_auto_reconnect` flag is preserved. The
  method is idempotent (no-op if state is already CLOSED or DISCONNECTED).
  Migration : use `force_close()` explicitly for emergency stop, or
  `shutdown()` for intentional SIGINT-like shutdown.
- **`WebSocketManager.force_close()` now marks `is_shutdown=True`** :
  the intentional emergency stop now sets the shutdown event in addition
  to flipping `auto_reconnect=False` and moving to State=CLOSED. Helps
  watchdog consumers distinguish reactive disconnect (via `kill()`,
  `is_shutdown=False`) from intentional terminal shutdown (via
  `force_close()` or `shutdown()`, `is_shutdown=True`). The new
  `is_recoverable` property (see Added section above) leverages this
  distinction.
- **CLI `rapi call --minify` without `--raw` now fails fast** : the
  combination was previously silent (Rich console rendering reformats
  output regardless of compact JSON flags, so `--minify` alone had no
  visible effect). The CLI now rejects the combination at command
  entry via `typer.BadParameter` with a hint message pointing to
  `--raw --minify`. The validation runs before any RapiClient
  construction or endpoint resolution so no I/O occurs on a rejected
  invocation.
- **`rapi.client` now detects access token expiration on HTTP 401**
  : `RapiClient.call` (and its async counterpart) now inspects every
  parsed response and raises `AuthExpiredError` when the response
  indicates token expiration (heuristic : body contains `expired`,
  `invalid_token`, or `token expired` case-insensitive, or
  `WWW-Authenticate` header contains `invalid_token` per RFC 6750).
  The exception carries a sanitized `token_source` label and a
  contextual `suggested_action` hint derived from the credential
  source (file path, env var, SOPS path, or provider name) without
  ever exposing the secret material itself. Backward compat
  preserved : HTTP 401 responses that lack expiration markers
  continue to surface as `RapiResponse(ok=False)`. A tagged
  `WARNING [SECURITY]` log entry is emitted before the raise
  (status code, content type, credential source label only ; never
  the response body or the token).
- **`rapi.client` now also emits a user-facing `ERROR` log with
  the re-auth hint** before raising `AuthExpiredError`. The
  `WARNING [SECURITY]` audit entry is preserved untouched ; the
  new `ERROR` line targets human operators consuming kstlib as a
  library (the actionable hint stays visible even if the
  exception is swallowed or generically caught upstream). Same
  sanitization contract applies : the message references the
  credential source label (file path / env var name / SOPS path
  / provider name) but never the token value, the response body,
  or the `Authorization` header.
- **CLI `rapi call`** : `AuthExpiredError` now triggers exit code
  4 (distinct from the generic exit code 1 used for other errors).
  The error message displays the actionable re-authentication
  hint on a dedicated `Hint:` line alongside the token source on
  a `Source:` line. Shell scripts wrapping `kstlib rapi` can now
  detect token expiration specifically and trigger an automated
  re-login flow without having to parse the message body.

### Deprecated

### Removed

### Fixed

- **RAPI `--minify` now enforced at command entry** : the `--minify` CLI flag was
  silently ineffective without `--raw` because Rich console rendering
  reformats output regardless of compact JSON flags. Add
  `_validate_output_flags()` rejection at command entry with an
  explicit hint instead of swallowing the user intent.
- **RAPI surfaces expired OAuth/OIDC tokens as `AuthExpiredError`** : `RapiClient` no
  longer swallows expired SAS Viya (or any OAuth/OIDC) tokens
  behind a generic `RapiResponse(ok=False)` exit. The detection
  helper `_check_auth_expired()` invoked inside both
  `_execute_with_retry` and `_execute_with_retry_async` surfaces
  `AuthExpiredError` with a contextual re-authentication hint
  (`sas-admin auth login` for SAS Viya credentials files, env var
  refresh hint for env-based credentials, SOPS file path hint for
  SOPS-backed credentials, `kstlib auth login` for provider-backed
  credentials). The CLI exit code mapping to a distinct value
  for `AuthExpiredError` ships in a follow-up commit.
- **Watchdog timeout test determinism** : `tests/resilience/test_watchdog.py::test_raise_on_timeout`
  relied on a real `time.sleep(1.2)` plus the background monitor thread, making it
  timing-sensitive and flaky under runtime load (notably on Python 3.14). Rewritten
  to mock `time.monotonic` and drive the timeout check synchronously, making the test
  deterministic and independent of runtime speed.
- **`SecretError` and `ConfigExportError` now inherit from
  `KstlibError`** : both classes previously extended only
  `RuntimeError`, so they escaped the library-wide
  `except KstlibError` catch-all honored by every other kstlib
  exception. `SecretError` (`kstlib.secrets`, base of
  `SecretNotFoundError` and `SecretDecryptionError`) now extends
  `(KstlibError, RuntimeError)`, and `ConfigExportError`
  (`kstlib.config`) now extends `(ConfigError, RuntimeError)`.
  `RuntimeError` is retained in both cases, so existing
  `except RuntimeError` handlers and `isinstance` checks are
  unaffected : the change only widens catchability.

### Security

- **`idna` lower bound raised to `>=3.15`** (transitive via `httpx`) :
  addresses CVE-2026-45409, a quadratic-time denial of service on
  oversized input that bypassed the CVE-2024-3651 mitigation. Fixed
  upstream in idna 3.14 ; the floor is set to 3.15 (the Dependabot
  target, which also adds an early DNS-length cap on labels).
- **`authlib` lower bound raised to `>=1.6.12`** : upstream fix for
  an open redirect to an unvalidated `redirect_uri` on
  `InvalidScopeError` in the OpenID implicit and hybrid grants
  (authlib 1.6.12). No CVE assigned upstream. The locked and tested
  authlib version is 1.7.2 ; authlib 1.7.x delegates JOSE operations
  to `joserfc`, a new transitive dependency.

## [2.7.1] - 2026-05-13

### Fixed

- **Throttle adversarial tests determinism** : `tests/mail/test_throttle_adversarial.py`
  was sensitive to runtime speed (logging overhead, CPU contention, accumulated test
  runtime), causing off-by-one assertion failures on slower runs (regression-prone
  on Python 3.10-3.13). Add autouse fixture `_frozen_clock` that monkeypatches
  `time.monotonic` to `0.0` for all tests in the file, making tests deterministic
  and independent of runtime speed (no token refill during the test window). Harden
  two ceiling assertions now made strict by the frozen clock:
  - `test_recursion_via_notify_is_throttled`: `<= 5` -> `== 5`
  - `test_combined_stress_does_not_exceed_rate_per_window`: `<= 6` -> `== 5`
- **Cross-platform LF line endings enforced via `.gitattributes`** : explicit
  `eol=lf` on `*.py`, `*.pyi`, `*.toml`, `*.yml`, `*.yaml`, `*.json`, `*.ini`,
  `*.cfg`, `*.conf`, `*.md`, `*.rst`, `*.txt` and on `LICENSE`, `CHANGELOG`,
  `README` documentation files. Without this, Windows checkout produced CRLF
  in worktree while `ruff format` enforces LF (`pyproject.toml`
  `line-ending = "lf"`), causing systematic `ruff format --check` failures on
  dev environments.
- **`uv.lock` line endings enforced as LF** : new `# --- Lockfiles ---` section
  in `.gitattributes` adds `uv.lock text eol=lf`. uv writes LF natively but
  `core.autocrlf=true` on Windows would re-introduce CRLF at checkout, creating
  churn. Explicit target marks the lockfile's criticality (source of truth for
  resolved dep versions).
- **`.coveragerc` untracked from repository** : the file was previously committed
  but is generated locally for test coverage measurement. Removed from git
  tracking and added to `.gitignore`.
- **Pre-commit hook documentation hardening (Windows OneDrive users)** :
  `CONTRIBUTING.md` adds an optional Windows hardening section recommending
  to host the virtualenv outside OneDrive sync via the
  `UV_PROJECT_ENVIRONMENT` environment variable (session isolation: defined
  explicitly per terminal session, never persisted globally). Symlinks are
  NOT recommended because OneDrive (and most folder-sync tools) traverse
  symbolic links and sync the target content anyway, defeating the purpose.

### Security

- **deps: bump urllib3 2.6.3 -> 2.7.0**
  ([CVE-2026-44431](https://nvd.nist.gov/vuln/detail/CVE-2026-44431),
  [CVE-2026-44432](https://nvd.nist.gov/vuln/detail/CVE-2026-44432)) -
  Two HIGH severity vulnerabilities patched by urllib3 2.7.0:
  - **CVE-2026-44431** : `ProxyManager.connection_from_url` did not strip
    sensitive headers (`Retry.remove_headers_on_redirect`) on cross-host
    redirect.
  - **CVE-2026-44432** : decompression-bomb safeguards bypass on `read(amt=N)`
    with Brotli compression + `drain_conn()` after partial read (CWE-409,
    client resource DoS).

  Lockfile resolution stayed conservative (urllib3 only, zero collateral).

## [2.7.0] - 2026-05-09

### Added

- **Mail throttle (anti-spam kill switch)** : `kstlib.mail.MailThrottle`
  enforces a token-bucket rate limit on every `MailBuilder.send()`,
  including indirect calls via the `@mail.notify` decorator. Stops
  runaway batch loops, recursive sends, exception-handler floods, and
  concurrent thread/asyncio races at their first overrun. Built on top
  of the existing `kstlib.resilience.RateLimiter` (Token Bucket,
  thread-safe and asyncio-safe).

  Configuration cascade, highest priority first :

  1. Per-builder kwarg `MailBuilder(throttle=False)` (disable),
     `MailBuilder(throttle={"rate": 100, "per": 3600.0})` (custom).
  2. `mail.presets.<name>.throttle.<key>` (preset-level YAML override).
  3. `mail.throttle.<key>` (mail-wide YAML default).
  4. Code defaults : `enabled=true`, `rate=20`, `per=60.0`,
     `on_exceed=raise`.

  Each key cascades independently. Two policies are supported on bucket
  empty : `raise` (emits `WARNING [SECURITY]` and raises
  `MailThrottledError`) and `warn` (emits `WARNING [SECURITY]` and
  drops the send silently). Mode `drop` is intentionally rejected at
  init : a security event must never be silent (kstlib logging
  convention).

  A singleton `MailThrottle` is shared across all builders that use the
  same preset, including `_snapshot()` copies taken by `@mail.notify`,
  preventing bypass via creating many builder instances. The registry
  persists across `kstlib.config.clear_config()` calls : the throttle
  is operational, not a preference.

  Hard limits enforced at init (`rate` in `[1, 1000]`, `per` in
  `[1.0, 86400.0]`) reuse the existing alerts hard-limit constants.
  YAML keys outside `{enabled, rate, per, on_exceed}` are rejected
  (anti-typo). Invalid types and out-of-bounds values raise
  `MailConfigurationError` at builder init, not at send time.

- **`MailThrottledError` exception** : raised by `MailBuilder.send()`
  in mode `raise` when the throttle bucket is empty. Inherits from
  `MailError`. Carries the throttle parameters in the message to help
  the caller decide on a backoff strategy.

- **`mail.throttle` YAML section** : new section in
  `src/kstlib/kstlib.conf.yml` with documented defaults and an inline
  example showing per-preset override.

- **Logging instrumentation for mail throttle** : every
  `MailBuilder.__init__` emits a `DEBUG` log on the `kstlib.mail.throttle`
  logger reporting the resolved `rate`, `per`, `on_exceed`, source level
  (`preset` / `mail` / `default`) and preset name. Every blocked send
  emits exactly one `WARNING [SECURITY]` log line (no batching). The
  log never includes the message body, sender, recipients, or
  attachments : only a sanitized subject (truncated to 80 chars,
  null-byte filtered) is included.

- **Sphinx documentation** : new section "Throttle (anti-spam
  protection)" in `docs/source/features/mail/index.md` (label
  `mail-throttle`) covering the four real-world spam scenarios, the
  cascade resolution, the two on_exceed modes, the singleton-per-preset
  contract, the hard limits, and recommendations for production usage.
  Cross-link added from the `@mail.notify()` decorator section.

### Changed

- **Mail sends are now throttled by default at 20 mails per 60 seconds,
  raising `MailThrottledError` on overrun.** This is a behavior change
  versus 2.6.0 where mail sends were unbounded.

  To restore the previous unbounded behavior on a single builder, pass
  `MailBuilder(throttle=False)`. To restore globally, set
  `mail.throttle.enabled: false` in `kstlib.conf.yml`. Both are
  recommended only for tests, scripts that send a single mail and exit,
  or specific business cases where the upstream system already enforces
  a rate limit.

  See `docs/source/features/mail/index.md` section "Throttle" for
  cascade tuning and operational recommendations.

### Deprecated

### Removed

### Fixed

### Security

- **Anti-spam kill switch on mail sends** : closes a real robustness
  gap where a buggy `for` loop, `@mail.notify` on a hot function,
  unbounded recursion, or exception handler that mailed could blacklist
  an SMTP relay's source IP, exhaust an external provider quota, or
  saturate a destination inbox. The throttle bounds the blast radius
  to `rate` mails per `per` seconds and emits `WARNING [SECURITY]`
  logs on every blocked send so the event is observable in operational
  dashboards.

## [2.6.0] - 2026-05-01

### Added

- **`--log-module` factorized syntax** : the CLI flag now supports
  three syntaxes for module-level logging configuration :
  - `--log-module kstlib.rapi.config=TRACE` (existing, fully-qualified)
  - `--log-module rapi.config=TRACE` (NEW : `kstlib.` auto-prepended)
  - `--log-module DEBUG=foo.bar,baz.qux` (NEW : reverse mode, level
    groups module list)

  Mode is decided on the LEFT side : a known level token (case-
  insensitive, in `TRACE`, `DEBUG`, `INFO`, `SUCCESS`, `WARNING`,
  `ERROR`, `CRITICAL`) triggers reverse mode, anything else is
  treated as a module name. Levels are case-insensitive on both sides.
  Whitespace around commas and inside the module list is trimmed.
  Empty entries skipped silently. Repeated `--log-module` flags
  accumulate ; later entries on the same logger overwrite earlier
  ones.

  Logger name validation uses the regex
  `^kstlib\.[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*$` after the optional
  auto-prepend, rejecting double dots, leading dots, embedded
  whitespace, and non-identifier characters. Invalid entries emit a
  `WARNING` (or `WARNING [SECURITY]` for malformed logger names) on
  the `kstlib_logging_internal` logger and the offending occurrence
  is skipped without aborting the command. Activate the observer
  via `logging.getLogger("kstlib_logging_internal").setLevel(logging.WARNING)`.

### Changed

- **Sphinx logging introspection guide** : cascade priority schema
  reverted to the clean three-layer model (YAML defaults,
  preset.modules, CLI `--log-module`), new section "Module mutes
  are persistent by design" documenting the v2.6.0 behaviour, new
  "CLI module overrides" section listing the three syntaxes, and
  updated behavior matrix illustrating the persistent-mute interplay
  between handler level and per-logger level.

### Fixed

- **Logging modules cascade** : YAML default mutes
  (`kstlib.rapi.config: WARNING`, `kstlib.config.loader: WARNING`)
  are now preserved when CLI verbosity flags (`-v`/`-vv`/`-vvv` or
  `--log-level`) are used. Previously in v2.5.0, these mutes were
  reset by verbosity flags (the so-called "Option A" design),
  defeating the purpose of having defaults for verbose modules. The
  embedded mutes are now persistent by design ; verbosity flags only
  adjust the root handler level. To explicitly bypass a mute under
  verbosity, use `--log-module name=<level>` (or any of the new
  factorized syntaxes).

  Friction reproducer that motivated the change :

  ```bash
  # In v2.5.0 : noisy 'rapi.config' was un-muted by -vvv, drowning
  # the output the user wanted to see.
  kstlib -vvv rapi list

  # In v2.6.0 : 'rapi.config' stays at WARNING under -vvv ; the rest
  # of the kstlib hierarchy runs at TRACE as requested.
  kstlib -vvv rapi list

  # Explicit bypass when the user does want rapi.config at TRACE.
  kstlib -vvv --log-module rapi.config=TRACE rapi list
  ```

- **`--log-module` parser robustness** : pathological inputs (no `=`,
  empty side, unknown level, malformed logger name, only commas in
  reverse mode, embedded whitespace or punctuation in a module name)
  no longer abort the command with an exception. The CLI now warns
  on `kstlib_logging_internal` and skips the offending entry,
  applying the remaining valid entries normally.

## [2.5.0] - 2026-05-01

### Added

- **`kstlib._shared.redaction`** module consolidating sanitization helpers used
  across kstlib : `redact_sensitive()` (regex-based, AWS ARN, AKIA keys, paths),
  `mask_webhook_url()` (Slack/Discord/Teams tokens), `mask_url()` (URL with
  inline credentials or sensitive query parameters). Replaces local helpers
  previously scattered in `secrets/providers/sops.py` and
  `alerts/channels/slack.py`. Available at `from kstlib._shared.redaction
  import redact_sensitive, mask_webhook_url, mask_url`.
- **`kstlib.logging.modules`** YAML configuration for per-logger level override.
  Cascade : global config -> active preset -> CLI `--log-module` flag (replaces
  total) -> CLI verbosity flags (`-v`/`-vv`/`-vvv` or `--log-level`) reset the
  YAML cascade when no `--log-module` is supplied. Default sans entries means
  no per-module filtering. Validation on YAML load : invalid logger names
  (must start with `kstlib.`) and invalid levels are skipped with WARNING.
- **CLI flag `--log-module name=level`** repeatable, format `name=level`. When
  at least one is supplied, it REPLACES the YAML modules cascade.
- **Default YAML mutes** for verbose modules at startup :
  `kstlib.rapi.config: WARNING` (silences ~1300+ DEBUG/TRACE per Viya startup)
  and `kstlib.config.loader: WARNING` (silences cascade verbose with multiple
  includes). Override available via user `kstlib.conf.yml`, presets, or CLI
  flags.
- **`dev` vs `debug` presets differentiation** : `dev` keeps `output: console`
  / level `DEBUG` (rapid iteration), `debug` switches to `output: both` (console
  + persisted file for grep) / level `TRACE` (deep investigation).
- **Sphinx documentation** : new section "User responsibility" (6 cases :
  NotifyCollector, transform callable, StepResult, NotifyResult, AlertMessage,
  WebSocket callbacks) + new "Logging introspection guide" (convention,
  cascade, presets, recipes, HTTPTraceLogger reference).
- **`MailBuilder.notify` `redact_user_data: bool = True`** : default-on opt-in
  redaction of `exception` / `return_value` / `traceback_str` in
  `NotifyCollector` summary HTML. User can opt-out with `redact_user_data=False`
  for cases where exception messages are known safe.
- **`NotifyCollector.render_html`** : new redaction toggle aligned with
  `MailBuilder.notify`.
- **`WARNING [SECURITY]` tag** systematically applied before raising on
  security events across modules : path traversal in `secure/fs.py`, drive
  escape, null byte injection in `db/cipher.py`, `db/aiosqlcipher.py`,
  `pipeline/_base.py`, `auth/providers/oauth2.py` (state mismatch CSRF),
  `ssl.py` (null byte CA bundle), `ops/validators.py`, `rapi/config.py`,
  `rapi/client.py`, `utils/validators.py`. Total : 15+ occurrences.
- **`kstlib_logging_internal`** internal logger (underscore-prefixed, outside
  `kstlib.*` hierarchy) for logging the `LogManager` setup itself without
  recursion. Used by `kstlib.logging.manager` to break the silent fail-paths.
- **~80 logging seeds** across kstlib modules (rapi, config, auth, transform,
  pipeline, secrets, mail, alerts, websocket, db, secure, ssl, cache, helpers,
  limits, ui, utils, logging) following the convention 7 levels (TRACE/DEBUG/
  INFO/SUCCESS/WARNING/ERROR/CRITICAL). INFO and SUCCESS used sparingly,
  TRACE/DEBUG split between detail (per-item, firehose) and synthesis
  (decisional branching).
- **Smoke tests** : `tests/security/test_log_no_secret_leak.py` (validates 4
  HIGH fix points), `tests/smoke/test_logging_noise_reduction.py` (asserts
  `-vvv` produces < 200 useful lines on typical rapi call), `tests/smoke/test_logging_modules_kill_switch.py`
  (validates YAML mute silences verbose modules).
- **Furo theme consistency tweaks** : `.sd-card` and `.admonition` background
  forced to `--kstlib-surface` for visual coherence with code blocks. 3 Furo
  gotchas inscribed in `development/quality.md` (no `{contents}` directive
  with Furo, card cascade override needs `!important`, build local
  verification).

### Changed

- **`HTTPTraceLogger`** (in `kstlib.utils.http_trace`) generalized as the
  official infrastructure for HTTP redaction across all httpx-based modules.
  Existing adopters (`auth/providers/oauth2.py`, `mail/transports/gmail.py`,
  `mail/transports/resend.py`) unchanged. New module additions are encouraged
  to import and use it instead of building local redaction.
- **Anti-pattern "stderr-in-WARNING" remediation** (~9 occurrences) : Option C
  split-levels applied (short WARNING + redacted detail in TRACE) on
  `auth/providers/base.py`, `auth/config.py`, `config/loader.py`,
  `mail/transports/*`, `alerts/channels/slack.py`. Pipeline subprocess user
  applies Option A (drop stderr from log, kept in `StepResult.stderr` for user
  inspection).
- **Anti-pattern "raise sans log on security events" remediation** : `[SECURITY]`
  tag applied before each raise across the 15+ identified occurrences.
- **`pipeline.runner` log levels reclassified** following convention 7 levels :
  step skipped now `DEBUG` (was `INFO`), pipeline completed now `SUCCESS` (was
  `INFO`), step result successful now `SUCCESS`. Reduces INFO bias on long
  pipelines.
- **`secrets/providers/sops.py`** drops local `_redact_sensitive_output()`
  helper, imports `redact_sensitive` from `_shared/redaction.py`. Behavior
  identical with finer granularity (`[REDACTED_ARN]`, `[REDACTED_AKIA]`,
  `[REDACTED_PATH]` instead of generic `[REDACTED]`).
- **`alerts/channels/slack.py`** drops local `_mask_webhook_url()`, imports
  `mask_webhook_url` from `_shared/redaction.py`. Behavior identical.
- **Sphinx Furo theme** : visual consistency tweaks on cards and admonitions.
  No content change.

### Fixed

- **Security: `auth/callback.py:116`** : OAuth authorization code (`?code=...`
  query parameter) was leaked in DEBUG via the `requestline` forwarded by
  `BaseHTTPRequestHandler.log_request`. Fix : `log_message` now logs only HTTP
  method + status, never the full requestline.
- **Security: `websocket/manager.py:449`** : WebSocket connect URL was logged
  in clear at INFO level. URLs with inline auth (`wss://user:pass@host`) or
  sensitive query parameters (`?token=xxx`) leaked credentials. Fix : URL is
  now redacted via `mask_url()` from `_shared/redaction.py` before logging.
- **Security: `pipeline/steps/_base.py:70-76`** : subprocess stderr was
  forwarded in WARNING on FAILED status. Stderr from arbitrary user shell
  commands (`psql`, `curl`, `ssh`, `mysql -p`) could contain credentials. Fix :
  stderr is dropped from log (kept in `StepResult.stderr` for user inspection).
  Documented in Sphinx user-responsibility.
- **Security: `pipeline/steps/shell.py:59,62`** + **`pipeline/steps/python.py:55,
  59`** : shell command line was logged in DEBUG (and INFO on dry-run),
  exposing `Authorization: Bearer xxx`, `--password=xxx`, `sshpass -p xxx`,
  inline credentials in URLs. Fix : new helper `_sanitize_command()` (regex-
  based, best-effort) redacts known sensitive patterns before logging. Users
  should still prefer `env:` mapping over command-line credentials when
  possible (documented in Sphinx).
- **`examples/db/02_encrypted_sqlite_demo.py`** : 4 sqlite3/sqlcipher3 connect
  call sites refactored to use `contextlib.closing` so the connection is
  released even when an intermediate `execute()` raises. Production impact is
  nil (this is an executable demo) but the file doubled as a copy-paste
  template that taught the wrong shape.
- **`tests/smoke/test_logging_noise_reduction.py`** : module docstring and
  assert message no longer reference internal audit documents and sprint
  labels; failure-mode hint is rewritten in self-contained terms (logger and
  level the user controls).
- **`tests/websocket/test_manager.py`** : drop unused `AsyncMock` stub causing
  `RuntimeWarning: coroutine was never awaited` under Python 3.14.

### Security

> **Important** : this release fixes 4 HIGH severity logging leaks identified
> by an internal audit covering 15 kstlib modules. Operators using
> `kstlib >= 2.0.0` with logging enabled at `DEBUG` or below in production are
> encouraged to upgrade to v2.5.0.

- **OAuth callback authorization code leak** (HIGH) : pre-v2.5.0,
  `auth/callback.py` forwarded the full HTTP requestline to `log.debug`,
  exposing the OAuth authorization code (10-minute window typically).
  Severity mitigated by PKCE in PKCE-enabled flows but still a policy
  violation. Fixed in v2.5.0.
- **WebSocket URL credentials leak** (HIGH) : pre-v2.5.0,
  `websocket/manager.py` logged the full URL in INFO including userinfo and
  query string. URLs like `wss://user:pass@host` or `wss://exchange.com/?token=...`
  exposed credentials. Fixed in v2.5.0.
- **Pipeline subprocess stderr leak** (HIGH) : pre-v2.5.0,
  `pipeline/steps/_base.py` forwarded full subprocess stderr in WARNING on
  FAILED. Stderr from user shell commands could contain credentials. Fixed
  in v2.5.0.
- **Pipeline shell command leak** (HIGH) : pre-v2.5.0, `pipeline/steps/shell.py`
  and `pipeline/steps/python.py` logged the full command line including
  Authorization headers, passwords, and inline credentials. Fixed in v2.5.0
  via `_sanitize_command()`.
- **Sanitization defenses inscribed as systematic conventions** in the
  Sphinx "Logging introspection guide" (12 model patterns) and "User
  responsibility" guide (6 cases). New module contributions must respect the
  pre-commit checklist documented there.

## [2.4.0] - 2026-04-26

### Added

- `MailBuilder.notify` accepts `mode="ok" | "ko" | "both"` (case-insensitive)
  and `on_success_only=True` for symmetric filtering, completing the
  pre-existing `on_error_only` shortcut.
- `MailBuilder.notify(collector=...)` captures every result that passes the
  active filter into a `NotifyCollector`, enabling run-summary emails. Capture
  follows the active mode, so the double-decorator pattern records exactly one
  entry per execution.
- `NotifyCollector`: thread-safe, FIFO-bounded collector of `NotifyResult`
  instances, with `render_html` / `render_plain` / `to_monitor_table` /
  `to_context` helpers.
- `MailBuilder.send_summary(collector, *, subject=None, format="html")`
  shortcut to send a summary email built from a collector. Operates on an
  internal snapshot so the original builder state is preserved.
- `kstlib._shared.jinja` module exposing `render_jinja(source, context, *,
  autoescape=False)` and `render_jinja_file(path, context, *,
  autoescape=False, encoding="utf-8")` helpers. Internal cross-module
  helpers; not part of the public top-level kstlib API. Used by
  `MailBuilder` for template rendering.
- Documentation table for `NotifyCollector.to_context()` keys with types,
  plus a "Custom Jinja2 templates with NotifyCollector" section showing a
  loop-over-results example.

### Changed

- `MailBuilder.message(template=...)` now renders templates with real
  Jinja2 (loops, conditions, filters, attribute access) instead of the
  previous regex-based `{{ var }}` substitution. Backward compatible for
  simple `{{ var }}` templates. Two small semantic changes worth noting:
  missing variables now render as empty strings (Jinja2
  `ChainableUndefined`) instead of preserving the `{{ var }}` literal,
  and non-scalar variables now render via Python `str()` instead of the
  `"[object]"` placeholder.

### Deprecated

### Removed

### Fixed

### Security

## [2.3.1] - 2026-04-25

### Fixed

- **Circular import when `from kstlib.mail import ...` (or any import
  path entering through `kstlib.limits`) is the first kstlib import in
  a fresh Python process.** Affected 2.3.0 users running scripts from
  command line or Jupyter kernels just after `Restart Kernel`. The
  cycle was triggered by `kstlib.config.loader` and `kstlib.config.sops`
  reading constants from `kstlib.limits` while the latter was still
  initialising (transitively reached through
  `kstlib.utils.formatting` -> `kstlib.utils.validators` ->
  `kstlib.config.exceptions`). Fix reorders `kstlib.limits` so all
  `HARD_*` and `DEFAULT_*` constants are defined before the cross-module
  import. **Workaround for users still on 2.3.0**: `import kstlib.config`
  before the first `from kstlib.mail import ...`. Upgrading to 2.3.1
  removes the need for the workaround.
- **`TypeError: 'NoneType' object is not iterable` on any kstlib command
  that loads the configuration when a user-provided YAML carried an
  empty `include:` key** (or `include: null`, or a list whose items had
  been commented out). `dict.pop("include", [])` returns `None` when the
  key is present with a `null` value, and the downstream
  `for inc in includes:` loop exploded. Fix routes the raw value
  through a new private helper `_normalize_includes` in
  `kstlib.config.loader` with four rules: empty/`None`/whitespace is
  silent `[]`, single string is wrapped after strip, list entries that
  are `None`/empty/whitespace are dropped with a single
  `WARNING kstlib.config.loader` log naming the source file, drop
  count, and original indices, and any other type (or non-string list
  item) raises `ConfigFormatError` consistent with the rest of the
  loader's validation.

### Tests

- **New `tests/test_no_circular_imports.py`**: 32 parametrised tests
  that import every public `kstlib.*` top-level module, a curated set
  of public symbols, and historical cycle-guard submodules
  (`kstlib.config.sops`) in isolated Python subprocesses. Subprocesses
  start with an empty `sys.modules`, which is the only condition under
  which import cycles surface (pytest's own init pre-loads enough of
  the package to mask them). Regression guard for the 2.3.0 cycle
  above.
- **New `tests/config/test_loader_include_normalization.py`**: 22 tests
  covering every branch of `_normalize_includes` (silent empty cases,
  string stripping, list filtering with `caplog` assertions on the
  warning message, and every illegitimate type path) plus two
  integration smoke tests that exercise `_load_with_includes` against
  tmp_path YAML files.

## [2.3.0] - 2026-04-24

### Added

- **`kstlib.config.reload_config()`**: ergonomic alias for "flush the
  singleton cache and reload from disk". Equivalent to
  `clear_config()` + `get_config()` but expresses the intent in a single
  call, designed for Jupyter / REPL sessions where the YAML files have
  been edited mid-session. Also re-exported at the top level as
  `kstlib.reload_config` for consistency with `get_config` /
  `clear_config`. Purely additive, no backward-compat break.
- **Mail preset SSL context with 4-level cascade.** SMTP presets now
  resolve their `ssl.SSLContext` through a cascade (preset >
  `mail.ssl.*` > root `ssl.*` > Python default). The two keys
  `ssl_verify` and `ssl_ca_bundle` cascade independently, so a preset
  can disable verification while a higher level provides a CA bundle.
  `ssl_ca_bundle` paths are validated via
  {func}`kstlib.ssl.validate_ca_bundle_path` (7-layer hardening:
  type/null-byte/empty/exists/file/readable/PEM). New
  `mail.ssl: {verify, ca_bundle}` defaults shipped in the packaged
  `kstlib.conf.yml`. Unlocks enterprise/internal PKI usage that was
  previously impossible through presets (users had to bypass
  `MailBuilder` and expose secrets).
- **Mail preset envelope defaults** (`sender`, `reply_to`). A preset may
  now declare a `defaults:` subsection under
  `mail.presets.<name>.defaults`. Both fields are applied automatically
  when the builder is created via `MailBuilder(preset="...")` or when
  `mail.default` resolves to a preset with defaults. User-provided
  values via `.sender()` / `.reply_to()` always override. Explicit
  `MailBuilder(transport=...)` short-circuits the logic entirely.
  **Scope is intentionally narrow**: `to`/`cc`/`bcc` are refused by
  design to prevent silent accidental sends. Unknown keys under
  `defaults` are logged once as WARNING and ignored (forward-compat).

### Security

- **WARNING log on `ssl_verify=false` for mail transports.** Every SMTP
  preset built with a resolved `ssl_verify=False` (at any cascade level)
  now emits a single WARNING naming the source level (`preset`,
  `mail.ssl`, `ssl (root)` or `default`). Helps operators detect
  accidental verification disablement. Precedence: when both a CA bundle
  and `ssl_verify=false` are present, the CA bundle wins and
  verification stays enabled (`CERT_REQUIRED`) - documented.

## [2.2.1] - 2026-04-17

### Fixed

- **WebSocket reconnect counter** resets only after `stable_connection_time`
  (default 60s) of uninterrupted connection, not on every successful handshake.
  Exponential backoff now accumulates correctly during prolonged server outages.
- **WebSocket code 1013** ("Try Again Later") is now detected explicitly and
  forces a `server_unavailable_delay` (default 30s) before any reconnect,
  instead of being treated as a generic server close.
- **WebSocket disconnect alert throttle**: new `on_disconnect_alert` callback
  with built-in `disconnect_alert_interval` (default 300s) and aggregated
  disconnect count. Prevents alert storms during server outages (e.g. 3918
  Slack alerts in 19 minutes during a Kraken trading engine outage).
- **deps: authlib>=1.6.11**
  ([GHSA-jj8c-mmj3-mmgv](https://github.com/advisories/GHSA-jj8c-mmj3-mmgv)) -
  JWT algorithm confusion vulnerability.

## [2.2.0] - 2026-04-16

### Added

- **System-wide config cascade via platformdirs.** New fallback level between
  package defaults and user home config: `XDG_CONFIG_DIRS` on Linux, native
  paths on macOS/Windows.
- **LogManager `register=True`.** Unified bootstrap API; replaces the previous
  dual-object pattern. `init_logging()` is kept as a backward-compatible
  wrapper.
- **MailBuilder config-driven presets.** `mail.presets` in `kstlib.conf.yml`;
  cascade is `transport=` kwarg > `preset=` kwarg > `mail.default`.
- **Auto-activation of kstlib internal logs** via `kstlib.logging.enabled` in
  `kstlib.conf.yml` (silent cascade, never breaks the host app).

### Fixed

- **Exception hierarchy consolidated.** All subpackage base exceptions now
  inherit from `KstlibError`: `mail`, `metrics`, `rapi`, `resilience`, `ui`,
  `secure`, `utils`. `except KstlibError` now catches everything kstlib
  raises.
- **pytest 9.0.3 bump** (was capped at `<9`; pulls in the
  [CVE-2025-71176](https://nvd.nist.gov/vuln/detail/CVE-2025-71176) temp dir
  fix).
- **`defusedxml` applied to all XML parsing paths** (`transform.primitives`,
  `transform.chain`, `utils.serialization`).
- **`auth/providers` asserts removed.** `assert` statements replaced by
  explicit `ConfigurationError` raises so missing `token_url` / `issuer` /
  JWKS still raise cleanly under `python -O`.
- **Pipeline `CallableStep` hardened.** `DANGEROUS_MODULES` blacklist +
  optional `allowed_modules` whitelist wired through
  `PipelineConfig.allowed_callable_modules`; blocks `os`, `subprocess`,
  `ctypes`, `pickle`, ... from being invoked via YAML config.
- **age-keygen private key** now has an explicit `chmod 0o600` after
  generation (umask fallback was `0o644` on Unix).
- **HTTP trace logger** redacts `access_token`, `refresh_token`, `id_token`,
  and `client_secret` in TRACE-level response bodies (matching the existing
  request redaction).

### Refactored

- **`pipeline/steps`**: shared `_run_subprocess` extracted into
  `pipeline/steps/_base.py`; `shell.py` and `python.py` now delegate instead
  of duplicating the execution skeleton.
- **`utils/validators`**: `CALLABLE_TARGET_PATTERN` +
  `MAX_CALLABLE_TARGET_LENGTH` consolidated; pipeline and transform
  validators share `_validate_callable_target_str`.
- **`alerts/manager`**: `_create_email_transport` split into
  `_create_smtp_transport`, `_create_resend_transport`,
  `_create_ses_transport`; dispatcher dropped to ~10 lines.
- **`cli/commands/ops/common`**: `get_session_manager` decomposed into
  `_detect_backend`, `_scan_tmux_sockets`, `_build_session_manager`
  (complexity 15 -> 8, blanket `C901`/`PLR0912` suppressions removed).
- **`cli/commands/rapi`**: `_load_config_or_exit()` shared by `list`,
  `show`, and `call`.
- **`LOGGING_LEVEL`** re-exported from `kstlib.logging`.
- **`ParamSpec`** migrated from `typing_extensions` to `typing`
  (`resilience/rate_limiter`, `resilience/circuit_breaker`; Python 3.10+).

### Security

- Response-body token redaction in HTTP trace logger (audit-security F1).
- `0o600` enforced on age private key (audit-security F2).
- `defusedxml` everywhere (audit-security F4).
- `auth/providers` asserts replaced by `ConfigurationError` (audit-security
  F5, safe under `python -O`).
- `CallableStep` blacklist + whitelist (audit-security F6).

## [2.1.4] - 2026-04-01

### Fixed

- **Batch audit fixes: pre-compile regex, extract helpers, fix resource leaks**
  - Pre-compile regex patterns at module level (logging, monitoring, delivery,
    ops/validators, sops) to avoid re-compilation on hot paths
  - Extract helpers to reduce duplication: `_normalize_scopes`/`_normalize_redirect_uri`
    (auth/config), `_validate_token_options` (cli/token), `_upgrade_to_tls`/`_authenticate`/
    `_trace_envelope` (smtp), `_check_response_size`/`_handle_retry_error` (rapi/client)
  - Add `OAuth2Provider.close()` and `__exit__` to release HTTP connection pool
  - Add JWKS TTL cache (3600s) in OIDC provider for key rotation
  - Add `py.typed` marker to package-data (PEP 561)

## [2.1.3] - 2026-04-01

### Fixed

- **deps: bump Pygments >= 2.20.0**
  ([CVE-2026-4539](https://nvd.nist.gov/vuln/detail/CVE-2026-4539)) -
  Regular Expression Denial of Service (ReDoS) due to inefficient regex for
  GUID matching. Transitive dependency via Sphinx. Lower bound enforced in
  dev, docs, and all extras.

## [2.1.2] - 2026-03-29

### Fixed

- **deps: enforce transitive dep lower bounds for CVE remediation** -
  Previous CVE fixes only bumped lockfiles (uv.lock, pylock.toml) but did not
  set minimum versions in pyproject.toml. Users installing via `pip install kstlib`
  could resolve vulnerable transitive dependencies. Now pyproject.toml enforces
  patched versions for all security-critical transitive deps.

  **Runtime dependencies added:**
  - `cryptography>=46.0.6`
    ([CVE-2026-26007](https://nvd.nist.gov/vuln/detail/CVE-2026-26007),
    [CVE-2026-34073](https://nvd.nist.gov/vuln/detail/CVE-2026-34073)) -
    SECT curve subgroup validation + DNS name constraint enforcement (via authlib)
  - `requests>=2.33.0`
    ([CVE-2024-47081](https://nvd.nist.gov/vuln/detail/CVE-2024-47081),
    [CVE-2026-25645](https://nvd.nist.gov/vuln/detail/CVE-2026-25645)) -
    cookie handling + temp path replacement (via httpx)
  - `urllib3>=2.6.3`
    ([CVE-2025-50182](https://nvd.nist.gov/vuln/detail/CVE-2025-50182),
    [CVE-2025-50181](https://nvd.nist.gov/vuln/detail/CVE-2025-50181),
    [CVE-2025-66418](https://nvd.nist.gov/vuln/detail/CVE-2025-66418),
    [CVE-2025-66471](https://nvd.nist.gov/vuln/detail/CVE-2025-66471),
    [CVE-2026-21441](https://nvd.nist.gov/vuln/detail/CVE-2026-21441)) -
    5 vulnerabilities in HTTP client (via requests)

  **Dev dependencies added:**
  - `filelock>=3.20.3`
    ([CVE-2026-22701](https://nvd.nist.gov/vuln/detail/CVE-2026-22701)) - via tox/virtualenv
  - `jaraco-context>=6.1.0`
    ([CVE-2026-23949](https://nvd.nist.gov/vuln/detail/CVE-2026-23949)) - via keyring
  - `virtualenv>=20.36.1`
    ([CVE-2026-22702](https://nvd.nist.gov/vuln/detail/CVE-2026-22702)) - via tox
  - `wheel>=0.46.2`
    ([CVE-2026-24049](https://nvd.nist.gov/vuln/detail/CVE-2026-24049)) - build-system

## [2.1.1] - 2026-03-26

### Fixed

- **deps: bump requests 2.32.5 -> 2.33.0**
  ([CVE-2026-25645](https://nvd.nist.gov/vuln/detail/CVE-2026-25645)) -
  `requests.utils.extract_zipped_paths` vulnerable to malicious file replacement
  via deterministic temp paths. Indirect dependency only (via sphinx,
  requests-toolbelt), no direct impact on kstlib.

## [2.1.0] - 2026-03-25

### Added

- **RAPI: multipart/form-data upload** - Endpoints with `Content-Type: multipart/form-data`
  in their headers now auto-handle file uploads via httpx native `files=` parameter.
  MIME type auto-detected from extension, boundary auto-generated.
  - `MultipartConfig` dataclass for fine-tuning (field_name, content_type)
  - `FilePayload` dataclass for programmatic uploads without files on disk
  - `EndpointConfig.is_multipart` property, optional `multipart:` YAML section
  - TRACE-level logging: boundary, parts, field names, sizes (`-vvv`)
  - `HARD_MAX_RAPI_UPLOAD_SIZE` (100 MiB) deep defense limit

- **RAPI CLI: `--raw` flag** - Output raw JSON without Rich formatting, pipeable to `jq`

- **RAPI CLI: `--minify` flag** - Output compact single-line JSON, combinable with `--out`

### Improved

- **RAPI: endpoint collision warnings** - Now show collision count, first source file,
  and actionable tips instead of just the endpoint name

### Documentation

- Multipart upload section with YAML config and Python examples
- `--raw` and `--minify` in CLI options tables
- `FilePayload` and `MultipartConfig` in API reference autodoc

## [2.0.1] - 2026-03-17

### Fixed

- **RAPI: null query params no longer sent as empty strings** - YAML query parameters
  with `null` value (e.g. `filter: null`) were converted to empty strings by httpx,
  causing server-side errors (SAS Viya error 1104: `The filter '' is not valid`).
  Null params are now excluded from the HTTP request. Kwargs can still override them
  at call time (e.g. `filter="name eq 'foo'"`), and passing `None` as a kwarg
  explicitly removes a default param.
  - `_extract_query_params()` filters out `None` values from endpoint config
  - `EndpointConfig.query` type hint corrected to `dict[str, str | None]`

## [2.0.0] - 2026-03-07

### Breaking Changes

> **Major version bump** due to security hardening that changes runtime behavior.
> Rollback: `pip install "kstlib<2.0.0"`

- **`validate_command()` strict blocklist** - Now blocks `;`, `&&`, `||`, `|`, `>`, `<`,
  `eval`, `source`, `exec`, null bytes in ops commands (container run/exec).
  Pipeline steps use `strict=False` and are not affected.
- **`validate_env()` dangerous keys denylist** - Blocks `LD_PRELOAD`, `PYTHONPATH`,
  `NODE_OPTIONS` and similar environment variables in ops functions.
- **`send_keys()` input validation** - Blocks pipes, semicolons, redirections in tmux
  send_keys. Tmux control sequences (C-c, Enter, Escape) remain allowed.
- **OIDC ID token validation mandatory** - `exchange_code()` now raises
  `TokenValidationError` on validation failure instead of logging a warning.
- **authlib required for OIDC** - Missing `authlib` raises `TokenValidationError`
  instead of falling back to unverified JWT decode.
- **Config `include` path traversal blocked** - Include paths escaping the config
  directory raise `ConfigFormatError`. Symlinks in includes are also rejected
  to prevent TOCTOU bypass of the path confinement check.
- **SOPS binary must be a simple name** - Paths in `sops_binary` raise `ConfigSopsError`.
- **RAPI URL scheme validation** - Only `http://` and `https://` accepted.
- **JSON heuristic removed** - Response body parsed as JSON only when content-type
  confirms it (`application/json` or `application/vnd.*+json`).
- **`shlex.split()` for container commands** - Replaces `str.split()` for proper
  quoting support.
- **Redirect URI validation** - `AuthProviderConfig` validates scheme (http/https)
  and warns on non-localhost hosts.
- **TmuxRunner socket_name validation** - Rejects paths and null bytes in socket names.

### Security

- **47 security items hardened** across 9 phases (8 CRITICAL, 17 HIGH, 15 MEDIUM, 7 LOW)
- Timing-safe CSRF state comparison (`hmac.compare_digest`)
- Thread-safe token refresh with double-checked locking
- Config file size limit (10 MiB) before YAML/JSON parse
- Bounded recursion depth (max 32) for `deep_merge` and SOPS scan
- NaN/Inf rejection in config values
- Path traversal and null byte checks in RAPI parameters
- SOPS decrypted secrets cache TTL (5 minutes)
- WAL checkpoint forced on DB pool close
- Log injection sanitization (CRLF/ANSI/null stripped)
- SMTP AUTH/PASS redacted in debug trace
- Token/SecretRecord/SMTPCredentials `repr=False`
- Explicit `follow_redirects=False` in httpx clients
- CallbackHandler state cleared on stop
- `.gitignore` patterns for secrets (`*.env`, `*.key`, `*.pem`, `credentials.*`)

## [1.7.8] - 2026-03-06

### Fixed

- **Oops: `ops attach`/`stop` now auto-discover custom tmux sockets** - v1.7.7 added
  custom socket discovery for `ops list`, but we didn't follow through: `attach` and `stop`
  still only checked the default socket, so `kstlib ops attach orion` failed with
  "Session not found" even though `ops list` showed it just fine. Now `get_session_manager()`
  scans custom sockets automatically when no `--socket` flag is provided, so `list`, `attach`,
  and `stop` all share the same discovery logic.
  - Move `discover_tmux_sockets()` from CLI layer to `kstlib.ops.tmux` (reusable)
  - `get_session_manager()` scans custom sockets when `socket_name` is None
  - Validated on EC2: `kstlib ops attach orion` works without `--socket`

## [1.7.7] - 2026-03-06

### Fixed

- **tmux custom socket discovery** - `TmuxRunner` now supports sessions started with
  `tmux -L <name>` (custom sockets). Previously, `kstlib ops list` only discovered sessions
  on the default socket, making multi-bot setups (e.g. Orion on `-L orion`) invisible.
  - `TmuxRunner(socket_name=...)` injects `-L` flag in all tmux commands including `attach`
  - `SessionStatus.socket_name` tracks the origin socket for each session
  - `_discover_tmux_sockets()` auto-scans `/tmp/tmux-{uid}/` for non-default sockets
  - `kstlib ops list` shows a new **Socket** column and `socket_name` in JSON output
  - New `--socket / -L` CLI option on `start`, `stop`, `attach`, `logs`, `status`
  - `SessionManager` and `auto_detect_backend` propagate socket context end-to-end

## [1.7.6] - 2026-03-06

### Security

- **Harden `ContainerRunner.exec()`** - Add `validate_command()` input validation before execution,
  consistent with `SessionConfig.__post_init__` validation
- **Harden `TmuxRunner.send_keys()`** - Add `validate_session_name()` input validation before
  passing session name to tmux subprocess
- **Pre-commit SOPS guard** - Add `check_sops_files()` to pre-commit hook to block commits
  containing decrypted SOPS files (missing `sops:` metadata block)

## [1.7.5] - 2026-03-05

### Security

- **Pin authlib>=1.6.9** - Tighten minimum version to exclude versions vulnerable to
  `alg: none` signature verification bypass (CVE-2026-28802)
- **Pin jinja2>=3.1.5** - Tighten minimum version to exclude versions vulnerable to
  sandbox bypass leading to RCE (CVE-2024-56326, CVE-2024-56201)
- **Upgrade werkzeug 3.1.5 to 3.1.6** - Fix `safe_join()` path traversal on Windows
  (dependabot #7, transitive dependency via moto)

### Changed

- Sync `uv.lock` and `pylock.toml` with updated dependency constraints

## [1.7.4] - 2026-03-04

### Security

- **Upgrade authlib 1.6.6 to 1.6.9** - Fix `alg: none` signature verification bypass
  ([GHSA-7wc2-qxgw-g8gg](https://github.com/advisories/GHSA-7wc2-qxgw-g8gg))

## [1.7.3] - 2026-02-27

### Changed

- **Full quality sweep** - Comprehensive code quality audit and fixes across 35 files
  - Add `__all__` exports to 5 modules (cache/decorator, cache/strategies, logging/manager,
    utils/dict, config/export)
  - Expose `ops` module via lazy loading in root `__init__.py`
  - Fix all D401 (imperative mood) docstring violations in 12 src/ files
  - Add ~137 missing test function docstrings (D103) across 9 test files
  - Simplify `MANIFEST.in` (use `prune .*` instead of individual exclusions)
  - Add `coverage.json` to `.gitignore`

### Fixed

- **3 mypy --strict errors** - Remove stale `type: ignore` comments for authlib, fix duplicate
  `__all__` in config/export, fix unreachable code in test_auth_cli
- **`test_rejects_code_exceeding_max_length`** - Use `_MAX_CODE_LENGTH + 1` instead of
  hardcoded value that became too small after limit was raised to 2048
- **CLI test coverage** - token.py (28% to 100%), attach.py (35% to 100%),
  login.py (47% to 99%)

## [1.7.2] - 2026-02-27

### Fixed

- **`secrets doctor` false ERROR on missing keyring** - The doctor command reported ERROR
  (exit code 1) when the optional `keyring` package was not installed, even though the
  encryption backend (age) was fully operational. Keyring is optional (used for credential
  caching, not encryption), so its absence now produces a WARNING instead.

## [1.7.1] - 2026-02-25

### Fixed

- **WebSocket `ConnectionClosedOK` silent data loss** - When Binance (or any server) closes
  the WebSocket cleanly (code 1000, e.g. after 24h), `_receive_loop` now triggers
  `_handle_disconnect(SERVER_CLOSED)` instead of only logging a debug message. This restores
  auto-reconnect behavior on clean server closures, preventing silent data loss.
- **Deprecated `websockets` API** - Replace `e.code`/`e.reason` with `e.rcvd.code`/`e.rcvd.reason`
  (deprecated since websockets 13.1) in both `ConnectionClosedOK` and `ConnectionClosedError`
  handlers.

## [1.7.0] - 2026-02-22

### Added

- **`AlertLevel.SUCCESS`** - New alert severity level for positive confirmations
  - Value 11 (between INFO=10 and WARNING=20), filtered like INFO by `min_level`
  - Slack emoji `:white_check_mark:` (green checkmark), color `#36a64f` (green)
  - `_parse_level("success")` supported for config-driven channel setup
  - Consumer: astro trading bot for `ws_reconnect`, `heartbeat_ok`, `order_filled`

### Fixed

- **Prod preset now defaults `tracebacks_show_locals` to `False`** - Reduces default exposure
  surface in production tracebacks. Local variables are still available by switching to the
  `debug` preset or setting `tracebacks_show_locals: True` in config. The fallback default
  also changed from `True` to `False` so unlisted presets inherit the safer behavior.

## [1.6.2] - 2026-02-18

### Fixed

- **`get_logger()` missing `.trace()` and `.success()` methods** - Child loggers returned by
  `get_logger(__name__)` are standard `logging.Logger` instances that lack custom level methods.
  Calling `logger.trace(...)` raised `AttributeError`. Now `init_logging()` patches the
  `logging.Logger` class once at startup so all child loggers support `.trace()` and `.success()`.

## [1.6.1] - 2026-02-16

### Fixed

- **`kstlib auth check` SSL context** - HTTP client now reuses the provider's SSL config
  (`ca_bundle`, `ssl_verify`) instead of creating a bare `httpx.Client()`. Falls back to the
  global SSL cascade from `kstlib.conf.yml` when no provider config is available.

### Added

- **Shell examples** - `kstlib-auth-check.sh` (wrapper script) and `token_check.sh` (raw
  curl/openssl verification) for auth check usage without Python
- **CLI tests** - New test suite for `kstlib auth check` CLI command (80 lines, covers
  SSL context propagation)

### Documentation

- Updated examples gallery with shell script references

## [1.6.0] - 2026-02-14

### Added

- **`kstlib auth check`** - JWT token validation with cryptographic proof
  - `TokenChecker` class with 6-step validation chain: decode JWT structure, discover
    issuer endpoints, fetch JWKS, extract public key, verify RSA signature, validate claims
  - Works with any RSA-signed JWT (RS256/RS384/RS512) whose issuer exposes an OIDC
    discovery endpoint (`.well-known/openid-configuration`)
  - Key metadata extraction: type (RSA), size (2048/4096-bit), SHA-256 fingerprint
  - X.509 certificate parsing from JWKS `x5c` field when published by the IDP
  - CLI command with `--verbose`, `--json`, `--access-token` options
  - Rich panel output with step-by-step validation results
  - Exit codes: 0 (valid), 1 (invalid), 2 (system error)
  - Delegated trust support: issuer and JWKS server can be different hosts

### Documentation

- Cryptographic proof chain diagram with RSA verification steps
- Manual verification guide (without kstlib, using curl/openssl/PowerShell)
- Issuer vs JWKS server (delegated trust) explanation
- Examples gallery: `token_check.py` (Python) and `token_check.ps1` (PowerShell raw RSA)
- Updated auth feature guide, API reference, CLI reference

## [1.5.0] - 2026-02-11

### Added

- **`kstlib.pipeline`** - Declarative, config-driven pipeline execution module
  - Three step types: `ShellStep` (subprocess, shell=True), `PythonStep` (python -m),
    `CallableStep` (importlib import + call)
  - Conditional execution: `always`, `on_success`, `on_failure` step conditions
  - Error policies: `fail_fast` (aborts with on_failure cleanup) or `continue`
  - Timeout cascade: step timeout overrides pipeline `default_timeout`
  - Dry-run mode: simulate execution without side effects
  - Config-driven pipelines: define workflows in `kstlib.conf.yml` under `pipeline.pipelines`
  - `PipelineRunner.from_config(name)` to load and run named pipelines
  - Deep input validation reusing `kstlib.ops.validators` (dangerous pattern detection)
  - `PipelineLimits` in `limits.py` with hard caps (max 50 steps, 1-3600s timeout)
  - Multi-line shell commands supported via YAML `>-` (folded) and `|` (literal) scalars

### Fixed

- **SQLite `isolation_level`** - Align plain SQLite path with cipher path (`isolation_level=None`
  for autocommit consistency)

### Documentation

- Pipeline feature guide, API reference, exception catalog
- 3 example scripts + example `kstlib.conf.yml`
- Updated landing page, features/api/examples indexes

## [1.4.1] - 2026-02-11

### Security

- Upgrade `cryptography` 46.0.4 -> 46.0.5 (CVE-2026-26007, subgroup attack on SECT curves)

## [1.4.0] - 2026-02-10

### Added

- **Multi-backend `secrets init`** - Auto-detect best available encryption backend
  - Priority order: age > GPG > error with clear guidance
  - `--backend`/`-b` option for explicit backend selection (`age` or `gpg`)
  - GPG flow: reads fingerprint from keyring, generates `.sops.yaml` with `pgp:` key
  - Age flow: unchanged (backward compatible)

- **Doctor backend mismatch hint** - Actionable guidance when configured backend
  is unavailable but an alternative exists on the system
  (e.g., "Configured backend (age) is not available, but gpg is. Run: `kstlib secrets init --backend gpg`")

### Fixed

- **`secrets doctor` scan** - Detect available backends (age/gpg/kms) by binary presence
  - Deep checks for configured backends, lightweight checks for unconfigured
  - New `available_backends` field in doctor payload

## [1.3.0] - 2026-02-08

### Added

- **SQLite performance PRAGMAs** for self-maintaining databases
  - `PRAGMA auto_vacuum=INCREMENTAL` on new file databases (set before WAL to ensure
    it takes effect; skipped on existing databases and `:memory:`)
  - `PRAGMA optimize` executed on each connection at pool close (updates internal
    statistics for better query planner decisions)

## [1.2.1] - 2026-02-07

### Fixed

- **Binance testnet WebSocket URL** - Update deprecated `wss://testnet.binance.vision/ws`
  to `wss://stream.testnet.binance.vision/ws` (officially changed by Binance in May 2024,
  old endpoint kept working beyond scheduled removal but is now unreliable)

### Documentation

- README and Sphinx index: add AWS SES to mail transports list (from v1.2.0)

## [1.2.0] - 2026-02-06

### Added

- **SesTransport** - AWS SES email delivery via `send_raw_email`
  - Async transport using `run_in_executor` for boto3 compatibility
  - Raw MIME passthrough (preserves HTML, attachments, all headers)
  - Default credential chain support (EC2 instance profiles, env vars)
  - Explicit credentials option (`aws_access_key_id` / `aws_secret_access_key`)
  - Deep validation: region, credential pairs, timeout
  - TRACE-level logging for request metadata
  - Error mapping: `ClientError`, `NoCredentialsError`, `EndpointConnectionError`

- **`[ses]` extras** - `pip install kstlib[ses]` installs boto3

- **Alert manager integration** - `type: "ses"` in transport factory

### Fixed

- **Sphinx docs** - `'re_'` in ResendTransport docstring caused reST warning

### Documentation

- Sphinx features/mail: AWS SES Transport section with install + examples
- Sphinx api/mail: autodoc for SesTransport, ResendTransport, GmailTransport
- Installation guide: `[ses]` extra in bundles list

## [1.1.1] - 2026-02-04

### Fixed

- **SOPS cascading search** - Fix `.sops.yaml` discovery from source file directory
  - Previously only checked `~/.sops.yaml`, ignoring local configs
  - Now walks up directory tree from source file, then falls back to home

## [1.1.0] - 2026-02-01

### Added

- **RAPI Safeguards** - Protection for dangerous endpoints
  - SafeguardConfig: configure which HTTP methods require confirmation
  - Runtime confirmation via `confirm=` parameter
  - Config-time validation for DELETE/PUT endpoints

- **RAPI Environment Variables** - Dynamic configuration
  - `${VAR}` syntax for required env vars
  - `${VAR:-default}` syntax with fallback values
  - Recursive expansion in all string values

- **RAPI Nested Includes** - Modular API definitions
  - Include sub-modules from root `.rapi.yml` files
  - Defaults inheritance (base_url, credentials, headers)
  - Endpoint collision detection with strict mode

- **RAPI CLI Improvements**
  - `--filter` option for endpoint search
  - `--short-desc` flag for truncated descriptions
  - Verbose mode shows full descriptions by default

- **SAS Viya POC** - Example with ~1250 endpoints
  - Validates nested includes architecture at scale
  - Body schemas approximate (not validated)

## [1.0.2] - 2026-01-31

### Changed

- Upgrade dev dependencies (security fixes)

## [1.0.1] - 2026-01-31

### Fixed

- Use absolute URL for logo in README

## [1.0.0] - 2026-01-30

First public release of kstlib, a config-driven Python toolkit for building
resilient applications.

### Core Modules

#### Configuration (`kstlib.config`)
- Cascading YAML/JSON configuration with file includes
- SOPS-encrypted secrets integration (Age, GPG, AWS KMS)
- Environment variable interpolation
- Box-based dot notation access
- Auto-discovery with customizable search paths

#### Secrets Management (`kstlib.secrets`)
- Multi-provider secret resolution (env, keyring, SOPS, AWS KMS)
- Kwargs provider for runtime injection
- Sensitive value redaction in logs
- Provider priority chain with fallbacks

#### Logging (`kstlib.logging`)
- Rich console output with colors and formatting
- Rotating file handlers with compression
- TRACE level for verbose debugging
- Structlog integration for structured logging
- Context-aware logging with correlation IDs

#### Authentication (`kstlib.auth`)
- OAuth2/OIDC with PKCE support
- Automatic token refresh
- Secure token storage (keyring integration)
- Callback server for authorization flows
- Provider abstraction (Keycloak, generic OIDC)

#### Mail (`kstlib.mail`)
- Fluent MailBuilder API
- Jinja2 template rendering
- Multiple transports: SMTP, Gmail API, Resend
- Attachment handling with filesystem guardrails
- Async transport support

#### Alerts (`kstlib.alerts`)
- Multi-channel delivery (Slack, Email)
- Severity levels with routing rules
- Throttling to prevent alert fatigue
- Template-based message formatting

#### WebSocket (`kstlib.websocket`)
- Resilient connection management
- Automatic reconnection with backoff
- Heartbeat and ping/pong handling
- Watchdog for connection health
- Message deduplication

#### REST API Client (`kstlib.rapi`)
- Config-driven endpoint definitions
- HMAC request signing
- Automatic retry with backoff
- Response validation
- Rate limiting integration

#### Monitoring (`kstlib.monitoring`)
- Metric collectors with Jinja rendering
- Multiple delivery targets (file, mail)
- Scheduled collection runs
- Custom collector plugins

#### Resilience (`kstlib.resilience`)
- Circuit breaker pattern
- Token bucket rate limiter
- Graceful shutdown handling
- Heartbeat monitoring
- Watchdog timers

#### Operations (`kstlib.ops`)
- Session manager (tmux integration)
- Container operations (Docker/Podman)
- Process management utilities

#### Cache (`kstlib.cache`)
- TTL-based caching
- LRU eviction strategy
- File-based persistent cache
- Decorator API for easy integration

#### Database (`kstlib.db`)
- Connection pooling
- Field-level encryption (cipher)
- Migration support

#### UI Components (`kstlib.ui`)
- Rich panels and tables
- Progress spinners
- Formatted output helpers

#### Utilities (`kstlib.utils`, `kstlib.helpers`)
- TimeTrigger for scheduled operations
- Input validators
- Text formatting utilities
- Secure file deletion
- HTTP request tracing

### CLI

- Command-line interface for common operations (`kstlib --help`)

### Documentation

- Comprehensive Sphinx documentation with Furo theme
- API reference with autodoc
- Examples gallery with runnable code
- Development guides (testing, contributing, secrets management)

### Quality

- 95%+ test coverage per module
- 16,000+ tests across 5 Python versions (3.10-3.14)
- Strict mypy type checking
- Ruff linting and formatting
- Pre-commit hooks with tox validation
- CI/CD with GitHub Actions

### Security

- Supply chain verification with PEP 751 lockfile (pylock.toml)
- SHA256 hash verification for all dependencies
- SOPS integration for secrets at rest
- Sensitive value redaction in logs and errors
- Filesystem guardrails for attachments

[Unreleased]: https://github.com/KaminoU/kstlib/compare/v3.8.0...HEAD
[3.8.0]: https://github.com/KaminoU/kstlib/compare/v3.7.1...v3.8.0
[3.7.1]: https://github.com/KaminoU/kstlib/compare/v3.7.0...v3.7.1
[3.7.0]: https://github.com/KaminoU/kstlib/compare/v3.6.2...v3.7.0
[3.6.2]: https://github.com/KaminoU/kstlib/compare/v3.6.1...v3.6.2
[3.6.1]: https://github.com/KaminoU/kstlib/compare/v3.6.0...v3.6.1
[3.6.0]: https://github.com/KaminoU/kstlib/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/KaminoU/kstlib/compare/v3.4.2...v3.5.0
[3.4.2]: https://github.com/KaminoU/kstlib/compare/v3.4.1...v3.4.2
[3.4.1]: https://github.com/KaminoU/kstlib/compare/v3.4.0...v3.4.1
[3.4.0]: https://github.com/KaminoU/kstlib/compare/v3.3.1...v3.4.0
[3.3.1]: https://github.com/KaminoU/kstlib/compare/v3.3.0...v3.3.1
[3.3.0]: https://github.com/KaminoU/kstlib/compare/v3.2.0...v3.3.0
[3.2.0]: https://github.com/KaminoU/kstlib/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/KaminoU/kstlib/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/KaminoU/kstlib/compare/v2.7.1...v3.0.0
[2.7.1]: https://github.com/KaminoU/kstlib/compare/v2.7.0...v2.7.1
[2.7.0]: https://github.com/KaminoU/kstlib/compare/v2.6.0...v2.7.0
[2.6.0]: https://github.com/KaminoU/kstlib/compare/v2.5.0...v2.6.0
[2.5.0]: https://github.com/KaminoU/kstlib/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/KaminoU/kstlib/compare/v2.3.1...v2.4.0
[2.3.1]: https://github.com/KaminoU/kstlib/compare/v2.3.0...v2.3.1
[2.3.0]: https://github.com/KaminoU/kstlib/compare/v2.2.1...v2.3.0
[2.2.1]: https://github.com/KaminoU/kstlib/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/KaminoU/kstlib/compare/v2.1.4...v2.2.0
[2.1.4]: https://github.com/KaminoU/kstlib/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/KaminoU/kstlib/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/KaminoU/kstlib/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/KaminoU/kstlib/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/KaminoU/kstlib/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/KaminoU/kstlib/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/KaminoU/kstlib/compare/v1.7.8...v2.0.0
[1.7.8]: https://github.com/KaminoU/kstlib/compare/v1.7.7...v1.7.8
[1.7.7]: https://github.com/KaminoU/kstlib/compare/v1.7.6...v1.7.7
[1.7.6]: https://github.com/KaminoU/kstlib/compare/v1.7.5...v1.7.6
[1.7.5]: https://github.com/KaminoU/kstlib/compare/v1.7.4...v1.7.5
[1.7.4]: https://github.com/KaminoU/kstlib/compare/v1.7.3...v1.7.4
[1.7.3]: https://github.com/KaminoU/kstlib/compare/v1.7.2...v1.7.3
[1.7.2]: https://github.com/KaminoU/kstlib/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/KaminoU/kstlib/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/KaminoU/kstlib/compare/v1.6.2...v1.7.0
[1.6.2]: https://github.com/KaminoU/kstlib/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/KaminoU/kstlib/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/KaminoU/kstlib/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/KaminoU/kstlib/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/KaminoU/kstlib/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/KaminoU/kstlib/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/KaminoU/kstlib/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/KaminoU/kstlib/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/KaminoU/kstlib/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/KaminoU/kstlib/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/KaminoU/kstlib/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/KaminoU/kstlib/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/KaminoU/kstlib/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/KaminoU/kstlib/releases/tag/v1.0.0
