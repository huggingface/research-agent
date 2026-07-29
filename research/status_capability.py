"""Opaque, expiring capabilities for browser-only research status reads."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from time import time


@dataclass(frozen=True, slots=True)
class StatusCapability:
    job_id: str
    owner_id: str
    expires_at: float


class StatusCapabilityStore:
    def __init__(
        self,
        *,
        ttl: float = 2 * 60 * 60,
        clock: Callable[[], float] = time,
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._records: dict[str, StatusCapability] = {}

    def issue(self, job_id: str, owner_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._records[self._digest(token)] = StatusCapability(
            job_id=job_id,
            owner_id=owner_id,
            expires_at=self._clock() + self._ttl,
        )
        return token

    def resolve(self, token: str) -> StatusCapability | None:
        key = self._digest(token)
        capability = self._records.get(key)
        if capability is None:
            return None
        if capability.expires_at <= self._clock():
            self._records.pop(key, None)
            return None
        return capability

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
