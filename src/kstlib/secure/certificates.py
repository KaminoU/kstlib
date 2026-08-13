"""Bounded X.509 certificate metadata extraction.

Turns DER-encoded certificate bytes into frozen metadata. The input is treated
as hostile: it is size-bounded before any parsing, and every failure surfaces
as a typed kstlib exception instead of leaking one from the parsing backend.

The scope is deliberately narrow. This module reads a certificate that is
already in hand. It performs no network access, no chain building, no trust
store lookup, no revocation check, and it reaches no verdict: deciding that a
certificate is expired, weak, or acceptable belongs to the caller, which owns
the thresholds.

Failures are split by who is at fault. A broken call contract raises a builtin
exception (``TypeError`` for a payload that is not bytes-like, ``ValueError``
for a nonsensical bound), while a problem with the payload itself raises the
``CertificateError`` family. So the exception type already answers "is it me or
is it my data", without reading the message.

Every import of the certificate backend below sits inside a function body
rather than at module level. That is deliberate, not an oversight to tidy up:
the backend costs on the order of 25 ms to import once its files are in the OS
cache, nearer 85 ms cold, and ``-X importtime`` counts 60 ms for the transitive
tree. This module is loaded by anyone importing ``kstlib.secure``, including
code that only hashes passwords, so hoisting those imports would charge that
cost to every consumer of the package, whether or not a certificate is ever
parsed. The property is locked by a test, so undoing it fails the suite rather
than silently slowing every caller down.

Example:
    >>> from kstlib.secure import parse_certificate
    >>> info = parse_certificate(der_bytes)  # doctest: +SKIP
    >>> info.public_key_type  # doctest: +SKIP
    'ec'

"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from kstlib.config.exceptions import KstlibError
from kstlib.logging import get_logger

if TYPE_CHECKING:
    import datetime

    from cryptography import x509

log = get_logger(__name__)

__all__ = [
    "MAX_CERTIFICATE_SIZE",
    "CertificateError",
    "CertificateInfo",
    "CertificateTooLargeError",
    "InvalidCertificateError",
    "parse_certificate",
]

# Hardening: cap the accepted payload so a multi-megabyte blob cannot be used
# as a denial-of-service vector against the parser. A common certificate is 1
# to 2 KB; the largest realistic one, carrying a post-quantum key and a long
# subject alternative name list, stays around 10 KB. This leaves ample room.
MAX_CERTIFICATE_SIZE: Final = 64 * 1024  # bytes (64 KiB)


class CertificateError(KstlibError, ValueError):
    """Raised when a certificate cannot be turned into metadata."""


class CertificateTooLargeError(CertificateError):
    """Raised when the payload exceeds the accepted size limit."""


class InvalidCertificateError(CertificateError):
    """Raised when the payload is not a usable DER-encoded certificate."""


@lru_cache(maxsize=1)
def _algorithm_labels() -> tuple[dict[str, str], dict[str, str]]:
    """Return the (public key, signature) OID-to-label lookup tables.

    Both tables are keyed by dotted OID string and built from the public
    constants of the parsing backend, so a renamed constant fails loudly here
    rather than silently degrading a label. Labels are written by hand: a label
    computed from a constant name would drift on its own the day a new
    algorithm is added.

    Returns:
        Tuple of (public key labels, signature algorithm labels).

    """
    from cryptography.x509.oid import PublicKeyAlgorithmOID as PublicKey
    from cryptography.x509.oid import SignatureAlgorithmOID as Signature

    public_key = {
        PublicKey.DSA.dotted_string: "dsa",
        PublicKey.EC_PUBLIC_KEY.dotted_string: "ec",
        PublicKey.ED25519.dotted_string: "ed25519",
        PublicKey.ED448.dotted_string: "ed448",
        PublicKey.ML_DSA_44.dotted_string: "ml-dsa-44",
        PublicKey.ML_DSA_65.dotted_string: "ml-dsa-65",
        PublicKey.ML_DSA_87.dotted_string: "ml-dsa-87",
        PublicKey.ML_KEM_768.dotted_string: "ml-kem-768",
        PublicKey.ML_KEM_1024.dotted_string: "ml-kem-1024",
        PublicKey.RSAES_PKCS1_v1_5.dotted_string: "rsa",
        PublicKey.RSASSA_PSS.dotted_string: "rsa-pss",
        PublicKey.X25519.dotted_string: "x25519",
        PublicKey.X448.dotted_string: "x448",
    }
    signature = {
        Signature.DSA_WITH_SHA1.dotted_string: "dsa-with-sha1",
        Signature.DSA_WITH_SHA224.dotted_string: "dsa-with-sha224",
        Signature.DSA_WITH_SHA256.dotted_string: "dsa-with-sha256",
        Signature.DSA_WITH_SHA384.dotted_string: "dsa-with-sha384",
        Signature.DSA_WITH_SHA512.dotted_string: "dsa-with-sha512",
        Signature.ECDSA_WITH_SHA1.dotted_string: "ecdsa-with-sha1",
        Signature.ECDSA_WITH_SHA224.dotted_string: "ecdsa-with-sha224",
        Signature.ECDSA_WITH_SHA256.dotted_string: "ecdsa-with-sha256",
        Signature.ECDSA_WITH_SHA384.dotted_string: "ecdsa-with-sha384",
        Signature.ECDSA_WITH_SHA512.dotted_string: "ecdsa-with-sha512",
        Signature.ECDSA_WITH_SHA3_224.dotted_string: "ecdsa-with-sha3-224",
        Signature.ECDSA_WITH_SHA3_256.dotted_string: "ecdsa-with-sha3-256",
        Signature.ECDSA_WITH_SHA3_384.dotted_string: "ecdsa-with-sha3-384",
        Signature.ECDSA_WITH_SHA3_512.dotted_string: "ecdsa-with-sha3-512",
        Signature.ED25519.dotted_string: "ed25519",
        Signature.ED448.dotted_string: "ed448",
        Signature.GOSTR3410_2012_WITH_3411_2012_256.dotted_string: "gostr3410-2012-with-3411-2012-256",
        Signature.GOSTR3410_2012_WITH_3411_2012_512.dotted_string: "gostr3410-2012-with-3411-2012-512",
        Signature.GOSTR3411_94_WITH_3410_2001.dotted_string: "gostr3411-94-with-3410-2001",
        Signature.ML_DSA_44.dotted_string: "ml-dsa-44",
        Signature.ML_DSA_65.dotted_string: "ml-dsa-65",
        Signature.ML_DSA_87.dotted_string: "ml-dsa-87",
        Signature.RSASSA_PSS.dotted_string: "rsassa-pss",
        Signature.RSA_WITH_MD5.dotted_string: "rsa-with-md5",
        Signature.RSA_WITH_SHA1.dotted_string: "rsa-with-sha1",
        Signature.RSA_WITH_SHA224.dotted_string: "rsa-with-sha224",
        Signature.RSA_WITH_SHA256.dotted_string: "rsa-with-sha256",
        Signature.RSA_WITH_SHA384.dotted_string: "rsa-with-sha384",
        Signature.RSA_WITH_SHA512.dotted_string: "rsa-with-sha512",
        Signature.RSA_WITH_SHA3_224.dotted_string: "rsa-with-sha3-224",
        Signature.RSA_WITH_SHA3_256.dotted_string: "rsa-with-sha3-256",
        Signature.RSA_WITH_SHA3_384.dotted_string: "rsa-with-sha3-384",
        Signature.RSA_WITH_SHA3_512.dotted_string: "rsa-with-sha3-512",
        Signature.UNSIGNED.dotted_string: "unsigned",
    }
    return public_key, signature


@dataclass(frozen=True, slots=True)
class CertificateInfo:
    """Frozen metadata extracted from a single X.509 certificate.

    Hexadecimal fields (``serial_number``, ``fingerprint_sha256``) are
    lowercase, unseparated, and always an even number of digits. That shape is
    pinned: these values are meant for deduplicating a certificate seen in
    several places, and two consumers must not derive different keys from the
    same certificate.

    Attributes:
        subject_cn: Subject common name, or None when absent or not textual.
        issuer_cn: Issuer common name, or None when absent or not textual.
        serial_number: Serial as lowercase hexadecimal.
        not_before: Start of the validity window, timezone-aware UTC.
        not_after: End of the validity window, timezone-aware UTC.
        signature_algorithm: Signature algorithm label, dotted OID if unknown.
        signature_hash: Signature hash name (``sha256``), or None. None covers
            two different situations: the algorithm has no separate hash step,
            as with Ed25519, or the algorithm is not recognized at all. To tell
            them apart, read ``signature_algorithm``: a dotted OID rather than
            a label means the algorithm was not recognized.
        public_key_type: Public key algorithm label, dotted OID if unknown.
        public_key_size: Key size in bits, None for algorithms that do not
            express one and for algorithms that are not recognized. Same
            discriminant as above, on ``public_key_type``.
        fingerprint_sha256: SHA-256 of the DER encoding, lowercase hexadecimal.
        is_ca: Whether BasicConstraints asserts the CA flag. False when the
            extension is absent: RFC 5280 section 4.2.1.9 gives an absent
            extension and a non-asserted cA boolean the same consequence.

    """

    subject_cn: str | None
    issuer_cn: str | None
    serial_number: str
    not_before: datetime.datetime
    not_after: datetime.datetime
    signature_algorithm: str
    signature_hash: str | None
    public_key_type: str
    public_key_size: int | None
    fingerprint_sha256: str
    is_ca: bool


def _as_bytes(data: bytes | bytearray | memoryview) -> bytes:
    """Normalize a bytes-like payload to plain bytes.

    Args:
        data: Payload to normalize.

    Returns:
        The payload as ``bytes``.

    Raises:
        TypeError: If the payload is not bytes-like. The parsing backend would
            raise its own TypeError here; raising ours keeps the contract of
            never surfacing a backend exception.

    """
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    raise TypeError(f"certificate data must be bytes-like, got {type(data).__name__}")


def _common_name(name: x509.Name) -> str | None:
    """Return the first common name of an X.509 name, or None.

    Args:
        name: Subject or issuer name to read.

    Returns:
        The first common name when it is textual, None otherwise. A name
        attribute can legitimately carry bytes; those are reported as absent
        rather than rendered through a lossy conversion.

    """
    from cryptography.x509.oid import NameOID

    attributes = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    if not attributes:
        return None
    value = attributes[0].value
    return value if isinstance(value, str) else None


def _is_ca(certificate: x509.Certificate) -> bool:
    """Return whether the certificate asserts the BasicConstraints CA flag.

    Args:
        certificate: Loaded certificate to inspect.

    Returns:
        True when BasicConstraints is present and asserts cA, False otherwise.

    """
    from cryptography import x509 as x509_module

    try:
        extension = certificate.extensions.get_extension_for_class(x509_module.BasicConstraints)
    except x509_module.ExtensionNotFound:
        return False
    return bool(extension.value.ca)


def _extract(certificate: x509.Certificate) -> CertificateInfo:
    """Read every advertised field off a loaded certificate.

    Args:
        certificate: Loaded certificate to read.

    Returns:
        Frozen metadata for the certificate.

    Raises:
        InvalidCertificateError: If the serial number is not positive.

    """
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives import hashes

    if certificate.serial_number <= 0:
        # RFC 5280 requires a positive serial. Rendering a negative one as hex
        # would yield a leading minus sign, which is useless as a traceability
        # identifier, and the parsing backend already deprecates loading these.
        log.warning("[SECURITY] certificate rejected: serial number is not positive")
        raise InvalidCertificateError("certificate serial number is not positive")

    public_key_labels, signature_labels = _algorithm_labels()

    signature_oid = certificate.signature_algorithm_oid.dotted_string
    public_key_oid = certificate.public_key_algorithm_oid.dotted_string

    # An algorithm the backend does not know is legitimate data, not an attack:
    # a certificate can carry an algorithm newer than the installed backend.
    # Both accessors are guarded one by one, so an unknown algorithm costs the
    # derived field only, and the rest of the metadata stays readable. Guarding
    # the whole extraction instead would turn an unrecognized algorithm back
    # into something indistinguishable from a corrupt certificate.
    try:
        hash_algorithm = certificate.signature_hash_algorithm
    except UnsupportedAlgorithm:
        hash_algorithm = None

    try:
        key_size = getattr(certificate.public_key(), "key_size", None)
    except UnsupportedAlgorithm:
        key_size = None

    serial = format(certificate.serial_number, "x")

    return CertificateInfo(
        subject_cn=_common_name(certificate.subject),
        issuer_cn=_common_name(certificate.issuer),
        serial_number=serial if len(serial) % 2 == 0 else f"0{serial}",
        not_before=certificate.not_valid_before_utc,
        not_after=certificate.not_valid_after_utc,
        signature_algorithm=signature_labels.get(signature_oid, signature_oid),
        signature_hash=None if hash_algorithm is None else hash_algorithm.name,
        public_key_type=public_key_labels.get(public_key_oid, public_key_oid),
        public_key_size=key_size if isinstance(key_size, int) else None,
        fingerprint_sha256=certificate.fingerprint(hashes.SHA256()).hex(),
        is_ca=_is_ca(certificate),
    )


def parse_certificate(
    data: bytes | bytearray | memoryview,
    *,
    max_size: int = MAX_CERTIFICATE_SIZE,
) -> CertificateInfo:
    """Extract metadata from a DER-encoded X.509 certificate.

    The payload is size-checked before it reaches the parser, so an oversized
    blob costs nothing beyond the length comparison. No network access, no
    chain building, no revocation check is performed, and no verdict is
    reached: the caller owns the thresholds.

    Args:
        data: DER-encoded certificate bytes.
        max_size: Maximum accepted payload size in bytes. The limit is
            inclusive: a payload of exactly this size is parsed.

    Returns:
        Frozen metadata describing the certificate.

    Raises:
        TypeError: If *data* is not bytes-like.
        ValueError: If *max_size* is not positive. A non-positive bound would
            otherwise reject every certificate as oversized, which reads as a
            data problem while it is a wiring problem.
        CertificateTooLargeError: If the payload exceeds *max_size*.
        InvalidCertificateError: If the payload is not a usable certificate,
            including a certificate whose serial number is not positive.

    Example:
        >>> from kstlib.secure import parse_certificate
        >>> info = parse_certificate(der_bytes)  # doctest: +SKIP
        >>> info.public_key_type  # doctest: +SKIP
        'ec'

    """
    if max_size <= 0:
        # Checked before normalizing, so a nonsensical call does not first copy
        # a potentially large buffer.
        raise ValueError(f"max_size must be positive, got {max_size}")

    payload = _as_bytes(data)
    if len(payload) > max_size:
        log.warning(
            "[SECURITY] certificate rejected: %d bytes exceeds the %d byte limit",
            len(payload),
            max_size,
        )
        raise CertificateTooLargeError(f"certificate is {len(payload)} bytes, limit is {max_size}")

    from cryptography import x509 as x509_module
    from cryptography.exceptions import UnsupportedAlgorithm

    try:
        return _extract(x509_module.load_der_x509_certificate(payload))
    except CertificateError:
        # Already typed and already logged, do not wrap it a second time.
        raise
    except (ValueError, UnsupportedAlgorithm) as exc:
        # Extension parsing is lazy: a successful load does not guarantee the
        # rest is readable, so the whole extraction sits inside this guard.
        # UnsupportedAlgorithm does not derive from ValueError, hence the
        # explicit tuple. The two accessors that legitimately raise it are
        # handled field by field upstream; this arm is only a net for a site we
        # have not identified, so that no backend exception ever escapes.
        log.warning("[SECURITY] certificate rejected: %d bytes could not be parsed", len(payload))
        raise InvalidCertificateError("certificate could not be parsed") from exc
