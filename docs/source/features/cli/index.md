# CLI

Command-line interface for `kstlib`. Built on [Typer](https://typer.tiangolo.com/) with [Rich](https://rich.readthedocs.io/) for colored output, the CLI exposes the most common operations of the library so they can be invoked directly from a terminal or shell script without writing Python glue.

```{tip}
For the API reference of the underlying `kstlib.cli` module, see {doc}`../../api/cli`.
```

## TL;DR

```bash
# Show package info and logo
kstlib info

# Show version
kstlib version

# OAuth2 / OIDC flows
kstlib auth login --provider keycloak

# Resolve a config file with cascade and includes
kstlib config show ./kstlib.conf.yml

# Manage tmux/container sessions
kstlib ops list
kstlib ops attach my-session

# Call a configured REST endpoint (RAPI)
kstlib rapi --server github github.repos-list

# Resolve / shred secrets
kstlib secrets resolve mysecret
kstlib secrets shred path/to/file
```

## Key Features

- **Subcommand groups**: `auth`, `config`, `ops`, `rapi`, `secrets`, plus top-level `info` and `version`.
- **Verbose flags**: `-v` / `-vv` / `-vvv` map to `INFO` / `DEBUG` / `TRACE` log levels.
- **Per-module log control**: `--log-module <name>=<level>` overrides verbosity for a single module without globally enabling TRACE.
- **Config-driven**: every subcommand reads `kstlib.conf.yml` via the standard cascade (`kwargs > user config > presets > defaults`).
- **Rich output**: tables, panels, colored status messages by default; pipe-friendly fallback when stdout is not a TTY.

## Verbosity examples

```bash
# Default: WARNING
kstlib info

# -v: INFO
kstlib -v auth login

# -vv: DEBUG
kstlib -vv rapi --server github github.repos-list

# -vvv: TRACE (firehose, includes per-item logs)
kstlib -vvv rapi --server github github.repos-list

# Per-module override (mute everything except auth.providers)
kstlib --log-module kstlib.auth.providers=DEBUG rapi --server github github.repos-list
```

## Discoverability

Each command supports `--help` so the available options and sub-options can be browsed without leaving the terminal:

```bash
kstlib --help
kstlib auth --help
kstlib rapi --help
```
