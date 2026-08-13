"""Tests for kstlib.secure.certificates (bounded X.509 metadata extraction)."""

from __future__ import annotations

import datetime
import subprocess
import sys

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed448, ed25519, mldsa, rsa
from cryptography.x509.oid import NameOID

from kstlib.config.exceptions import KstlibError
from kstlib.secure import (
    MAX_CERTIFICATE_SIZE,
    CertificateError,
    CertificateInfo,
    CertificateTooLargeError,
    InvalidCertificateError,
    parse_certificate,
)

NOT_BEFORE = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
NOT_AFTER = NOT_BEFORE + datetime.timedelta(days=30)

# Key types that sign without a separate hash step: the builder rejects a hash
# algorithm for these. Only the types this file actually builds are listed.
HASHLESS_KEY_TYPES = (
    ed25519.Ed25519PrivateKey,
    ed448.Ed448PrivateKey,
    mldsa.MLDSA44PrivateKey,
    mldsa.MLDSA65PrivateKey,
    mldsa.MLDSA87PrivateKey,
)


def make_name(common_name: str | None) -> x509.Name:
    """Build an X.509 name, optionally without any common name attribute."""
    if common_name is None:
        return x509.Name([])
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def build_der(
    signing_key: object,
    public_key: object,
    *,
    subject: str | None = "example.test",
    issuer: str | None = "example.test",
    serial: int = 1234567890,
    ca: bool | None = None,
    hash_algorithm: hashes.HashAlgorithm | None = None,
    extra_common_name: str | None = None,
) -> bytes:
    """Build a self-issued certificate and return its DER encoding."""
    subject_name = make_name(subject)
    if extra_common_name is not None:
        subject_name = x509.Name([*subject_name, x509.NameAttribute(NameOID.COMMON_NAME, extra_common_name)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(make_name(issuer))
        .public_key(public_key)  # type: ignore[arg-type] # reason: exercised across key types
        .serial_number(serial)
        .not_valid_before(NOT_BEFORE)
        .not_valid_after(NOT_AFTER)
    )
    if ca is not None:
        builder = builder.add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    hashless = isinstance(signing_key, HASHLESS_KEY_TYPES)
    algorithm = None if hashless else (hash_algorithm or hashes.SHA256())
    certificate = builder.sign(signing_key, algorithm)  # type: ignore[arg-type] # reason: idem
    return certificate.public_bytes(serialization.Encoding.DER)


def negative_serial_der(signing_key: ec.EllipticCurvePrivateKey) -> bytes:
    """Build DER whose serial parses as negative.

    The builder refuses a non-positive serial, so the value is patched in the
    encoded form instead. DER pads a leading 0x00 onto an integer whose top bit
    is set; raising that pad byte to 0x80 keeps the length identical and makes
    the value two's-complement negative, which is what a hostile certificate
    would carry.
    """
    der = bytearray(build_der(signing_key, signing_key.public_key(), serial=0xFF11223344556677))
    marker = bytes.fromhex("020900FF11223344556677")
    offset = der.find(marker)
    assert offset != -1, "serial INTEGER not found, the fixture assumption broke"
    der[offset + 2] = 0x80
    return bytes(der)


@pytest.fixture(scope="module")
def ec_key() -> ec.EllipticCurvePrivateKey:
    """Reusable P-256 key, three orders of magnitude cheaper than RSA keygen."""
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="module")
def ec_der(ec_key: ec.EllipticCurvePrivateKey) -> bytes:
    """DER bytes of a plain EC end-entity certificate."""
    return build_der(ec_key, ec_key.public_key())


class TestParseCertificateNominal:
    """Happy path: every advertised field is populated from a real certificate."""

    def test_returns_certificate_info(self, ec_der: bytes) -> None:
        """Parsing valid DER yields a CertificateInfo instance."""
        assert isinstance(parse_certificate(ec_der), CertificateInfo)

    def test_common_names(self, ec_der: bytes) -> None:
        """Subject and issuer common names are extracted as plain strings."""
        info = parse_certificate(ec_der)
        assert info.subject_cn == "example.test"
        assert info.issuer_cn == "example.test"

    def test_validity_window_is_timezone_aware(self, ec_der: bytes) -> None:
        """Validity bounds are timezone-aware UTC datetimes, never naive."""
        info = parse_certificate(ec_der)
        assert info.not_before == NOT_BEFORE
        assert info.not_after == NOT_AFTER
        assert info.not_before.tzinfo is not None
        assert info.not_after.tzinfo is not None

    def test_serial_number_is_lowercase_even_length_hex(self, ec_der: bytes) -> None:
        """The serial is rendered as lowercase hex with an even digit count."""
        info = parse_certificate(ec_der)
        assert info.serial_number == "499602d2"
        assert len(info.serial_number) % 2 == 0

    def test_fingerprint_matches_sha256_of_der(self, ec_der: bytes) -> None:
        """The fingerprint is the lowercase hex SHA-256 of the DER bytes."""
        expected = x509.load_der_x509_certificate(ec_der).fingerprint(hashes.SHA256()).hex()
        info = parse_certificate(ec_der)
        assert info.fingerprint_sha256 == expected
        assert len(info.fingerprint_sha256) == 64

    def test_algorithm_labels(self, ec_der: bytes) -> None:
        """Signature and key algorithms resolve to stable lowercase labels."""
        info = parse_certificate(ec_der)
        assert info.signature_algorithm == "ecdsa-with-sha256"
        assert info.signature_hash == "sha256"
        assert info.public_key_type == "ec"

    def test_public_key_size(self, ec_der: bytes) -> None:
        """A P-256 key reports its size in bits."""
        assert parse_certificate(ec_der).public_key_size == 256

    def test_is_ca_defaults_to_false(self, ec_der: bytes) -> None:
        """A certificate without BasicConstraints is not a CA."""
        assert parse_certificate(ec_der).is_ca is False

    def test_result_is_frozen(self, ec_der: bytes) -> None:
        """CertificateInfo is immutable, so callers cannot corrupt shared metadata."""
        info = parse_certificate(ec_der)
        with pytest.raises((AttributeError, TypeError)):
            info.subject_cn = "tampered"  # type: ignore[misc] # reason: asserting immutability

    def test_is_deterministic(self, ec_der: bytes) -> None:
        """The same bytes always produce the same metadata."""
        assert parse_certificate(ec_der) == parse_certificate(ec_der)


class TestSizeBound:
    """The payload is bounded before any parsing happens."""

    def test_default_bound_is_64_kib(self) -> None:
        """The shipped bound leaves headroom over the largest realistic certificate."""
        assert MAX_CERTIFICATE_SIZE == 64 * 1024

    def test_payload_at_the_bound_is_accepted(self, ec_der: bytes) -> None:
        """A payload exactly at the limit is parsed, the bound is inclusive."""
        assert parse_certificate(ec_der, max_size=len(ec_der)).subject_cn == "example.test"

    def test_payload_over_the_bound_is_rejected(self, ec_der: bytes) -> None:
        """One byte over the limit is refused."""
        with pytest.raises(CertificateTooLargeError):
            parse_certificate(ec_der, max_size=len(ec_der) - 1)

    def test_oversized_blob_is_rejected_without_parsing(self) -> None:
        """A giant blob is refused on size alone, never handed to the parser."""
        with pytest.raises(CertificateTooLargeError):
            parse_certificate(b"\x00" * (MAX_CERTIFICATE_SIZE + 1))


class TestInvalidInput:
    """Hostile or wrongly typed input surfaces as a typed kstlib error."""

    def test_malformed_der_raises_typed_error(self) -> None:
        """Bytes that are not a certificate raise InvalidCertificateError."""
        with pytest.raises(InvalidCertificateError):
            parse_certificate(b"\x30\x82\xde\xad\xbe\xef")

    def test_non_bytes_input_raises_type_error(self) -> None:
        """A wrongly typed payload raises TypeError, not a backend exception."""
        with pytest.raises(TypeError):
            parse_certificate("not bytes")  # type: ignore[arg-type] # reason: asserting the guard

    def test_buffer_types_are_accepted(self, ec_der: bytes) -> None:
        """bytearray and memoryview are normalized instead of leaking a TypeError."""
        expected = parse_certificate(ec_der)
        assert parse_certificate(bytearray(ec_der)) == expected
        assert parse_certificate(memoryview(ec_der)) == expected

    def test_non_positive_serial_is_rejected(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """A serial that parses as negative is refused rather than rendered."""
        with pytest.raises(InvalidCertificateError):
            parse_certificate(negative_serial_der(ec_key))


class TestExceptionContract:
    """The typed errors slot into the kstlib hierarchy as documented."""

    def test_errors_derive_from_kstlib_and_value_error(self) -> None:
        """Both failure modes are catchable as KstlibError and as ValueError."""
        assert issubclass(CertificateError, KstlibError)
        assert issubclass(CertificateError, ValueError)
        assert issubclass(CertificateTooLargeError, CertificateError)
        assert issubclass(InvalidCertificateError, CertificateError)

    def test_failure_modes_are_distinguishable(self, ec_der: bytes) -> None:
        """An oversized blob and a corrupt certificate are not the same error."""
        with pytest.raises(CertificateTooLargeError):
            parse_certificate(ec_der, max_size=1)
        with pytest.raises(InvalidCertificateError):
            parse_certificate(b"\x00\x01\x02\x03")


class TestBasicConstraints:
    """is_ca reflects the asserted CA flag, with absence treated as not a CA."""

    def test_ca_flag_asserted(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """An asserted cA boolean is reported as True."""
        der = build_der(ec_key, ec_key.public_key(), ca=True)
        assert parse_certificate(der).is_ca is True

    def test_ca_flag_present_but_not_asserted(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """A present but non-asserted cA boolean is reported as False."""
        der = build_der(ec_key, ec_key.public_key(), ca=False)
        assert parse_certificate(der).is_ca is False


class TestNameHandling:
    """Common names are optional and may repeat."""

    def test_missing_common_names_are_none(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """A certificate with no common name reports None, not an empty string."""
        der = build_der(ec_key, ec_key.public_key(), subject=None, issuer=None)
        info = parse_certificate(der)
        assert info.subject_cn is None
        assert info.issuer_cn is None

    def test_first_common_name_wins(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """When several common names are present, the first one is reported."""
        der = build_der(ec_key, ec_key.public_key(), extra_common_name="second.test")
        assert parse_certificate(der).subject_cn == "example.test"


class TestKeyTypeVariants:
    """Algorithm labels and key size adapt to the key actually carried."""

    def test_rsa_certificate(self) -> None:
        """An RSA certificate reports its label and its key size in bits."""
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        info = parse_certificate(build_der(key, key.public_key()))
        assert info.public_key_type == "rsa"
        assert info.public_key_size == 2048
        assert info.signature_algorithm == "rsa-with-sha256"
        assert info.signature_hash == "sha256"

    def test_ed25519_certificate_has_no_hash_and_no_key_size(self) -> None:
        """Ed25519 signs without a separate hash and exposes no key size."""
        key = ed25519.Ed25519PrivateKey.generate()
        info = parse_certificate(build_der(key, key.public_key()))
        assert info.public_key_type == "ed25519"
        assert info.signature_algorithm == "ed25519"
        assert info.signature_hash is None
        assert info.public_key_size is None


class TestImportCost:
    """The parsing backend stays out of the import path until it is needed."""

    def test_importing_secure_does_not_import_cryptography(self) -> None:
        """Importing kstlib.secure must not pull the parsing backend in."""
        probe = "import sys, kstlib.secure; print('cryptography' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "False"


# ---------------------------------------------------------------------------
# Adversarial fixtures.
#
# Several cases below cannot be produced by the certificate builder, which
# refuses to emit them: a non-positive serial, a weak signature algorithm, an
# unknown algorithm OID. They are produced by patching the encoded form
# instead, always at constant length so the enclosing structures stay
# consistent. The resulting certificates carry a signature that no longer
# matches their content. That is irrelevant here and deliberately so: this
# primitive reads metadata and verifies no signature. None of these fixtures is
# a valid certificate, and none should be used as one.
# ---------------------------------------------------------------------------

# Both OIDs encode to 11 bytes, so one can replace the other in place.
SHA256_RSA_OID = bytes.fromhex("06092A864886F70D01010B")
SHA1_RSA_OID = bytes.fromhex("06092A864886F70D010105")
# 1.2.840.113549.1.1.99, unassigned, same length as its neighbours above.
UNKNOWN_SIG_OID = bytes.fromhex("06092A864886F70D010163")
# id-ecPublicKey and an unassigned sibling, both 9 bytes.
EC_PUBLIC_KEY_OID = bytes.fromhex("06072A8648CE3D0201")
UNKNOWN_KEY_OID = bytes.fromhex("06072A8648CE3D0263")
# tbsCertificate opens with [0] { INTEGER 2 }, so the serial TLV follows it.
VERSION_V3_PREFIX = bytes.fromhex("A003020102")
# BasicConstraints(ca=True) encodes as SEQUENCE { BOOLEAN TRUE }.
BASIC_CONSTRAINTS_TRUE = bytes.fromhex("30030101FF")


def zero_serial_der(signing_key: ec.EllipticCurvePrivateKey) -> bytes:
    """Build DER whose serial parses as exactly zero.

    A serial of 0 encodes as a single content byte, so it is reachable by
    patching a one-byte serial in place. Rewriting a longer serial would change
    the length and break every enclosing structure.
    """
    der = bytearray(build_der(signing_key, signing_key.public_key(), serial=1))
    offset = der.find(VERSION_V3_PREFIX)
    assert offset != -1, "version prefix not found, the fixture assumption broke"
    serial_content = offset + len(VERSION_V3_PREFIX) + 2
    assert bytes(der[offset + 5 : offset + 8]) == bytes.fromhex("020101"), "serial TLV not where expected"
    der[serial_content] = 0x00
    return bytes(der)


def corrupt_extension_der(signing_key: ec.EllipticCurvePrivateKey) -> bytes:
    """Build DER that loads cleanly but whose extensions cannot be read.

    DER allows a BOOLEAN to hold only 0x00 or 0xFF. Setting it to 0x01 keeps
    the certificate loadable, because extensions are parsed lazily, and makes
    the extension itself fail on access.
    """
    der = bytearray(build_der(signing_key, signing_key.public_key(), ca=True))
    offset = der.find(BASIC_CONSTRAINTS_TRUE)
    assert offset != -1, "BasicConstraints not found, the fixture assumption broke"
    der[offset + 4] = 0x01
    return bytes(der)


def replace_oid(der: bytes, old: bytes, new: bytes) -> bytes:
    """Swap one OID encoding for another of the same length."""
    assert len(old) == len(new), "OID replacement must preserve length"
    assert old in der, "OID to replace not found in the certificate"
    return der.replace(old, new)


def oversized_der(signing_key: ec.EllipticCurvePrivateKey) -> bytes:
    """Build a certificate larger than the default bound, via many attributes."""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"cn{i}") for i in range(2000)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(signing_key.public_key())
        .serial_number(4242)
        .not_valid_before(NOT_BEFORE)
        .not_valid_after(NOT_AFTER)
        .sign(signing_key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.DER)


@pytest.fixture(scope="module")
def rsa_der() -> bytes:
    """DER of an RSA certificate: the RSA signature OIDs are patchable in place."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return build_der(key, key.public_key())


class TestLooksLikeACertificate:
    """Payloads a consumer really does hand over by mistake."""

    def test_pem_passed_as_der(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """A PEM file passed where DER is expected is refused, not half-read."""
        certificate = x509.load_der_x509_certificate(build_der(ec_key, ec_key.public_key()))
        pem = certificate.public_bytes(serialization.Encoding.PEM)
        with pytest.raises(InvalidCertificateError):
            parse_certificate(pem)

    def test_truncated_payload(self, ec_der: bytes) -> None:
        """A certificate cut short, as a partial read would produce, is refused."""
        with pytest.raises(InvalidCertificateError):
            parse_certificate(ec_der[:-1])

    def test_trailing_bytes_after_a_valid_certificate(self, ec_der: bytes) -> None:
        """Extra bytes after a valid structure are refused, never silently ignored."""
        with pytest.raises(InvalidCertificateError):
            parse_certificate(ec_der + b"\xff\xff")

    def test_empty_payload(self) -> None:
        """An empty attribute value is refused like any other malformed payload."""
        with pytest.raises(InvalidCertificateError):
            parse_certificate(b"")


class TestValidLoadHostileContent:
    """Payloads that load cleanly and only then turn out to be unusable."""

    def test_unreadable_extension(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """A load that succeeds is not treated as a parse that succeeded."""
        with pytest.raises(InvalidCertificateError):
            parse_certificate(corrupt_extension_der(ec_key))

    def test_zero_serial(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """A serial of exactly zero is refused, so the guard is not merely `< 0`."""
        with pytest.raises(InvalidCertificateError):
            parse_certificate(zero_serial_der(ec_key))


class TestBoundArguments:
    """The bound can be moved, but not to a value that makes it meaningless."""

    def test_bound_can_be_raised_above_the_default(self, ec_key: ec.EllipticCurvePrivateKey) -> None:
        """A certificate over the default bound parses when the caller raises it."""
        der = oversized_der(ec_key)
        assert len(der) > MAX_CERTIFICATE_SIZE
        with pytest.raises(CertificateTooLargeError):
            parse_certificate(der)
        assert parse_certificate(der, max_size=len(der)).subject_cn == "cn0"

    @pytest.mark.parametrize("bound", [0, -1, -4096])
    def test_non_positive_bound_is_a_call_error(self, ec_der: bytes, bound: int) -> None:
        """A meaningless bound fails at the call site, not as a data verdict."""
        with pytest.raises(ValueError) as excinfo:
            parse_certificate(ec_der, max_size=bound)
        assert not isinstance(excinfo.value, CertificateError)


class TestInputContract:
    """The payload guard is driven by type, not by luck."""

    @pytest.mark.parametrize("payload", [42, 3.14, ["der"], None, {"der": 1}])
    def test_non_bytes_like_payloads(self, payload: object) -> None:
        """Anything that is not bytes-like raises our TypeError, not the backend's."""
        with pytest.raises(TypeError, match="bytes-like"):
            parse_certificate(payload)  # type: ignore[arg-type] # reason: asserting the guard


class TestAlgorithmCoverage:
    """Every branch of the label tables that can be produced is produced."""

    def test_ed448(self) -> None:
        """Ed448 resolves its label and reports no hash and no key size."""
        key = ed448.Ed448PrivateKey.generate()
        info = parse_certificate(build_der(key, key.public_key()))
        assert info.public_key_type == "ed448"
        assert info.signature_algorithm == "ed448"
        assert info.signature_hash is None
        assert info.public_key_size is None

    def test_post_quantum_ml_dsa(self) -> None:
        """A post-quantum algorithm resolves, which an isinstance chain would miss."""
        key = mldsa.MLDSA44PrivateKey.generate()
        info = parse_certificate(build_der(key, key.public_key()))
        assert info.public_key_type == "ml-dsa-44"
        assert info.signature_algorithm == "ml-dsa-44"
        assert info.public_key_size is None

    def test_weak_signature_hash_is_reported(self, rsa_der: bytes) -> None:
        """A SHA-1 signature is reported as such, which is the point of the field."""
        info = parse_certificate(replace_oid(rsa_der, SHA256_RSA_OID, SHA1_RSA_OID))
        assert info.signature_algorithm == "rsa-with-sha1"
        assert info.signature_hash == "sha1"


class TestUnknownAlgorithms:
    """An unrecognized algorithm is described, not confused with corruption."""

    def test_unknown_signature_oid(self, rsa_der: bytes) -> None:
        """An unknown signature OID falls back to its dotted form, rest intact."""
        info = parse_certificate(replace_oid(rsa_der, SHA256_RSA_OID, UNKNOWN_SIG_OID))
        assert info.signature_algorithm == "1.2.840.113549.1.1.99"
        assert info.signature_hash is None
        assert info.subject_cn == "example.test"
        assert info.public_key_type == "rsa"
        assert info.public_key_size == 2048

    def test_unknown_public_key_oid(self, ec_der: bytes) -> None:
        """An unknown key OID falls back to its dotted form, rest intact."""
        info = parse_certificate(replace_oid(ec_der, EC_PUBLIC_KEY_OID, UNKNOWN_KEY_OID))
        assert info.public_key_type == "1.2.840.10045.2.99"
        assert info.public_key_size is None
        assert info.subject_cn == "example.test"
        assert info.not_before == NOT_BEFORE
        assert len(info.fingerprint_sha256) == 64
