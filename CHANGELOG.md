# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
