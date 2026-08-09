"""
Cert models - data structures for SSL certificate monitoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class CertWatchConfig:
    hostname:                str
    port:                    int                                                    = 443
    interval:                int                                                    = 86400
    label:                   str                                                    = ""
    warn_days_before_expiry: int                                                    = 30
    alert_on_change:         bool                                                   = True
    alert_on_expiry:         bool                                                   = True
    cooldown:                int                                                    = 0
    dry_run:                 bool                                                   = False
    webhooks:                list[str]                                              = field(default_factory=list)
    webhook_retries:         int                                                    = 3
    on_change:               Callable[[CertChangeInfo], Any] | None                = None
    on_expiry:               Callable[[CertExpiryInfo], Any] | None                = None
    on_error:                Callable[[Exception, CertWatchConfig], None] | None   = None

    def __post_init__(self) -> None:
        if not self.label:
            self.label = f"{self.hostname}:{self.port}"


@dataclass
class CertSnapshot:
    hostname:          str
    port:              int
    subject:           str
    issuer:            str
    valid_from:        datetime
    valid_to:          datetime
    days_until_expiry: int
    fingerprint:       str
    captured_at:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CertReport:
    hostname:            str
    label:               str
    snapshot:            CertSnapshot
    previous:            CertSnapshot | None
    days_until_expiry:   int
    is_expired:          bool
    is_expiring_soon:    bool
    fingerprint_changed: bool
    compared_at:         datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CertExpiryInfo:
    hostname:          str
    label:             str
    days_until_expiry: int
    valid_to:          datetime
    is_expired:        bool


@dataclass
class CertChangeInfo:
    hostname:             str
    label:                str
    previous_fingerprint: str
    current_fingerprint:  str
    previous_valid_to:    datetime
    current_valid_to:     datetime


@dataclass
class CertWatcherStatus:
    hostname:          str
    label:             str
    port:              int
    interval:          int
    paused:            bool
    last_check_at:     datetime | None
    next_check_at:     datetime | None
    last_change_at:    datetime | None
    checks_count:      int
    changes_count:     int
    errors_count:      int
    days_until_expiry: int | None
    valid_to:          datetime | None
    is_expiring_soon:  bool


def make_cert_watch_config(hostname: str, **kwargs: Any) -> CertWatchConfig:
    return CertWatchConfig(hostname=hostname, **kwargs)


__all__ = [
    "CertChangeInfo",
    "CertExpiryInfo",
    "CertReport",
    "CertSnapshot",
    "CertWatchConfig",
    "CertWatcherStatus",
    "make_cert_watch_config",
]
