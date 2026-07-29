from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import canonical_json


def sign_attestation(attestation: dict[str, Any], key: bytes) -> dict[str, Any]:
    if not key:
        raise ValueError("attestation key cannot be empty")
    value = dict(attestation)
    value.pop("signature", None)
    value["signature"] = hmac.new(key, canonical_json(value), hashlib.sha256).hexdigest()
    return value


def verify_attestation(attestation: dict[str, Any], key: bytes) -> bool:
    signature = attestation.get("signature")
    if not isinstance(signature, str):
        return False
    unsigned = dict(attestation)
    unsigned.pop("signature", None)
    expected = hmac.new(key, canonical_json(unsigned), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


class AuditLog:
    """Append-only HMAC chain suitable for detecting local log tampering."""

    def __init__(self, path: str | Path, key: bytes):
        if not key:
            raise ValueError("audit key cannot be empty")
        self.path = Path(path)
        self.key = key
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, fields: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            previous = "0" * 64
            if self.path.exists():
                with self.path.open("rb") as file:
                    lines = [line for line in file.read().splitlines() if line]
                if lines:
                    previous_value = json.loads(lines[-1])
                    previous = previous_value["entry_hmac"]
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "fields": fields,
                "previous_hmac": previous,
            }
            entry["entry_hmac"] = hmac.new(
                self.key, canonical_json(entry), hashlib.sha256
            ).hexdigest()
            descriptor = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
            )
            try:
                os.write(descriptor, canonical_json(entry) + b"\n")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return entry

