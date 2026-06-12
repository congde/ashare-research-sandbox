# -*- coding: utf-8 -*-
"""
Credential — §12.2 (Phase 4 P0)

Per-user credential bound to a specific MCP server URL.

Design principles:
  - Credentials are write-only: once stored, the raw value cannot be read
    back through the API (only the encrypted form exists in storage).
  - Credentials are NOT snapshotted into Sessions — they are always fetched
    live from the Vault at tool-call time (§5.5.1 design note: security
    compliance requires immediate key rotation propagation).
  - auto_refresh flag enables OAuth token refresh for applicable types.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class CredentialType(str, Enum):
    OAUTH = "oauth"
    BEARER = "bearer"
    API_KEY = "api_key"


@dataclass
class Credential:
    """
    Per-user secret credential for an MCP server.

    Maps to MongoDB `vault_credentials` collection.
    """

    credential_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str = ""
    workspace_id: str = ""
    mcp_server_url: str = ""
    type: CredentialType = CredentialType.API_KEY
    encrypted_value: str = ""  # stored encrypted; never returned to API callers
    auto_refresh: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    rotated_at: Optional[float] = None

    # ── Validation ───────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Raise ValueError if required fields are missing."""
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.workspace_id:
            raise ValueError("workspace_id is required")
        if not self.mcp_server_url:
            raise ValueError("mcp_server_url is required")
        if not self.encrypted_value:
            raise ValueError("encrypted_value is required")
        if not self.encrypted_value.startswith(("enc:", "vault:")):
            import logging
            logging.getLogger(__name__).warning(
                "Credential %s: encrypted_value does not start with 'enc:' or 'vault:' prefix. "
                "Raw plaintext credentials should NEVER be stored. "
                "Use EncryptionService to encrypt before calling add_credential().",
                self.credential_id,
            )

    @property
    def value_fingerprint(self) -> str:
        """sha256 fingerprint of the encrypted value for audit logging."""
        return hashlib.sha256(self.encrypted_value.encode()).hexdigest()[:16]

    # ── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to MongoDB document."""
        return {
            "_id": self.credential_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "mcp_server_url": self.mcp_server_url,
            "type": self.type.value,
            "encrypted_value": self.encrypted_value,
            "auto_refresh": self.auto_refresh,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rotated_at": self.rotated_at,
        }

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize for API responses — value is NEVER included (write-only)."""
        return {
            "credential_id": self.credential_id,
            "user_id": self.user_id,
            "mcp_server_url": self.mcp_server_url,
            "type": self.type.value,
            "auto_refresh": self.auto_refresh,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rotated_at": self.rotated_at,
            "value_fingerprint": self.value_fingerprint,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Credential:
        """Deserialize from MongoDB document."""
        return cls(
            credential_id=str(d.get("_id", d.get("credential_id", ""))),
            user_id=d.get("user_id", ""),
            workspace_id=d.get("workspace_id", ""),
            mcp_server_url=d.get("mcp_server_url", ""),
            type=CredentialType(d.get("type", "api_key")),
            encrypted_value=d.get("encrypted_value", ""),
            auto_refresh=d.get("auto_refresh", False),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            rotated_at=d.get("rotated_at"),
        )
