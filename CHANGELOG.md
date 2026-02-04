# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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

[1.1.1]: https://github.com/KaminoU/kstlib/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/KaminoU/kstlib/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/KaminoU/kstlib/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/KaminoU/kstlib/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/KaminoU/kstlib/releases/tag/v1.0.0
