# -*- coding: utf-8 -*-
"""
Vault — §12.2 (Phase 4 P0)

Per-user credential container, decoupled from Agent/Session.

Design principles:
  - Write-only: after add_credential(), the raw value cannot be read back.
  - match_for_server(mcp_server_url) performs automatic credential lookup
    for MCP tool calls.
  - rotate() enables hot-update: running Sessions use the latest credential
    on the next tool call (design-by-intent: security compliance requires
    old keys to be immediately invalid — §5.5.1 design note).
  - Credentials are NEVER snapshotted into Session creation_snapshot.

Encryption:
  The Vault receives pre-encrypted values.  Encryption/decryption is handled
  by a separate EncryptionService (not part of the Vault domain model).
  In tests, plaintext values are used directly.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from vendor_runtime_sdk.runtime.vault.credential import Credential, CredentialType

logger = logging.getLogger(__name__)


class VaultError(Exception):
    """Base exception for Vault operations."""


class CredentialNotFoundError(VaultError):
    """Raised when a credential lookup finds no match."""


class Vault:
    """
    Per-user credential container — §12.2.

    In-memory implementation backed by a dict; production use injects
    a DAO for MongoDB persistence.

    Usage::

        vault = Vault(user_id="user-123", workspace_id="ws-456")
        cred_id = vault.add_credential(
            mcp_server_url="https://api.kucoin.com",
            cred_type=CredentialType.API_KEY,
            encrypted_value="enc:AES256:...",
        )
        cred = vault.match_for_server("https://api.kucoin.com")
        vault.rotate(cred_id, new_encrypted_value="enc:AES256:new...")
    """

    def __init__(
        self,
        user_id: str,
        workspace_id: str,
        dao: Optional[object] = None,
    ) -> None:
        self._user_id = user_id
        self._workspace_id = workspace_id
        self._dao = dao
        # In-memory store: credential_id → Credential
        self._credentials: Dict[str, Credential] = {}
        self._lock = threading.Lock()

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    # ── Public API (§12.2) ───────────────────────────────────────────────────

    def add_credential(
        self,
        mcp_server_url: str,
        cred_type: CredentialType,
        encrypted_value: str,
        auto_refresh: bool = False,
    ) -> str:
        """
        Add a credential — write-only (post-write, cannot read original value).

        Returns the credential_id.
        """
        cred = Credential(
            user_id=self._user_id,
            workspace_id=self._workspace_id,
            mcp_server_url=mcp_server_url,
            type=cred_type,
            encrypted_value=encrypted_value,
            auto_refresh=auto_refresh,
        )
        cred.validate()
        with self._lock:
            self._credentials[cred.credential_id] = cred
        logger.debug(
            "Vault[%s]: added credential %s for %s (type=%s)",
            self._user_id, cred.credential_id, mcp_server_url, cred_type.value,
        )
        return cred.credential_id

    def match_for_server(self, mcp_server_url: str) -> Optional[Credential]:
        """
        Automatically match a credential for the given MCP server URL.

        Returns the most recently updated credential matching the URL,
        or None if no match exists.
        """
        with self._lock:
            matches = [
                c for c in self._credentials.values()
                if c.mcp_server_url == mcp_server_url
            ]
        if not matches:
            return None
        # Return the most recently updated credential
        return max(matches, key=lambda c: c.updated_at)

    def rotate(self, credential_id: str, new_encrypted_value: str) -> None:
        """
        Hot-update a credential value.

        Running Sessions use the latest value on their next tool call.
        Design-by-intent: security compliance requires old keys to be
        immediately invalid (§5.5.1, §12.2).
        """
        with self._lock:
            cred = self._credentials.get(credential_id)
            if cred is None:
                raise CredentialNotFoundError(
                    f"Credential '{credential_id}' not found in vault for user '{self._user_id}'"
                )
            cred.encrypted_value = new_encrypted_value
            cred.updated_at = time.time()
            cred.rotated_at = time.time()
        logger.info(
            "Vault[%s]: rotated credential %s (fingerprint=%s)",
            self._user_id, credential_id, cred.value_fingerprint,
        )

    def get_credential(self, credential_id: str) -> Optional[Credential]:
        """Retrieve credential metadata (for internal use, e.g., DAO sync)."""
        with self._lock:
            return self._credentials.get(credential_id)

    def list_credentials(self) -> List[Credential]:
        """List all credentials for this user (metadata only; values are write-only)."""
        with self._lock:
            return list(self._credentials.values())

    def remove_credential(self, credential_id: str) -> bool:
        """Remove a credential. Returns True if found and removed."""
        with self._lock:
            return self._credentials.pop(credential_id, None) is not None
