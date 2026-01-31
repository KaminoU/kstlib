# kstlib Development Infrastructure

Local infrastructure for integration testing with cloud services (AWS KMS, S3, Secrets Manager).

## Prerequisites

- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- AWS CLI v2 (optional, for manual testing)

## Quick Start

```bash
# From project root
cd infra

# Copy config (optional, defaults work fine)
cp .env.example .env

# Start LocalStack
docker compose up -d

# Check it's ready
docker compose logs -f localstack
```

Wait for the `=== LocalStack Ready ===` message in logs.

## Auto-Created Resources

| Service | Resource | Description |
| - | - | - |
| KMS | `alias/kstlib-test` | Test encryption key |
| S3 | `kstlib-secrets-test` | Bucket for encrypted files |
| Secrets Manager | `kstlib/test/api-key` | Test secret |

## Usage

### With AWS CLI

```bash
# Install awslocal (LocalStack wrapper)
pip install awscli-local

# List KMS keys
awslocal kms list-keys

# Encrypt text
awslocal kms encrypt \
    --key-id alias/kstlib-test \
    --plaintext "my secret" \
    --output text --query CiphertextBlob

# List secrets
awslocal secretsmanager list-secrets
```

### With Python/boto3

```python
import boto3

# Client configured for LocalStack
kms = boto3.client(
    'kms',
    endpoint_url='http://localhost:4566',
    region_name='us-east-1',
    aws_access_key_id='test',
    aws_secret_access_key='test'
)

# Encrypt
response = kms.encrypt(
    KeyId='alias/kstlib-test',
    Plaintext=b'my secret'
)
ciphertext = response['CiphertextBlob']

# Decrypt
response = kms.decrypt(CiphertextBlob=ciphertext)
plaintext = response['Plaintext']
```

### With kstlib (future)

```python
from kstlib.secrets import SecretResolver

resolver = SecretResolver(
    backend='aws-kms',
    endpoint_url='http://localhost:4566'  # LocalStack
)
```

## Useful Commands

```bash
# Stop services
docker compose down

# Stop and delete data
docker compose down -v

# View logs
docker compose logs -f

# Restart cleanly
docker compose restart

# Service status
docker compose ps
```

## Structure

```text
infra/
├── docker-compose.yml    # Docker services
├── .env.example          # Environment variables
├── .env                  # Local config (gitignored)
├── README.md             # This file
└── localstack/
    └── init-aws.sh       # Bootstrap on startup
```

## CI/CD Integration

For GitHub Actions, see `.github/workflows/` (coming soon).

```yaml
services:
  localstack:
    image: localstack/localstack:latest
    ports:
      - 4566:4566
```

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs localstack

# Check port 4566 is free
netstat -an | findstr 4566  # Windows
lsof -i :4566               # Linux/Mac
```

### KMS keys not created

```bash
# Run init script manually
docker compose exec localstack /etc/localstack/init/ready.d/init-aws.sh
```

### Full reset

```bash
docker compose down -v
docker compose up -d
```
