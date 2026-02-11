---
hide-toc: true
---

# Kstlib Documentation

```{image} ../../assets/kstlib.svg
:alt: kstlib logo
:align: center
:width: 420px
```

**kstlib** is a personal Python toolkit I've been building for over 7 years.

It started as a **learning project** to explore Python best practices, then evolved into utilities
for personal automation, and now serves as the foundation for **study projects** in algorithmic
trading and crypto market analysis.

The focus has always been on understanding how to build **resilient, secure, and performant**
systems, not on profits (my portfolio can confirm).

This release is a "snapshot" as I move on to new experiments. I'm sharing it in case these
building blocks help others on similar learning journeys.

```{note}
Everything works via Python, but since kstlib is heavily config-driven,
the [Examples Gallery](examples) showcases an alternative YAML-first approach.
```

```{tip}
As part of this learning journey, I've also been exploring **AI-assisted development**.
Working with an AI copilot makes it possible to maintain a test suite of **16,000+ tests**
across multiple Python versions with **98% coverage**, something that would be humanly
impossible to achieve alone. And yes, this documentation too... writing docs is painful,
every developer knows that!
```

## Core Modules

| Module | Purpose |
|--------|---------|
| **config** | Cascading config files, includes, SOPS encryption, Box access |
| **secrets** | Multi-provider resolver (env, keyring, SOPS, KMS) with guardrails |
| **logging** | Rich console, rotating files, TRACE level, structlog integration |
| **auth** | OIDC/OAuth2 with PKCE, token storage, auto-refresh |
| **mail** | Jinja templates, transports (SMTP, Gmail API, Resend, AWS SES) |
| **alerts** | Multi-channel (Slack, Email), throttling, severity levels |
| **websocket** | Resilient connections, auto-reconnect, heartbeat, watchdog |
| **rapi** | Config-driven REST client with HMAC signing |
| **monitoring** | Collectors + Jinja rendering + delivery (file, mail) |
| **resilience** | Circuit breaker, rate limiter, graceful shutdown |
| **ops** | Session manager (tmux), containers (Docker/Podman) |
| **pipeline** | Declarative step execution (shell, Python, callable) |
| **helpers/utils** | TimeTrigger, formatting, secure delete, validators |

## Quick Start

### Installation

```bash
pip install kstlib
```

::::{dropdown} Alternative installation options
:icon: download

#### Using uv (recommended for speed)

```bash
uv pip install kstlib
```

[uv](https://docs.astral.sh/uv/) is a fast Python package installer. It respects lock files and provides
reproducible installs out of the box.

#### Extras bundles

```bash
pip install "kstlib[dev]"
pip install "kstlib[ses]"
pip install "kstlib[docs]"
pip install "kstlib[all]"
```

- `dev` installs linting, testing, and typing helpers for contributors.
- `ses` installs **boto3** for sending emails via AWS SES (`SesTransport`).
- `docs` installs the Sphinx toolchain for building the documentation locally.
- `all` pulls every optional dependency so a workstation mirrors the maintainer toolkit.

#### Install directly from GitHub

```bash
pip install "git+https://github.com/KaminoU/kstlib.git"
```

This command tracks the main branch without waiting for a published release.

#### Editable clone for development

```bash
git clone https://github.com/KaminoU/kstlib.git
cd kstlib
pip install -e ".[dev]"
```

Use this when you need to hack on the source, run the full test suite, or pin the project inside a monorepo.

#### Supply chain and offline installation

For air-gapped environments or strict supply chain requirements, kstlib provides an offline bundle
containing all dependency wheels and a locked requirements file for reproducible installs.
See {doc}`development/makefile` for details on `make dist-bundle`.

::::

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

## Documentation Contents

```{toctree}
:hidden:
:maxdepth: 2
:caption: Features

features/index
examples
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: API Reference

api/index
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: Development

development/index
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: Meta

changelog
license
```

## Indices and Tables

- {ref}`genindex`
- {ref}`modindex`
