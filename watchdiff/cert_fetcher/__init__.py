"""
CertFetcher - retrieves SSL certificate info using stdlib ssl + socket.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
from datetime import datetime, timezone

from watchdiff.cert_models import CertSnapshot, CertWatchConfig


def fetch_cert(config: CertWatchConfig) -> CertSnapshot:
    ctx = ssl.create_default_context()
    with socket.create_connection((config.hostname, config.port), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=config.hostname) as ssock:
            der_cert = ssock.getpeercert(binary_form=True)
            cert     = ssock.getpeercert()

    if der_cert is None or cert is None:
        raise RuntimeError(f"No certificate returned for {config.hostname}:{config.port}")

    fingerprint = hashlib.sha256(der_cert).hexdigest()

    not_before = datetime.strptime(cert["notBefore"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    not_after  = datetime.strptime(cert["notAfter"],  "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    days_until_expiry = (not_after - datetime.now(timezone.utc)).days

    return CertSnapshot(
        hostname          = config.hostname,
        port              = config.port,
        subject           = _get_cn(cert.get("subject", ())),
        issuer            = _get_cn(cert.get("issuer", ())),
        valid_from        = not_before,
        valid_to          = not_after,
        days_until_expiry = days_until_expiry,
        fingerprint       = fingerprint,
    )


def _get_cn(rdns: tuple) -> str:  # type: ignore[type-arg]
    for rdn in rdns:
        for attr in rdn:
            if attr[0] == "commonName":
                return str(attr[1])
    return str(rdns)


__all__ = ["fetch_cert"]
