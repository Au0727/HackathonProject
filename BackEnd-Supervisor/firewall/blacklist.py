"""The user's merchant blacklist.

Blacklisted merchants are stored as plain structured ids and matched by exact
string equality on ``merchantId``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator

__all__ = ["BlacklistStore", "BlacklistError"]


class BlacklistError(ValueError):
    """Raised when blacklist data is unreadable or malformed.

    A malformed blacklist fails loudly: silently continuing with an empty
    blacklist could authorize a merchant the user explicitly blocked.
    """


class BlacklistStore:
    """In-memory blacklist with optional JSON persistence."""

    def __init__(
        self,
        merchant_ids: Iterable[str] = (),
        path: str | Path | None = None,
    ) -> None:
        self._path = Path(path) if path is not None else None
        self._merchants: set[str] = set()
        for merchant_id in merchant_ids:
            self._merchants.add(self._validate_id(merchant_id))
        if self._path is not None and self._path.exists():
            for merchant_id in self._read_file(self._path):
                self._merchants.add(self._validate_id(merchant_id))

    # -- inspection ------------------------------------------------------
    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def merchants(self) -> tuple[str, ...]:
        """Sorted tuple: deterministic order for audits and tests."""

        return tuple(sorted(self._merchants))

    def contains(self, merchant_id: str) -> bool:
        return merchant_id in self._merchants

    def __len__(self) -> int:
        return len(self._merchants)

    def __iter__(self) -> Iterator[str]:
        return iter(self.merchants)

    # -- mutation --------------------------------------------------------
    def add(self, merchant_id: str, persist: bool = True) -> bool:
        """Add a merchant. Returns True when it was not already listed."""

        validated = self._validate_id(merchant_id)
        if validated in self._merchants:
            return False
        self._merchants.add(validated)
        if persist and self._path is not None:
            self._write_file(self._path)
        return True

    # -- internals -------------------------------------------------------
    @staticmethod
    def _validate_id(merchant_id: object) -> str:
        if not isinstance(merchant_id, str) or not merchant_id.strip():
            raise BlacklistError("A blacklist entry must be a non-empty merchant id string.")
        return merchant_id

    @staticmethod
    def _read_file(path: Path) -> list[str]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BlacklistError(f"Could not read the blacklist file {path}: {error}") from error
        if isinstance(raw, dict):
            raw = raw.get("blacklistedMerchants", raw.get("blacklisted_merchants"))
        if not isinstance(raw, list):
            raise BlacklistError(
                f"Blacklist file {path} must contain a list of merchant ids."
            )
        return [str(entry) for entry in raw]

    def _write_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"blacklistedMerchants": list(self.merchants)}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
