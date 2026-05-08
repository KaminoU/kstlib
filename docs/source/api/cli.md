# CLI

`kstlib.cli` exposes the command-line interface as a [Typer](https://typer.tiangolo.com/) application. The single public symbol is `app`, the root Typer instance, which is registered as the `kstlib` console script in `pyproject.toml` so it can be invoked directly from the shell.

```{tip}
See {doc}`../features/cli/index` for the user-facing guide with command examples and verbosity flags.
```

## Quick overview

- `kstlib.cli.app` is a `typer.Typer` instance that aggregates the subcommand groups (`auth`, `config`, `ops`, `rapi`, `secrets`) plus the top-level `info` and `version` commands.
- The console script entry point `kstlib` (defined in `pyproject.toml`) calls `app()` so users can run `kstlib --help`, `kstlib auth login`, etc.
- Subcommand groups are registered via `kstlib.cli.commands.<group>.register_cli(app)` at import time.
- Verbose flags (`-v`, `-vv`, `-vvv`) and `--log-module <name>=<level>` are handled in the global callback before any subcommand runs.

## Command tree

| Group | Purpose |
|---|---|
| `info` | Display package information and logo. |
| `version` | Show the installed `kstlib` version. |
| `auth` | OAuth2 / OIDC flows, token management. |
| `config` | Inspect and resolve configuration files (cascade, includes, env vars). |
| `ops` | Session management (tmux / container backends): start, stop, attach, list. |
| `rapi` | Invoke configured REST endpoints (multi-server, body templates, safeguards). |
| `secrets` | Resolve / shred secrets via the configured providers (SOPS, KMS, env, keyring). |

Each group is exposed as a Typer subcommand and supports `--help` for inline discovery.

## Module reference

```{eval-rst}
.. automodule:: kstlib.cli
    :members:
    :undoc-members:
    :show-inheritance:
    :noindex:
```
