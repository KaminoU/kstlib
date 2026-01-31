# Testing

This guide covers kstlib's test suite: structure, running tests, and writing new tests.

```{note}
The full test suite runs **16,000+ tests** across 5 Python versions (3.10-3.14).
Each version executes ~3,200 unit tests, ensuring compatibility across the Python ecosystem.
```

## Quick Start

```bash
# Full validation (recommended before commits)
make tox

# Run tests on a specific Python version
tox -e py310

# Run specific test module
pytest tests/secrets_module/ -v

# Run with LocalStack for KMS tests
cd infra && docker compose up -d
pytest tests/secrets_module/test_sops_e2e.py -v
```

## Test Structure

```text
tests/
├── alerts/                     # AlertManager, channels, throttling
├── auth_module/                # OAuth2/OIDC, token storage, callbacks
├── cache/                      # TTL, LRU, File cache strategies
├── cli/                        # @pytest.mark.cli (separate coverage)
├── config/                     # Loader, export, includes, SOPS integration
├── db/                         # Database pool, cipher, migrations
├── helpers/                    # TimeTrigger, scheduling utilities
├── logging/                    # LogManager, levels, formatters, structlog
├── mail/                       # Builder, transports (SMTP, Gmail, Resend)
├── metrics/                    # Decorators, collectors
├── monitoring/                 # Service, delivery, styles, collectors
├── ops/                        # Session manager, container operations
├── rapi/                       # REST client, config, HMAC signing
├── resilience/                 # Circuit breaker, rate limiter, shutdown
├── secrets_module/             # Providers, resolver, SOPS e2e
├── secure/                     # Secure delete, path guardrails
├── ui/                         # Panels, tables, spinners
├── utils/                      # Validators, formatting, text utilities
└── websocket/                  # Manager, reconnect, models, watchdog
```

## Running Tests

### With Tox (Recommended)

Tox manages isolated test environments:

```bash
# Specific Python version
tox -e py310
tox -e py311
tox -e py312
tox -e py313
tox -e py314

# Lint only (ruff + mypy)
tox -e lint

# Type checking
tox -e mypy

# Docstring examples
tox -e doctest

# Documentation build
tox -e docs
```

### Manual Tox Environments

Some environments are excluded from the default `tox` run and must be invoked manually:

```bash
# CLI tests (excluded from main runs to keep coverage focused on core library)
tox -e cli

# Integration tests (require real infrastructure: testnets, OAuth providers, etc.)
tox -e integration

# Deep structural analysis with Pylint (verbose, slower)
tox -e pylint
```

> **Important**: Run `tox -e cli` before each release to verify CLI functionality.
> Run `tox -e integration` when testing against real services (Binance testnet, etc.).
> Run `tox -e pylint` periodically for deep code audits.

### With Pytest Directly

```bash
# All tests (excluding CLI)
pytest tests/ -m "not cli" --cov=kstlib --cov-report=term-missing

# CLI tests only
pytest tests/ -m cli -v

# All tests including CLI
pytest tests/ --cov=kstlib --cov-report=term-missing

# Specific module
pytest tests/config/ -v

# Specific test
pytest tests/cache/test_cache.py::TestTTLCacheStrategy -v

# Stop on first failure
pytest tests/ -x

# Show print statements
pytest tests/ -s
```

## Coverage Requirements

The project maintains **95% minimum coverage** for core library code:

```bash
# Core library coverage (excludes CLI tests)
pytest tests/ -m "not cli" --cov=kstlib --cov-fail-under=95

# CLI coverage (tracked separately)
pytest tests/ -m cli --cov=kstlib.cli
```

### Per-Module Coverage

| Module | Target | Notes |
| - | - | - |
| `alerts/` | 95%+ | Manager, channels, throttling |
| `auth/` | 95%+ | OAuth2, OIDC, token storage |
| `cache/` | 95%+ | TTL, LRU, file strategies |
| `cli/` | Separate | Tracked via `tox -e cli` |
| `config/` | 95%+ | Loader, export, SOPS includes |
| `db/` | 95%+ | Pool, cipher, migrations |
| `helpers/` | 95%+ | TimeTrigger, scheduling |
| `logging/` | 95%+ | LogManager, handlers |
| `mail/` | 95%+ | Builder, all transports |
| `metrics/` | 95%+ | Decorators, collectors |
| `monitoring/` | 95%+ | Service, delivery, styles |
| `ops/` | 95%+ | Session, containers |
| `rapi/` | 95%+ | Client, config, signing |
| `resilience/` | 95%+ | Circuit breaker, rate limiter |
| `secrets/` | 95%+ | All providers, resolver |
| `secure/` | 95%+ | Secure delete, guardrails |
| `ui/` | 95%+ | Panels, tables, spinners |
| `utils/` | 95%+ | Validators, formatting |
| `websocket/` | 95%+ | Manager, reconnect, watchdog |

> **Note**: CLI tests are marked with `@pytest.mark.cli` and excluded from main coverage
> to keep metrics focused on the reusable library code.

### Integration-Only Code

Some modules contain code that cannot be tested with unit tests alone because they
require real external infrastructure (WebSocket servers, OAuth providers, etc.).

#### Affected Modules

| Module | Unit Coverage | Integration Code |
| - | - | - |
| `websocket.manager` | ~71% | Real WebSocket connection, ping/pong, reconnection |
| `rapi.credentials` | ~62% | Real OAuth2 token exchange flows |
| `alerts.manager` | ~70% | Real Slack/Email channel delivery |

#### The `@pytest.mark.integration` Marker

Use this marker for tests that require real infrastructure:

```python
import pytest

@pytest.mark.integration
class TestWebSocketBinanceTestnet:
    """Tests requiring Binance testnet WebSocket."""

    async def test_real_connection(self) -> None:
        """Connect to real Binance testnet."""
        ws = WebSocketManager(url="wss://testnet.binance.vision/ws")
        async with ws:
            msg = await ws.receive()
            assert msg is not None
```

#### Running Integration Tests

```bash
# With tox (recommended)
tox -e integration

# With pytest directly
pytest tests/ -m integration -v

# Run all tests EXCEPT integration (default tox behavior)
pytest tests/ -m "not cli and not integration" -v

# Run integration tests for a specific module
pytest tests/websocket/ -m integration -v
```

> **Note**: Integration tests are excluded from the default `tox` run (alongside CLI tests).
> Run `tox -e integration` manually when you have access to real infrastructure (testnets, etc.).

#### Excluding from Coverage Calculation

Integration-only code paths can be marked with a justified pragma:

```python
async def _real_websocket_loop(self) -> None:  # pragma: no cover (integration)
    """Main receive loop - requires real WebSocket server."""
    async for message in self._ws:
        await self._handle_message(message)
```

> **Important**: Only use `# pragma: no cover` with a justification comment
> explaining why the code cannot be unit tested. Never use it to hide
> untested code that could be tested.

#### Effective Coverage

When excluding integration-only code, the effective unit test coverage is:

| Category | Coverage |
| - | - |
| **Unit-testable code** | ~98-99% |
| **Integration-only code** | Tested via `tox -e integration` or manual testnet |
| **CLI code** | Tracked via `tox -e cli` |

## SOPS End-to-End Tests

The `tests/secrets_module/test_sops_e2e.py` module tests SOPS encryption with real backends.

### Test Classes

| Class | Backend | Tests |
| - | - | - |
| `TestSopsAgeBackend` | Age | YAML/JSON roundtrip, plaintext verification |
| `TestSopsGpgBackend` | GPG | YAML roundtrip, fingerprint verification |
| `TestSopsKmsBackend` | KMS (LocalStack) | YAML roundtrip, ARN verification |
| `examples/secrets/kms/` | KMS (real AWS) | Working example with production key |
| `TestKstlibSecretsCliAge` | CLI | `kstlib secrets encrypt/decrypt` |

### Fixtures

#### `age_keypair`

Generates a temporary age keypair for testing:

```python
@pytest.fixture
def age_keypair(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    """Generate temporary age keypair for SOPS testing."""
    keys_file = tmp_path / "age-keys.txt"
    subprocess.run(["age-keygen", "-o", str(keys_file)], check=True)

    # Extract public key
    result = subprocess.run(["age-keygen", "-y", str(keys_file)], capture_output=True)
    public_key = result.stdout.strip()

    yield {"keys_file": keys_file, "public_key": public_key}
```

#### `gpg_keypair`

Generates a temporary GPG keypair with isolated GNUPGHOME:

```python
@pytest.fixture
def gpg_keypair(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    """Generate temporary GPG keypair for SOPS testing."""
    gnupghome = tmp_path / ".gnupg"
    gnupghome.mkdir()

    # Batch key generation (no passphrase)
    key_params = tmp_path / "key-params.txt"
    key_params.write_text("""
Key-Type: RSA
Key-Length: 2048
Name-Real: Test User
Name-Email: test@test.local
Expire-Date: 0
%no-protection
%commit
""")

    env = {**os.environ, "GNUPGHOME": str(gnupghome)}
    subprocess.run(["gpg", "--batch", "--gen-key", str(key_params)], env=env, check=True)

    yield {"gnupghome": gnupghome, "fingerprint": "...", "email": "test@test.local"}
```

#### `kms_key_arn`

Resolves the KMS key ARN from LocalStack:

```python
@pytest.fixture
def kms_key_arn(kms_client: Any, localstack_key_alias: str) -> str:
    """Resolve the KMS key ARN from the alias."""
    response = kms_client.describe_key(KeyId=localstack_key_alias)
    return response["KeyMetadata"]["Arn"]
```

### Skip Markers

Tests use conditional skip markers for graceful degradation:

```python
# Skip if sops binary not installed
requires_sops = pytest.mark.skipif(
    not shutil.which("sops"),
    reason="sops not installed (run: scoop install sops)",
)

# Skip if age-keygen not installed
requires_age = pytest.mark.skipif(
    not shutil.which("age-keygen"),
    reason="age-keygen not installed (run: scoop install age)",
)

# Skip if GPG has path issues (Windows cygdrive)
requires_gpg = pytest.mark.skipif(
    not _gpg_works_with_temp_dirs(),
    reason="gpg not installed or has path compatibility issues",
)

# Skip if LocalStack not running
requires_localstack = pytest.mark.skipif(
    not _is_localstack_available(),
    reason="LocalStack not available (run: cd infra && docker compose up -d)",
)

# Skip if boto3 not installed
requires_boto3 = pytest.mark.skipif(
    not _has_boto3(),
    reason="boto3 not installed (run: pip install boto3)",
)
```

Usage in tests:

```python
@requires_sops
@requires_age
class TestSopsAgeBackend:
    def test_encrypt_decrypt_yaml_roundtrip(self, age_keypair, age_sops_config):
        # Test runs only if sops and age are available
        ...
```

### Windows Compatibility

#### GPG Path Issues

Git for Windows bundles a Cygwin-based GPG that mangles paths:

```text
# Bad: Git GPG with cygdrive paths
/cygdrive/c/Users/.../C:\Users\...\pubring.kbx
```

**Solution**: Use Gpg4win instead:

```powershell
# Install Gpg4win
scoop install gpg4win

# Add to PATH (before Git)
$env:PATH = "C:\Users\$env:USERNAME\scoop\apps\gpg4win\current\GnuPG\bin;$env:PATH"
```

The `_gpg_works_with_temp_dirs()` function detects this issue and skips tests accordingly.

#### Subprocess Encoding

Windows uses cp1252 by default, which can't decode UTF-8 output:

```python
# Fix: Specify UTF-8 encoding
result = subprocess.run(
    ["kstlib", "secrets", "encrypt", ...],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",  # Handle any remaining decode errors
)
```

### LocalStack Setup

KMS tests require LocalStack:

```bash
# Start LocalStack
cd infra
docker compose up -d

# Verify
curl http://localhost:4566/_localstack/health

# Run KMS tests
pytest tests/secrets_module/test_sops_e2e.py::TestSopsKmsBackend -v
```

The `init-localstack.sh` script creates the test KMS key:

```bash
awslocal kms create-key --description "kstlib test key"
awslocal kms create-alias \
    --alias-name alias/kstlib-test \
    --target-key-id <key-id>
```

## Mock Fixtures

### `mock_boto3_kms`

For unit tests without real AWS/LocalStack:

```python
@pytest.fixture
def mock_boto3_kms(monkeypatch):
    """Mock boto3.client for KMS tests."""
    captures = {
        "encrypt_calls": [],
        "decrypt_calls": [],
        "encrypt_response": {"CiphertextBlob": b"encrypted", "KeyId": "arn:..."},
        "decrypt_response": {"Plaintext": b"decrypted", "KeyId": "arn:..."},
    }

    def mock_encrypt(**kwargs):
        captures["encrypt_calls"].append(kwargs)
        return captures["encrypt_response"]

    # Patch boto3 at module level
    monkeypatch.setattr("kstlib.secrets.providers.kms.boto3", fake_boto3)
    return captures
```

Usage:

```python
def test_kms_encrypt(mock_boto3_kms):
    provider = KMSProvider(key_id="alias/test")
    result = provider.encrypt(b"secret")

    assert mock_boto3_kms["encrypt_calls"][0]["Plaintext"] == b"secret"
```

## Writing New Tests

### Test File Template

```python
"""Tests for module_name."""

from __future__ import annotations

import pytest

from kstlib.module_name import SomeClass


class TestSomeClass:
    """Tests for SomeClass."""

    def test_basic_functionality(self) -> None:
        """Test basic usage."""
        obj = SomeClass()
        assert obj.do_something() == expected

    def test_edge_case(self) -> None:
        """Test edge case handling."""
        obj = SomeClass()
        with pytest.raises(ValueError, match="invalid input"):
            obj.do_something(invalid_input)

    @pytest.mark.parametrize("input,expected", [
        ("a", 1),
        ("b", 2),
        ("c", 3),
    ])
    def test_parameterized(self, input: str, expected: int) -> None:
        """Test with multiple inputs."""
        assert SomeClass().process(input) == expected
```

### Async Tests

```python
import pytest

@pytest.mark.asyncio
async def test_async_function() -> None:
    """Test async functionality."""
    result = await some_async_function()
    assert result == expected
```

### Temporary Files

```python
def test_with_temp_file(tmp_path: Path) -> None:
    """Test with temporary directory."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("key: value")

    result = load_config(config_file)
    assert result["key"] == "value"
```

## CI Integration

Tests run automatically on GitHub Actions with **uv caching** for faster builds:

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    strategy:
      fail-fast: true  # Stop all jobs on first failure (cost optimization)
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true  # Cache dependencies across runs

      - name: Set up Python
        run: uv python install ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync --all-extras

      - name: Run tests
        run: uv run pytest tests/ -v --cov=src
```

### CI Optimizations

| Optimization | Benefit |
| - | - |
| `fail-fast: true` | Stop all jobs on first failure, saves compute |
| `enable-cache: true` | Cache uv/pip dependencies across runs |
| `uv sync` | 10-100x faster than pip install |
| `lock-check` first | Fail fast if lock files are out of sync |

### Test Results

- Coverage reports uploaded to Codecov
- Test results visible in PR checks
- Minimum 95% coverage enforced
