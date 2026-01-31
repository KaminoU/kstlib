<p align="center">
  <img src="https://raw.githubusercontent.com/KaminoU/kstlib/main/assets/kstlib.svg" alt="Kstlib Logo" width="420">
</p>

<p align="center">
  <strong>Config-driven Python toolkit for resilient applications</strong>
</p>

<p align="center">
  <a href="https://github.com/KaminoU/kstlib/actions/workflows/ci.yml"><img src="https://github.com/KaminoU/kstlib/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://kstlib.readthedocs.io/"><img src="https://img.shields.io/badge/docs-RTD-blue" alt="Documentation"></a>
  <a href="https://pypi.org/project/kstlib/"><img src="https://img.shields.io/pypi/v/kstlib?color=blue" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-≥3.10-blue" alt="Python">
  <a href="https://github.com/KaminoU/kstlib/blob/main/LICENSE.md"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
</p>

---

**kstlib** is a personal Python toolkit built over 7 years of learning and experimentation.

It started as a way to explore Python best practices, evolved into utilities for personal automation,
and now serves as the foundation for study projects in algorithmic trading and market analysis.

The focus has always been on building **resilient, secure, and performant** systems.

> **Note**: Everything works via Python, but since kstlib is heavily config-driven,
> the [Examples Gallery](https://kstlib.readthedocs.io/en/latest/examples.html) showcases
> a YAML-first approach.

## Core Modules

| Module | Purpose |
|--------|---------|
| **config** | Cascading config files, includes, SOPS encryption, Box access |
| **secrets** | Multi-provider resolver (env, keyring, SOPS, KMS) with guardrails |
| **logging** | Rich console, rotating files, TRACE level, structlog integration |
| **auth** | OIDC/OAuth2 with PKCE, token storage, auto-refresh |
| **mail** | Jinja templates, transports (SMTP, Gmail API, Resend) |
| **alerts** | Multi-channel (Slack, Email), throttling, severity levels |
| **websocket** | Resilient connections, auto-reconnect, heartbeat, watchdog |
| **rapi** | Config-driven REST client with HMAC signing |
| **monitoring** | Collectors + Jinja rendering + delivery (file, mail) |
| **resilience** | Circuit breaker, rate limiter, graceful shutdown |
| **ops** | Session manager (tmux), containers (Docker/Podman) |
| **helpers** | TimeTrigger, formatting, secure delete, validators |

## Quick Start

### Installation

```bash
pip install kstlib
```

### Basic Usage

```python
from kstlib.config import load_from_file
from kstlib import cache

config = load_from_file("config.yml")

@cache(ttl=300)
def expensive_computation(x: int) -> int:
    return x ** 2

result = expensive_computation(5)
```

### Minimal Configuration

```yaml
app:
  name: "My Application"
  debug: true

database:
  host: "localhost"
  port: 5432
```

## Documentation

Full documentation available at **[kstlib.readthedocs.io](https://kstlib.readthedocs.io/)**

- [Features Guide](https://kstlib.readthedocs.io/en/latest/features/index.html)
- [Examples Gallery](https://kstlib.readthedocs.io/en/latest/examples.html)
- [API Reference](https://kstlib.readthedocs.io/en/latest/api/index.html)
- [Development Guide](https://kstlib.readthedocs.io/en/latest/development/index.html)

## Installation Options

```bash
# Standard install
pip install kstlib

# With uv (faster)
uv pip install kstlib

# Development install
pip install "kstlib[dev]"

# All extras
pip install "kstlib[all]"

# From GitHub (latest)
pip install "git+https://github.com/KaminoU/kstlib.git"
```

## License

MIT License - Copyright 2025 Michel TRUONG

See [LICENSE](LICENSE.md) for full text.
