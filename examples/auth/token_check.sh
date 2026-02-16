#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════
# JWT Signature Verification - Bash (raw RSA math)
# ══════════════════════════════════════════════════════════
#
# Same approach as token_check.ps1: recovers the hash from
# the signature via raw RSA (sig^e mod n), computes the hash
# independently, and compares both. Two identical hashes =
# mathematical proof that the IDP signed this token.
#
# Dependencies: bash, curl, openssl, jq, xxd
#
# Usage:
#   ./token_check.sh                              # kstlib cached token
#   ./token_check.sh --token "eyJ..."             # explicit JWT
#   ./token_check.sh --ca-bundle /path/to/ca.pem  # corporate CA
#
# Exit codes: 0 (match), 1 (mismatch/error)
# ══════════════════════════════════════════════════════════

set -euo pipefail

# ── Colors ────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

# ── Args ──────────────────────────────────────────────────
TOKEN=""
CA_BUNDLE=""
TMPDIR_WORK=""

cleanup() { [[ -d "${TMPDIR_WORK:-}" ]] && rm -rf "$TMPDIR_WORK"; }
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)     TOKEN="$2"; shift 2 ;;
        --ca-bundle) CA_BUNDLE="$2"; shift 2 ;;
        --help|-h)   echo "Usage: $0 [--token JWT] [--ca-bundle PATH]"; exit 0 ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────

b64url_decode() {
    local s="$1"
    s=$(echo -n "$s" | tr '_-' '/+')
    local mod=$(( ${#s} % 4 ))
    [[ $mod -eq 2 ]] && s="${s}=="
    [[ $mod -eq 3 ]] && s="${s}="
    echo -n "$s" | base64 -d 2>/dev/null
}

b64url_to_hex() {
    b64url_decode "$1" | xxd -p | tr -d '\n'
}

fetch() {
    local args=(-s -f --max-time 10)
    [[ -n "$CA_BUNDLE" ]] && args+=(--cacert "$CA_BUNDLE")
    curl "${args[@]}" "$1"
}

# ASN.1 DER helpers (JWK n/e -> PEM when x5c is absent)
asn1_len() {
    local len=$1
    if (( len < 128 )); then printf '%02x' "$len"
    elif (( len < 256 )); then printf '81%02x' "$len"
    else printf '82%04x' "$len"; fi
}

asn1_integer() {
    local hex="$1"
    (( ${#hex} % 2 != 0 )) && hex="0${hex}"
    local fb=$((16#${hex:0:2}))
    (( fb >= 128 )) && hex="00${hex}"
    local len=$(( ${#hex} / 2 ))
    printf '02%s%s' "$(asn1_len "$len")" "$hex"
}

asn1_seq() {
    local c="$1"; local len=$(( ${#c} / 2 ))
    printf '30%s%s' "$(asn1_len "$len")" "$c"
}

asn1_bits() {
    local c="$1"; local len=$(( ${#c} / 2 + 1 ))
    printf '03%s00%s' "$(asn1_len "$len")" "$c"
}

jwk_to_pem() {
    local n_hex e_hex
    n_hex=$(b64url_to_hex "$1")
    e_hex=$(b64url_to_hex "$2")
    local rsa; rsa=$(asn1_seq "$(asn1_integer "$n_hex")$(asn1_integer "$e_hex")")
    local spki; spki=$(asn1_seq "300d06092a864886f70d0101010500$(asn1_bits "$rsa")")
    echo "-----BEGIN PUBLIC KEY-----"
    echo -n "$spki" | xxd -r -p | base64 | fold -w 64
    echo "-----END PUBLIC KEY-----"
}

# ══════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════

TMPDIR_WORK=$(mktemp -d)

# --- Config ---
if [[ -z "$TOKEN" ]]; then
    TOKEN=$(kstlib auth token 2>/dev/null) || {
        echo "Error: not authenticated / kstlib not found." >&2
        echo "Use --token or run 'kstlib auth login' first." >&2
        exit 1
    }
    echo -e "${DIM}Using cached token from kstlib${NC}"
fi
TOKEN=$(echo -n "$TOKEN" | tr -d '[:space:]')

# --- Step 1: Decode JWT ---
IFS='.' read -r H_B64 P_B64 S_B64 <<< "$TOKEN"
H_JSON=$(b64url_decode "$H_B64")
P_JSON=$(b64url_decode "$P_B64")

ALG=$(echo "$H_JSON" | jq -r '.alg')
KID=$(echo "$H_JSON" | jq -r '.kid')
ISS=$(echo "$P_JSON" | jq -r '.iss')

echo -e "\n${CYAN}=== JWT Header ===${NC}"
echo "$H_JSON" | jq .
echo -e "\n${CYAN}=== Claims (issuer, kid) ===${NC}"
echo "  alg = $ALG"
echo "  kid = $KID"
echo "  iss = $ISS"

# --- Step 2: Fetch public key ---
DISCO=$(fetch "${ISS%/}/.well-known/openid-configuration")
JWKS_URI=$(echo "$DISCO" | jq -r '.jwks_uri')
JWKS=$(fetch "$JWKS_URI")
KEY=$(echo "$JWKS" | jq --arg kid "$KID" '.keys[] | select(.kid == $kid)')

[[ -z "$KEY" ]] && { echo "Key kid=$KID not found" >&2; exit 1; }

echo -e "\n${CYAN}=== Public Key ===${NC}"
echo "  kid = $KID"
echo "  kty = $(echo "$KEY" | jq -r '.kty')"

# Build PEM: try x5c first, fallback to JWK n/e
X5C=$(echo "$KEY" | jq -r '.x5c[0] // ""')
if [[ -n "$X5C" ]]; then
    CERT_PEM="-----BEGIN CERTIFICATE-----
$(echo "$X5C" | fold -w 64)
-----END CERTIFICATE-----"
    echo "$CERT_PEM" | openssl x509 -pubkey -noout > "${TMPDIR_WORK}/pubkey.pem" 2>/dev/null
else
    JWK_N=$(echo "$KEY" | jq -r '.n')
    JWK_E=$(echo "$KEY" | jq -r '.e')
    jwk_to_pem "$JWK_N" "$JWK_E" > "${TMPDIR_WORK}/pubkey.pem"
fi

KEY_BITS=$(openssl pkey -pubin -in "${TMPDIR_WORK}/pubkey.pem" -text -noout 2>/dev/null \
    | head -1 | sed 's/[^0-9]//g')
echo "  size = ${KEY_BITS}-bit"

# --- Step 3: Compute hash ---
case "$ALG" in
    RS256) DGST_FLAG="-sha256"; HASH_BYTES=32 ;;
    RS384) DGST_FLAG="-sha384"; HASH_BYTES=48 ;;
    RS512) DGST_FLAG="-sha512"; HASH_BYTES=64 ;;
    *) echo "Unsupported algorithm: $ALG" >&2; exit 1 ;;
esac

echo -n "${H_B64}.${P_B64}" > "${TMPDIR_WORK}/signed_data"
COMPUTED_HEX=$(openssl dgst "$DGST_FLAG" -binary "${TMPDIR_WORK}/signed_data" \
    | xxd -p | tr -d '\n')

# --- Step 4: Recover hash from signature (raw RSA: sig^e mod n) ---
b64url_decode "$S_B64" > "${TMPDIR_WORK}/sig.bin"

# Raw RSA public key operation: output = sig^e mod n (PKCS#1 padded block)
openssl pkeyutl -verifyrecover \
    -inkey "${TMPDIR_WORK}/pubkey.pem" -pubin \
    -pkeyopt rsa_padding_mode:none \
    -in "${TMPDIR_WORK}/sig.bin" \
    -out "${TMPDIR_WORK}/decrypted.bin" 2>/dev/null

# The PKCS#1 v1.5 block is: 00 01 FF..FF 00 [DigestInfo] [Hash]
# The hash occupies the last HASH_BYTES of the block
RECOVERED_HEX=$(tail -c "$HASH_BYTES" "${TMPDIR_WORK}/decrypted.bin" \
    | xxd -p | tr -d '\n')

# --- Step 5: PRINT & COMPARE ---
echo -e "\n${CYAN}=== Signature Verification ===${NC}"
echo "  Algorithm: ${ALG}"
echo ""
echo -e "  ${YELLOW}Computed hash  (SHA on header.payload):${NC}"
echo "    ${COMPUTED_HEX}"
echo ""
echo -e "  ${YELLOW}Recovered hash (DECRYPT(public_key, signature)):${NC}"
echo "    ${RECOVERED_HEX}"
echo ""

if [[ "$COMPUTED_HEX" == "$RECOVERED_HEX" ]]; then
    echo -e "  ${GREEN}>>> MATCH - The IDP signed this token. Mathematical fact. <<<${NC}"
    exit 0
else
    echo -e "  ${RED}>>> MISMATCH - Signature invalid. <<<${NC}"
    exit 1
fi
