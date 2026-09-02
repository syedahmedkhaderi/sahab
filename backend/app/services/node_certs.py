"""A very small certificate authority for the cluster's Docker control channel.

The manager signs three kinds of certificate, all from one CA that lives in
``NODE_PKI_DIR`` (bind-mounted rw into the backend, ro into JupyterHub):

* a **server** cert for each node's dockerd, so ``tcp://<node>:2376`` is mTLS;
* one long-lived **client** cert the spawner and the health probe present;
* a **server** cert for the private registry, so nodes pull images over TLS
  without an ``insecure-registries`` entry.

Doing our own PKI is a real cost, but it buys the two things a public CA cannot:
certificates for bare private IPs, and no dependency on the node being reachable
from the internet.

Everything here is filesystem-level and synchronous; call it from a thread if it
ever lands on a hot path (it does not — certificates are issued once per node).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.config import get_settings

logger = logging.getLogger(__name__)

CA_VALID_DAYS = 3650
LEAF_VALID_DAYS = 825  # the longest most tooling will accept without complaint
_KEY_SIZE = 2048


class PkiError(Exception):
    """The CA is missing or unusable."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def pki_dir() -> Path:
    return Path(get_settings().node_pki_dir)


def ca_cert_path() -> Path:
    return pki_dir() / "ca.crt"


def ca_key_path() -> Path:
    return pki_dir() / "ca.key"


def client_cert_path() -> Path:
    return pki_dir() / "client.crt"


def client_key_path() -> Path:
    return pki_dir() / "client.key"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _write_secret(path: Path, data: bytes) -> None:
    """Write a private key with 0600 before any content reaches the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _write_public(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o644)


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)


def _key_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sahab"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def _san_entries(names: list[str]) -> list[x509.GeneralName]:
    """Split a mixed list of IPs and hostnames into the right SAN types.

    dockerd is verified by IP as often as by name, and an IP that lands in a DNS
    SAN is silently ignored by OpenSSL — so the split has to be right.
    """
    entries: list[x509.GeneralName] = []
    for raw in names:
        value = (raw or "").strip()
        if not value:
            continue
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            entries.append(x509.DNSName(value))
    return entries


# ---------------------------------------------------------------------------
# CA
# ---------------------------------------------------------------------------

def ensure_ca() -> tuple[Path, Path]:
    """Create the CA if it does not exist yet. Idempotent.

    bootstrap.sh normally creates it, but the backend creates it too so a dev
    machine or a partially-provisioned host still works.
    """
    cert_path, key_path = ca_cert_path(), ca_key_path()
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    key = _new_key()
    subject = _name("Sahab Node CA")
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=CA_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    _write_secret(key_path, _key_pem(key))
    _write_public(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Generated Sahab node CA at %s", cert_path)
    return cert_path, key_path


def _load_ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    ensure_ca()
    try:
        cert = x509.load_pem_x509_certificate(ca_cert_path().read_bytes())
        key = serialization.load_pem_private_key(ca_key_path().read_bytes(), password=None)
    except (OSError, ValueError) as exc:
        raise PkiError(f"Cannot load the node CA from {pki_dir()}: {exc}") from exc
    return cert, key  # type: ignore[return-value]


def ca_cert_pem() -> str:
    ensure_ca()
    return ca_cert_path().read_text()


# ---------------------------------------------------------------------------
# Leaf certificates
# ---------------------------------------------------------------------------

def _issue(common_name: str, sans: list[str], *, server: bool) -> tuple[str, str]:
    ca_cert, ca_key = _load_ca()
    key = _new_key()
    now = dt.datetime.now(dt.timezone.utc)

    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=LEAF_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage(
                [x509.ExtendedKeyUsageOID.SERVER_AUTH]
                if server
                else [x509.ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
    )
    entries = _san_entries(sans)
    if entries:
        builder = builder.add_extension(x509.SubjectAlternativeName(entries), critical=False)

    cert = builder.sign(ca_key, hashes.SHA256())
    return (
        cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        _key_pem(key).decode("ascii"),
    )


def issue_server_cert(common_name: str, sans: list[str]) -> tuple[str, str]:
    """Issue a dockerd/registry server certificate. Returns (cert_pem, key_pem)."""
    return _issue(common_name, sans, server=True)


def ensure_client_cert() -> tuple[str, str]:
    """Return the cluster's client certificate, creating it on first use.

    One shared client identity is deliberate: every node trusts the same CA, and
    a per-caller identity would buy nothing while multiplying the ways an expiry
    can take the cluster down.
    """
    if client_cert_path().exists() and client_key_path().exists():
        return client_cert_path().read_text(), client_key_path().read_text()

    cert_pem, key_pem = _issue("sahab-control-plane", [], server=False)
    _write_secret(client_key_path(), key_pem.encode("ascii"))
    _write_public(client_cert_path(), cert_pem.encode("ascii"))
    logger.info("Issued Sahab control-plane client certificate")
    return cert_pem, key_pem
