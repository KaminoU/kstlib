#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
# JWT Signature Verification - Bash (curl + openssl + jq)
# ══════════════════════════════════════════════════════════════
#
# Pure shell JWT validation with cryptographic proof.
# Same 6-step chain as kstlib TokenChecker, zero Python deps.
#
# Dependencies: bash 4+, curl, openssl, jq, xxd, base64
#
# Usage:
#   ./token_check.sh                              # kstlib cached token
#   ./token_check.sh --token "eyJ..."             # explicit JWT
#   ./token_check.sh --ca-bundle /path/to/ca.pem  # custom CA
#   ./token_check.sh --verbose                    # full details
#
# Exit codes: 0 (valid), 1 (invalid), 2 (system error)
# ══════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

# ── Globals ───────────────────────────────────────────────────
VERBOSE=false
TOKEN=""
CA_BUNDLE=""
TMPDIR_WORK=""

# ── Cleanup ───────────────────────────────────────────────────
cleanup() {
    [[ -n "${TMPDIR_WORK:-}" && -d "${TMPDIR_WORK:-}" ]] && rm -rf "$TMPDIR_WORK"
}
trap cleanup EXIT

# ── Dependency check ──────────────────────────────────────────
for cmd in curl openssl jq xxd base64; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: '$cmd' is required but not found." >&2
        exit 2
    fi
done

# ── Usage ─────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: token_check.sh [OPTIONS]

Options:
  --token JWT         JWT string to validate (default: kstlib cached token)
  --ca-bundle PATH    Custom CA bundle for curl (corporate PKI)
  --verbose, -v       Show full JWT header, payload, PEM key, x509 info
  --help, -h          Show this help

Examples:
  ./token_check.sh                                    # cached token
  ./token_check.sh --token "eyJhbGci..."              # explicit JWT
  ./token_check.sh --ca-bundle /etc/pki/.../ca.pem    # corporate CA
  ./token_check.sh --verbose --ca-bundle ~/ca.pem     # full details + CA
EOF
    exit 0
}

# ── Parse args ────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)     TOKEN="$2"; shift 2 ;;
        --ca-bundle) CA_BUNDLE="$2"; shift 2 ;;
        --verbose|-v) VERBOSE=true; shift ;;
        --help|-h)   usage ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────

step_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
step_fail() { echo -e "  ${RED}✗${NC} $1"; }
info()      { echo -e "  ${DIM}$1${NC}"; }
section()   { echo -e "\n${CYAN}=== $1 ===${NC}"; }

b64url_decode() {
    local input="$1"
    input=$(echo -n "$input" | tr '_-' '/+')
    local mod=$(( ${#input} % 4 ))
    [[ $mod -eq 2 ]] && input="${input}=="
    [[ $mod -eq 3 ]] && input="${input}="
    echo -n "$input" | base64 -d 2>/dev/null
}

b64url_to_hex() {
    b64url_decode "$1" | xxd -p | tr -d '\n'
}

fetch() {
    local url="$1"
    local curl_args=(-s -f --max-time 10)
    [[ -n "$CA_BUNDLE" ]] && curl_args+=(--cacert "$CA_BUNDLE")
    curl "${curl_args[@]}" "$url"
}

# ── ASN.1 DER helpers (for JWK n/e -> PEM conversion) ────────

asn1_len() {
    local len=$1
    if (( len < 128 )); then
        printf '%02x' "$len"
    elif (( len < 256 )); then
        printf '81%02x' "$len"
    else
        printf '82%04x' "$len"
    fi
}

asn1_integer() {
    local hex="$1"
    # Ensure even-length hex string
    (( ${#hex} % 2 != 0 )) && hex="0${hex}"
    # Add leading 00 if high bit set (ASN.1 positive integer)
    local first_byte
    first_byte=$((16#${hex:0:2}))
    (( first_byte >= 128 )) && hex="00${hex}"
    local len=$(( ${#hex} / 2 ))
    printf '02%s%s' "$(asn1_len "$len")" "$hex"
}

asn1_sequence() {
    local content="$1"
    local len=$(( ${#content} / 2 ))
    printf '30%s%s' "$(asn1_len "$len")" "$content"
}

asn1_bitstring() {
    local content="$1"
    local len=$(( ${#content} / 2 + 1 ))  # +1 for unused-bits byte
    printf '03%s00%s' "$(asn1_len "$len")" "$content"
}

# JWK (n, e) -> SubjectPublicKeyInfo PEM
jwk_to_pem() {
    local n_b64url="$1" e_b64url="$2"
    local n_hex e_hex n_int e_int rsa_key bit_str spki

    n_hex=$(b64url_to_hex "$n_b64url")
    e_hex=$(b64url_to_hex "$e_b64url")

    n_int=$(asn1_integer "$n_hex")
    e_int=$(asn1_integer "$e_hex")

    # RSAPublicKey ::= SEQUENCE { modulus INTEGER, exponent INTEGER }
    rsa_key=$(asn1_sequence "${n_int}${e_int}")
    bit_str=$(asn1_bitstring "$rsa_key")

    # AlgorithmIdentifier: rsaEncryption OID (1.2.840.113549.1.1.1) + NULL
    local algo_id="300d06092a864886f70d0101010500"
    spki=$(asn1_sequence "${algo_id}${bit_str}")

    echo "-----BEGIN PUBLIC KEY-----"
    echo -n "$spki" | xxd -r -p | base64 | fold -w 64
    echo "-----END PUBLIC KEY-----"
}

# x5c certificate -> PEM public key
x5c_to_pubkey_pem() {
    local x5c_b64="$1"
    local cert_pem
    cert_pem="-----BEGIN CERTIFICATE-----
$(echo "$x5c_b64" | fold -w 64)
-----END CERTIFICATE-----"
    echo "$cert_pem" | openssl x509 -pubkey -noout 2>/dev/null
}

# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

TMPDIR_WORK=$(mktemp -d)

# ── Get JWT ───────────────────────────────────────────────────
if [[ -z "$TOKEN" ]]; then
    if command -v kstlib &>/dev/null; then
        TOKEN=$(kstlib auth token 2>/dev/null) || {
            echo "Error: Not authenticated. Run 'kstlib auth login' first, or use --token." >&2
            exit 2
        }
        echo -e "${DIM}Using cached token from kstlib${NC}"
    else
        echo "Error: No --token provided and kstlib not found in PATH." >&2
        exit 2
    fi
fi

# Strip whitespace
TOKEN=$(echo -n "$TOKEN" | tr -d '[:space:]')

# ── Step 1: Decode JWT structure ──────────────────────────────
section "Step 1: Decode JWT structure"

IFS='.' read -r HEADER_B64 PAYLOAD_B64 SIG_B64 <<< "$TOKEN"

if [[ -z "${HEADER_B64:-}" || -z "${PAYLOAD_B64:-}" || -z "${SIG_B64:-}" ]]; then
    step_fail "Invalid JWT format (expected 3 dot-separated parts)"
    exit 1
fi

HEADER_JSON=$(b64url_decode "$HEADER_B64")
PAYLOAD_JSON=$(b64url_decode "$PAYLOAD_B64")

ALG=$(echo "$HEADER_JSON" | jq -r '.alg // "unknown"')
KID=$(echo "$HEADER_JSON" | jq -r '.kid // "unknown"')
ISS=$(echo "$PAYLOAD_JSON" | jq -r '.iss // ""')

step_ok "JWT decoded: alg=${ALG}, kid=${KID}"
info "Issuer: ${ISS}"

if $VERBOSE; then
    echo -e "\n${YELLOW}Header:${NC}"
    echo "$HEADER_JSON" | jq .
    echo -e "\n${YELLOW}Payload:${NC}"
    echo "$PAYLOAD_JSON" | jq .
fi

# ── Step 2: Fetch OIDC discovery ──────────────────────────────
section "Step 2: Discover issuer"

DISCOVERY_URL="${ISS%/}/.well-known/openid-configuration"
info "GET ${DISCOVERY_URL}"

DISCOVERY=$(fetch "$DISCOVERY_URL") || {
    step_fail "Discovery failed: ${DISCOVERY_URL}"
    exit 1
}

JWKS_URI=$(echo "$DISCOVERY" | jq -r '.jwks_uri // ""')
SUPPORTED_ALGS=$(echo "$DISCOVERY" | jq -r '.id_token_signing_alg_values_supported // [] | join(", ")')

step_ok "Discovery OK"
info "JWKS URI: ${JWKS_URI}"
info "Supported algorithms: ${SUPPORTED_ALGS}"

# ── Step 3: Fetch JWKS ───────────────────────────────────────
section "Step 3: Fetch JWKS"
info "GET ${JWKS_URI}"

JWKS=$(fetch "$JWKS_URI") || {
    step_fail "JWKS fetch failed: ${JWKS_URI}"
    exit 1
}

KEY_COUNT=$(echo "$JWKS" | jq '.keys | length')
KEY_IDS=$(echo "$JWKS" | jq -r '[.keys[].kid] | join(", ")')

step_ok "JWKS fetched: ${KEY_COUNT} key(s)"
info "Key IDs: ${KEY_IDS}"

# ── Step 4: Extract public key ────────────────────────────────
section "Step 4: Extract public key (kid=${KID})"

MATCHING_KEY=$(echo "$JWKS" | jq --arg kid "$KID" '.keys[] | select(.kid == $kid)')

if [[ -z "$MATCHING_KEY" ]]; then
    step_fail "Key not found: kid='${KID}' not in [${KEY_IDS}]"
    exit 1
fi

KTY=$(echo "$MATCHING_KEY" | jq -r '.kty')
PUBKEY_PEM=""

# Try x5c first (contains full certificate, simpler extraction)
X5C=$(echo "$MATCHING_KEY" | jq -r '.x5c[0] // ""')

if [[ -n "$X5C" ]]; then
    PUBKEY_PEM=$(x5c_to_pubkey_pem "$X5C")
    info "Key source: x5c certificate"

    if $VERBOSE; then
        CERT_PEM="-----BEGIN CERTIFICATE-----
$(echo "$X5C" | fold -w 64)
-----END CERTIFICATE-----"
        echo -e "\n${YELLOW}X.509 Certificate:${NC}"
        echo "$CERT_PEM" | openssl x509 -noout -subject -issuer -dates 2>/dev/null | sed 's/^/  /'
    fi
else
    # Fallback: construct PEM from JWK (n, e) via ASN.1 DER
    JWK_N=$(echo "$MATCHING_KEY" | jq -r '.n')
    JWK_E=$(echo "$MATCHING_KEY" | jq -r '.e')
    PUBKEY_PEM=$(jwk_to_pem "$JWK_N" "$JWK_E")
    info "Key source: JWK (n, e) -> ASN.1 DER -> PEM"
fi

# Save PEM and compute fingerprint
echo "$PUBKEY_PEM" > "${TMPDIR_WORK}/pubkey.pem"
FINGERPRINT=$(openssl pkey -pubin -in "${TMPDIR_WORK}/pubkey.pem" -outform DER 2>/dev/null \
    | openssl dgst -sha256 -hex 2>/dev/null | sed 's/.*= //')
KEY_BITS=$(openssl pkey -pubin -in "${TMPDIR_WORK}/pubkey.pem" -text -noout 2>/dev/null \
    | head -1 | sed 's/[^0-9]//g')

step_ok "Public key extracted: ${KTY} ${KEY_BITS}-bit"
info "Fingerprint: SHA256:${FINGERPRINT:0:32}..."

if $VERBOSE; then
    echo -e "\n${YELLOW}Public Key PEM:${NC}"
    echo "$PUBKEY_PEM"
fi

# ── Step 5: Verify signature ─────────────────────────────────
section "Step 5: Verify signature (${ALG})"

case "$ALG" in
    RS256) DGST="-sha256" ;;
    RS384) DGST="-sha384" ;;
    RS512) DGST="-sha512" ;;
    *)
        step_fail "Unsupported algorithm: ${ALG} (only RS256/RS384/RS512)"
        exit 1
        ;;
esac

# Signed data = ASCII bytes of "header_b64.payload_b64"
echo -n "${HEADER_B64}.${PAYLOAD_B64}" > "${TMPDIR_WORK}/signed_data"
b64url_decode "$SIG_B64" > "${TMPDIR_WORK}/signature.bin"

# openssl dgst -verify does PKCS#1 v1.5 by default for RSA keys
if openssl dgst "$DGST" -verify "${TMPDIR_WORK}/pubkey.pem" \
    -signature "${TMPDIR_WORK}/signature.bin" \
    "${TMPDIR_WORK}/signed_data" &>/dev/null; then
    step_ok "Signature valid (${ALG})"
else
    step_fail "Signature INVALID"
    exit 1
fi

# ── Step 6: Validate claims ──────────────────────────────────
section "Step 6: Validate claims"

NOW=$(date +%s)
SKEW=300  # 5 minutes tolerance
ISSUES=()

# Expiration
EXP=$(echo "$PAYLOAD_JSON" | jq -r '.exp // empty')
if [[ -n "${EXP:-}" ]]; then
    if (( NOW > EXP + SKEW )); then
        ELAPSED=$(( NOW - EXP ))
        ISSUES+=("Token expired (${ELAPSED}s ago)")
    else
        REMAINING=$(( EXP - NOW ))
        info "Expires in: $(( REMAINING / 60 ))m $(( REMAINING % 60 ))s"
    fi
fi

# Issued-at (future check)
IAT=$(echo "$PAYLOAD_JSON" | jq -r '.iat // empty')
if [[ -n "${IAT:-}" ]]; then
    if (( IAT > NOW + SKEW )); then
        ISSUES+=("Token issued in the future (iat=${IAT})")
    fi
fi

# Not-before
NBF=$(echo "$PAYLOAD_JSON" | jq -r '.nbf // empty')
if [[ -n "${NBF:-}" ]]; then
    if (( NOW < NBF - SKEW )); then
        ISSUES+=("Token not yet valid (nbf=${NBF})")
    fi
fi

# Display claims
SUB=$(echo "$PAYLOAD_JSON" | jq -r '.sub // ""')
AUD=$(echo "$PAYLOAD_JSON" | jq -r 'if .aud | type == "array" then .aud | join(", ") else .aud // "" end')

[[ -n "$ISS" ]] && info "Issuer:   ${ISS}"
[[ -n "$AUD" ]] && info "Audience: ${AUD}"
[[ -n "$SUB" ]] && info "Subject:  ${SUB}"

if (( ${#ISSUES[@]} > 0 )); then
    for issue in "${ISSUES[@]}"; do
        step_fail "$issue"
    done
    exit 1
fi

step_ok "All claims valid"

# ── Summary ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  TOKEN IS VALID - Cryptographic proof verified${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "  Algorithm:   ${ALG}"
echo -e "  Key ID:      ${KID}"
echo -e "  Key Type:    ${KTY} ${KEY_BITS}-bit"
echo -e "  Fingerprint: SHA256:${FINGERPRINT:0:32}..."
echo -e "  Issuer:      ${ISS}"
echo -e "  Subject:     ${SUB}"
echo ""
echo -e "${DIM}  Verified with: curl + openssl + jq (zero Python)${NC}"
echo -e "${DIM}  Any third party can reproduce this independently.${NC}"

exit 0
