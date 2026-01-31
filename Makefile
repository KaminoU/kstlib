# Convenience wrappers around the kstlib secrets CLI.
# The CLI remains the source of truth; these targets forward to it.

# Default target: show help
.DEFAULT_GOAL := help

.PHONY: help tox tox-clean lock lock-check dist dist-bundle secrets-doctor secrets-encrypt secrets-decrypt secrets-shred

help:
	@echo "Development:"
	@echo "  tox              -> Run full tox suite + create commit marker"
	@echo "  tox-clean        -> Clean caches + recreate tox environments (fixes cross-platform issues)"
	@echo ""
	@echo "Lock file management:"
	@echo "  lock             -> Regenerate uv.lock and pylock.toml"
	@echo "  lock-check       -> Verify lock files are in sync"
	@echo ""
	@echo "Build:"
	@echo "  dist             -> Build wheel package in dist/"
	@echo "  dist-bundle      -> Build wheel + all deps (offline install)"
	@echo ""
	@echo "Secrets helpers (thin wrappers around 'kstlib secrets'):"
	@echo "  secrets-doctor   -> kstlib secrets doctor"
	@echo "  secrets-encrypt  -> kstlib secrets encrypt"
	@echo "  secrets-decrypt  -> kstlib secrets decrypt"
	@echo "  secrets-shred    -> kstlib secrets shred"
	@echo ""
	@echo "Common variables:"
	@echo "  SOURCE=path/to/secrets.yml      (encrypt/decrypt source file)"
	@echo "  OUT=path/to/output.yml          (optional --out)"
	@echo "  CONFIG=path/to/.sops.yaml       (passes --config)"
	@echo "  BINARY=/usr/bin/sops            (override --binary)"
	@echo "  FORMATS='yaml json'             (forwarded to --format)"
	@echo "  FORCE=1 | QUIET=1 | SHRED=1     (truthy -> adds matching flag)"
	@echo ""
	@echo "Example: make secrets-encrypt SOURCE=secrets.yml OUT=secrets.sops.yml CONFIG=~/.sops.yaml"

# Lock file management (quiet output)
lock:
	@echo "Regenerating lock files..."
	@uv lock --quiet
	@uv export --format pylock.toml --all-extras -o pylock.toml --quiet
	@echo "Done. See uv.lock and pylock.toml for details."

lock-check:
	@uv lock --check
	@python -c "\
import subprocess, sys; \
from pathlib import Path; \
subprocess.run(['uv', 'export', '--format', 'pylock.toml', '--all-extras', '-o', 'pylock.check.toml', '--quiet'], check=True); \
cur = Path('pylock.toml').read_text().split('\n', 2)[-1] if Path('pylock.toml').exists() else ''; \
new = Path('pylock.check.toml').read_text().split('\n', 2)[-1] if Path('pylock.check.toml').exists() else ''; \
Path('pylock.check.toml').unlink(missing_ok=True); \
sys.exit(0) if cur == new else (print('Lock files out of sync. Run: make lock'), sys.exit(1))"
	@echo "Lock files are in sync."

# Build wheel package for distribution
dist:
	@echo "Cleaning previous builds..."
	@python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ['dist', 'build', 'src/kstlib.egg-info']]"
	@echo "Building wheel..."
	@python -m build --wheel
	@echo ""
	@python -c "from pathlib import Path; whl = next(Path('dist').glob('*.whl')); print(f'[OK] Built: {whl}')"

# Build wheel + all dependencies for offline install
dist-bundle: dist
	@echo "Creating offline bundle..."
	@python -c "import shutil; from pathlib import Path; shutil.rmtree('dist/bundle', ignore_errors=True); Path('dist/bundle').mkdir(parents=True, exist_ok=True)"
	@echo "Exporting locked dependencies..."
	@uv export --format requirements-txt --no-hashes --no-dev --no-emit-project -o dist/requirements-lock.txt --quiet
	@echo "Downloading dependency wheels..."
	@pip download -r dist/requirements-lock.txt -d dist/bundle --no-cache-dir --quiet
	@echo "Adding kstlib wheel..."
	@python -c "import shutil; from pathlib import Path; whl = next(Path('dist').glob('kstlib-*.whl')); shutil.copy(whl, 'dist/bundle/')"
	@echo "Creating zip archive..."
	@python -c "import shutil; from pathlib import Path; whl = next(Path('dist').glob('kstlib-*.whl')); ver = whl.stem.split('-')[1]; shutil.make_archive(f'dist/kstlib-{ver}-bundle', 'zip', 'dist/bundle')"
	@python -c "import shutil; shutil.rmtree('dist/bundle')"
	@echo ""
	@python -c "from pathlib import Path; z = next(Path('dist').glob('*-bundle.zip')); r = Path('dist/requirements-lock.txt'); print(f'[OK] Bundle: {z} ({z.stat().st_size / 1024 / 1024:.1f} MB)'); print(f'[OK] Lock file: {r} (for cross-platform install)')"

# Run tox and create marker on success (enables fast pre-commit)
tox:
	@echo "Formatting code..."
	@ruff format src/ tests/
	@tox && python -c "from pathlib import Path; Path('.github/.tox-passed').touch(); print('[OK] Tox passed. Marker created for fast commit.')"

# Run tox with -r to recreate environments (fixes corrupted cache)
tox-clean:
	@echo "Cleaning caches..."
	@python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov']]; pathlib.Path('.coverage').unlink(missing_ok=True)"
	@echo "Formatting code..."
	@ruff format src/ tests/
	@echo "Recreating tox environments..."
	@tox -r && python -c "from pathlib import Path; Path('.github/.tox-passed').touch(); print('[OK] Tox passed (clean). Marker created for fast commit.')"

# Secrets CLI variables
KSTLIB ?= kstlib
BINARY ?= sops
CONFIG ?=
FORMATS ?= auto auto
QUIET ?=
SHRED ?=
SHRED_METHOD ?=
SHRED_PASSES ?=
SHRED_ZERO_LAST ?=
SHRED_CHUNK_SIZE ?=
SHRED_FORCE ?=
SHRED_QUIET ?=
METHOD ?=
PASSES ?=
ZERO_LAST ?=
CHUNK_SIZE ?=

secrets-doctor:
	$(KSTLIB) secrets doctor --binary $(BINARY)

secrets-encrypt:
ifndef SOURCE
	$(error SOURCE is required, e.g. make secrets-encrypt SOURCE=secrets.yml)
endif
	$(KSTLIB) secrets encrypt $(SOURCE) $(if $(OUT),--out $(OUT),) --binary $(BINARY) $(if $(FORCE),--force,) --format $(FORMATS) $(if $(QUIET),--quiet,) $(if $(SHRED),--shred,) \
		$(if $(CONFIG),--config $(CONFIG),) \
		$(if $(SHRED_METHOD),--shred-method $(SHRED_METHOD),) \
		$(if $(SHRED_PASSES),--shred-passes $(SHRED_PASSES),) \
		$(if $(SHRED_ZERO_LAST),$(if $(filter true TRUE 1 yes YES on ON,$(SHRED_ZERO_LAST)),--shred-zero-last-pass,--shred-no-zero-last-pass),) \
		$(if $(SHRED_CHUNK_SIZE),--shred-chunk-size $(SHRED_CHUNK_SIZE),)

secrets-decrypt:
ifndef SOURCE
	$(error SOURCE is required, e.g. make secrets-decrypt SOURCE=secrets.sops.yml)
endif
	$(KSTLIB) secrets decrypt $(SOURCE) $(if $(OUT),--out $(OUT),) --binary $(BINARY) $(if $(FORCE),--force,) $(if $(QUIET),--quiet,)

secrets-shred:
ifndef TARGET
	$(error TARGET is required, e.g. make secrets-shred TARGET=secrets.yml)
endif
	$(KSTLIB) secrets shred $(TARGET) $(if $(SHRED_FORCE),--force,) $(if $(SHRED_QUIET),--quiet,) \
		$(if $(METHOD),--method $(METHOD),) \
		$(if $(PASSES),--passes $(PASSES),) \
		$(if $(ZERO_LAST),$(if $(filter true TRUE 1 yes YES on ON,$(ZERO_LAST)),--zero-last-pass,--no-zero-last-pass),) \
		$(if $(CHUNK_SIZE),--chunk-size $(CHUNK_SIZE),)
