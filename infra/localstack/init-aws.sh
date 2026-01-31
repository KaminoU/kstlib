#!/bin/bash
# LocalStack initialization script for kstlib
# Automatically executed on container startup

set -e

echo "=== kstlib LocalStack Initialization ==="

# Wait for KMS to be ready
awslocal kms list-keys > /dev/null 2>&1 || sleep 2

# --- KMS: Create test key ---
echo "[KMS] Creating test key..."
KEY_ID=$(awslocal kms create-key --description "kstlib-test-key" --query 'KeyMetadata.KeyId' --output text)

# Create alias for easy access
awslocal kms create-alias --alias-name "alias/kstlib-test" --target-key-id "$KEY_ID"

echo "[KMS] Key created: $KEY_ID"
echo "[KMS] Alias: alias/kstlib-test"

# --- S3: Bucket for encrypted secrets ---
echo "[S3] Creating test bucket..."
awslocal s3 mb s3://kstlib-secrets-test 2>/dev/null || true
echo "[S3] Bucket created: kstlib-secrets-test"

# --- Secrets Manager: Test secret ---
echo "[SecretsManager] Creating test secret..."
awslocal secretsmanager create-secret --name "kstlib/test/api-key" --description "Test secret for kstlib" --secret-string '{"api_key": "test-api-key-12345", "api_secret": "test-secret-67890"}' 2>/dev/null || true
echo "[SecretsManager] Secret created: kstlib/test/api-key"

# --- Summary ---
echo ""
echo "=== LocalStack Ready ==="
echo "Endpoint: http://localhost:4566"
echo "Region: ${AWS_DEFAULT_REGION:-us-east-1}"
echo ""
echo "Available resources:"
echo "  - KMS Key: alias/kstlib-test ($KEY_ID)"
echo "  - S3 Bucket: kstlib-secrets-test"
echo "  - Secret: kstlib/test/api-key"
echo ""
echo "Quick test:"
echo "  awslocal kms list-keys"
echo "  awslocal s3 ls"
echo "  awslocal secretsmanager list-secrets"
