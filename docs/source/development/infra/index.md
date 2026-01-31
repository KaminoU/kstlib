# Local Infrastructure

Development infrastructure for testing integrations without cloud accounts.

## Overview

kstlib provides Docker-based local infrastructure for two purposes:

| Service | Purpose | Module |
| ------- | ------- | ------ |
| [LocalStack](localstack) | AWS emulation (KMS, S3, Secrets Manager) | `kstlib.secrets` |
| [Keycloak](keycloak) | OIDC/OAuth2 identity provider | `kstlib.auth` |

## Prerequisites

- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- AWS CLI v2 (required for `awslocal` wrapper) see [AWS CLI install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

## Quick Start

```bash
cd infra

# Start all services
docker compose up -d

# Start only what you need
docker compose up -d keycloak     # Auth testing only
docker compose up -d localstack   # AWS testing only
```

## Infrastructure Tools

Install optional CLI tools for local development:

```bash
pip install kstlib[infra-tools]
```

This includes:

- `awscli-local` - LocalStack AWS CLI wrapper (`awslocal` command)

## Service Endpoints

| Service | URL | Credentials |
| - | - | - |
| LocalStack | <http://localhost:4566> | `test` / `test` |
| Keycloak Admin | <http://localhost:8080/admin> | `admin` / `admin` |
| Keycloak OIDC | <http://localhost:8080/realms/kstlib-test> | See {doc}`keycloak` |

## Directory Structure

```text
infra/
├── docker-compose.yml    # Service definitions
├── .env.example          # Environment template
├── .env                  # Local config (gitignored)
├── README.md             # Quick reference
├── localstack/
│   └── init-aws.sh       # AWS resources bootstrap
└── keycloak/
    └── realm-export.json # Test realm with users/clients
```

## Docker Commands

```bash
# Start services
docker compose up -d

# Stop services
docker compose down

# Stop and delete all data
docker compose down -v

# View logs
docker compose logs -f
docker compose logs -f keycloak    # Single service

# Restart
docker compose restart

# Check status
docker compose ps
```

```{toctree}
:maxdepth: 1
:hidden:

localstack
keycloak
```
