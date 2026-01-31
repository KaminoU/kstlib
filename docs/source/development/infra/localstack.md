# LocalStack (AWS Emulation)

[LocalStack](https://localstack.cloud/) emulates AWS services locally for testing the secrets module without cloud accounts.

## Features

- **Offline development**: No AWS account required
- **Fast iteration**: No network latency
- **CI/CD testing**: Reproducible isolated tests
- **Cost savings**: No cloud charges

## Quick Start

```bash
cd infra

# Start LocalStack only
docker compose up -d localstack

# Check it's ready (wait for "LocalStack Ready" message)
docker compose logs -f localstack
```

## Pre-configured Resources

The bootstrap script (`localstack/init-aws.sh`) creates these resources on startup:

| Service | Resource | Description |
| - | - | - |
| KMS | `alias/kstlib-test` | Symmetric encryption key |
| S3 | `kstlib-secrets-test` | Bucket for encrypted files |
| Secrets Manager | `kstlib/test/api-key` | Test secret with API credentials |

## Usage

### AWS CLI

**Prerequisites:**

1. AWS CLI v2 must be installed (see {doc}`index`)
2. Install the wrapper: `pip install kstlib[infra-tools]`

::::{tab-set}

:::{tab-item} Linux / macOS
The `awslocal` command is a thin wrapper around `aws` that automatically targets LocalStack:

```bash
# List KMS keys
awslocal kms list-keys

# Encrypt data
awslocal kms encrypt \
    --key-id alias/kstlib-test \
    --plaintext "my secret" \
    --output text --query CiphertextBlob

# List S3 buckets
awslocal s3 ls

# Get secret value
awslocal secretsmanager get-secret-value --secret-id kstlib/test/api-key
```

:::

:::{tab-item} Windows
`awslocal` has a known bug on Windows (cannot determine HOME directory). Add this function to your PowerShell profile (`$PROFILE`):

```powershell
function awslocal {
    $env:HOME = $env:USERPROFILE
    $env:AWS_ACCESS_KEY_ID = "test"
    $env:AWS_SECRET_ACCESS_KEY = "test"
    aws --endpoint-url=http://localhost:4566 --region us-east-1 @args
}
```

Then use it the same way as on Linux/macOS:

```powershell
awslocal kms list-keys
awslocal s3 ls
awslocal secretsmanager get-secret-value --secret-id kstlib/test/api-key
```

:::

::::

### Python / boto3

```python
import boto3

# Configure client for LocalStack
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
    Plaintext=b'my secret data'
)
ciphertext = response['CiphertextBlob']

# Decrypt
response = kms.decrypt(CiphertextBlob=ciphertext)
plaintext = response['Plaintext']
```

## Configuration

Copy the environment template and adjust as needed:

```bash
cp .env.example .env
```

Available settings:

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `LOCALSTACK_PORT` | 4566 | Gateway port |
| `AWS_DEFAULT_REGION` | us-east-1 | AWS region |
| `LOCALSTACK_PERSISTENCE` | 1 | Persist data between restarts |
| `LOCALSTACK_DEBUG` | 0 | Enable debug logging |

## CI/CD Integration

### GitHub Actions

```yaml
services:
  localstack:
    image: localstack/localstack:latest
    ports:
      - 4566:4566
    env:
      SERVICES: kms,s3,secretsmanager

steps:
  - name: Wait for LocalStack
    run: |
      timeout 30 bash -c 'until curl -s http://localhost:4566/_localstack/health | grep -q running; do sleep 1; done'
```

### pytest Fixture

```python
import pytest
import boto3

@pytest.fixture
def kms_client():
    """KMS client configured for LocalStack."""
    return boto3.client(
        'kms',
        endpoint_url='http://localhost:4566',
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )

def test_encrypt_decrypt(kms_client):
    # Encrypt
    encrypted = kms_client.encrypt(
        KeyId='alias/kstlib-test',
        Plaintext=b'test data'
    )

    # Decrypt
    decrypted = kms_client.decrypt(
        CiphertextBlob=encrypted['CiphertextBlob']
    )

    assert decrypted['Plaintext'] == b'test data'
```

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs localstack
```

Verify port is available:

::::{tab-set}

:::{tab-item} Linux / macOS

```bash
lsof -i :4566
```

:::

:::{tab-item} Windows

```powershell
netstat -an | findstr 4566
```

:::

::::

### Init script not running

The bootstrap script (`init-aws.sh`) runs automatically on container start. If resources aren't created:

```bash
# Check script executed
docker compose logs localstack | grep "LocalStack Ready"

# Run manually if needed
docker compose exec localstack bash /etc/localstack/init/ready.d/init-aws.sh
```

### Full reset

```bash
docker compose down -v
docker compose up -d localstack
```

## See Also

- {doc}`../secrets-workflow` - SOPS-based secrets management
- {doc}`../secrets-management` - SecretResolver documentation
- [LocalStack Documentation](https://docs.localstack.cloud/)
- [AWS KMS Documentation](https://docs.aws.amazon.com/kms/)
