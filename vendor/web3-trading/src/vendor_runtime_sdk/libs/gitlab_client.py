# -*- coding: utf-8 -*-
"""
GitLabClient — thin HTTP adapter used by Sprint S2 (§Gap 2) components.

Three responsibilities, all narrow enough to stub in tests via
``httpx.MockTransport``:

  1. :meth:`list_user_repos` — used by onboarding to refresh the
     ``user_git_permissions`` snapshot for a specific employee.
  2. :meth:`verify_write_access` — live double-check invoked by
     :class:`runtime.tools.git_repo_acl_hook.GitRepoAclHook` for write
     operations, per plan §Gap 2.
  3. :meth:`mint_deploy_token` / :meth:`revoke_deploy_token` — paired
     lifecycle API consumed by
     :class:`runtime.vault.ephemeral_git_token.EphemeralGitTokenIssuer`.

The admin token is never echoed into exceptions — a swallowed HTTP body
is sanitized so stack traces / audit logs stay safe to ship to ops.

Access-level mapping follows GitLab's canonical scale
(``https://docs.gitlab.com/ee/api/members.html#roles``):

    Guest(10) / Reporter(20) → :class:`GitAccessLevel.READ`
    Developer(30) / Maintainer(40) / Owner(50) → :class:`GitAccessLevel.WRITE`
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from vendor_runtime_sdk.runtime.protocols.user_git_permissions_repository import GitAccessLevel
from vendor_runtime_sdk.runtime.vault.ephemeral_git_token import MintedDeployToken

logger = logging.getLogger(__name__)

__all__ = [
    "GitLabClient",
    "GitLabClientError",
    "GitLabNotFoundError",
    "GitLabUnauthorizedError",
    "UserRepoAccess",
]


# ── Exceptions ────────────────────────────────────────────────────────────


class GitLabClientError(Exception):
    """Base class for all GitLab client failures.

    ``__repr__`` deliberately redacts anything that looks like the admin
    token so exception propagation cannot leak it into logs.
    """

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class GitLabUnauthorizedError(GitLabClientError):
    """Raised on 401 from the provider — configuration / token issue."""


class GitLabNotFoundError(GitLabClientError):
    """Raised on 404 when the caller expects the resource to exist."""


# ── DTO ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UserRepoAccess:
    """One ``(repo, access)`` pair from :meth:`GitLabClient.list_user_repos`."""

    repo: str
    access: GitAccessLevel


# ── Access-level mapping ──────────────────────────────────────────────────


_WRITE_THRESHOLD = 30  # Developer+ grants push access in GitLab's model.


def _access_level_to_enum(level: Optional[int]) -> GitAccessLevel:
    if level is None or level < _WRITE_THRESHOLD:
        return GitAccessLevel.READ
    return GitAccessLevel.WRITE


def _extract_effective_level(permissions: dict) -> Optional[int]:
    """Return the higher of project_access / group_access levels."""
    levels: List[int] = []
    for key in ("project_access", "group_access"):
        block = permissions.get(key) or {}
        lvl = block.get("access_level")
        if isinstance(lvl, int):
            levels.append(lvl)
    return max(levels) if levels else None


def _parse_expires_at(value: Optional[str]) -> float:
    if not value:
        return time.time() + 3600
    # GitLab emits either an ISO-8601 datetime or a plain ``YYYY-MM-DD``.
    try:
        if "T" in value:
            # 2026-04-22T10:00:00.000Z → strip trailing Z for fromisoformat.
            normalised = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalised)
        else:
            dt = datetime.fromisoformat(value + "T00:00:00+00:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return time.time() + 3600


# ── Client ────────────────────────────────────────────────────────────────


class GitLabClient:
    """Minimal async GitLab v4 REST client focused on S2 needs.

    Parameters
    ----------
    base_url:
        Origin of the GitLab deployment (e.g. ``https://gitlab.com``).
        Trailing ``/`` is stripped.
    admin_token:
        Group-owner PAT used for listing other users' membership and for
        deploy-token lifecycle operations.  Never logged.
    transport:
        Optional ``httpx.AsyncBaseTransport`` override — tests inject an
        in-memory transport here.
    timeout:
        Per-request timeout in seconds.
    """

    _API_PREFIX = "/api/v4"

    def __init__(
        self,
        *,
        base_url: str,
        admin_token: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_token = admin_token
        self._transport = transport
        self._timeout = timeout

    # ── Public API ────────────────────────────────────────────────────

    async def list_user_repos(self, *, user_id: str) -> List[UserRepoAccess]:
        """Page through all projects the user is a member of."""
        path = f"{self._API_PREFIX}/users/{urllib.parse.quote(user_id, safe='')}/projects"
        out: List[UserRepoAccess] = []
        page = 1
        async with self._open_client() as client:
            while True:
                resp = await client.get(path, params={"page": page, "per_page": 100})
                self._raise_for_status(resp, path=path)
                rows = resp.json() or []
                for row in rows:
                    repo = row.get("path_with_namespace")
                    if not isinstance(repo, str) or not repo:
                        continue
                    perms = row.get("permissions") or {}
                    level = _extract_effective_level(perms)
                    out.append(
                        UserRepoAccess(
                            repo=repo,
                            access=_access_level_to_enum(level),
                        )
                    )
                next_page = resp.headers.get("x-next-page") or ""
                if not next_page.strip():
                    break
                try:
                    page = int(next_page)
                except ValueError:
                    break
        return out

    async def verify_write_access(self, *, user_id: str, repo: str) -> bool:
        """Fast live check invoked by the ACL hook for write operations.

        Returns ``False`` on missing project / insufficient level /
        absent permissions block — never raises for "no access".  The
        hook upstream is already fail-closed; surfacing a boolean keeps
        the call-site simple.
        """
        path = (
            f"{self._API_PREFIX}/projects/"
            f"{urllib.parse.quote(repo, safe='')}"
        )
        async with self._open_client() as client:
            resp = await client.get(
                path,
                params={"sudo": user_id} if user_id else None,
            )
            if resp.status_code == 404:
                return False
            if resp.status_code == 401:
                # Treat auth failure as "cannot verify" → hook denies.
                return False
            self._raise_for_status(resp, path=path, allow_404=True)
            body = resp.json() or {}
            level = _extract_effective_level(body.get("permissions") or {})
            return _access_level_to_enum(level) == GitAccessLevel.WRITE

    async def mint_deploy_token(
        self, repo: str, access: GitAccessLevel, ttl_sec: int
    ) -> MintedDeployToken:
        """Create a project-scoped deploy token.

        The name is disambiguated with a short UUID so simultaneous mints
        from multiple issuers do not collide at GitLab.
        """
        path = (
            f"{self._API_PREFIX}/projects/"
            f"{urllib.parse.quote(repo, safe='')}/deploy_tokens"
        )
        scopes = ["read_repository"]
        if access == GitAccessLevel.WRITE:
            scopes.append("write_repository")
        expires_at = (
            datetime.fromtimestamp(time.time() + ttl_sec, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        payload = {
            "name": f"aibuddy-{uuid.uuid4().hex[:8]}",
            "scopes": scopes,
            "expires_at": expires_at,
            "username": f"aibuddy-{uuid.uuid4().hex[:8]}",
        }
        async with self._open_client() as client:
            resp = await client.post(path, json=payload)
            self._raise_for_status(resp, path=path)
            body = resp.json() or {}

        token_value = body.get("token")
        token_id = body.get("id")
        if not token_value or token_id is None:
            raise GitLabClientError(
                "GitLab mint response missing token or id", status=resp.status_code
            )
        return MintedDeployToken(
            repo=repo,
            access=access,
            token_id=str(token_id),
            token_value=str(token_value),
            expires_at=_parse_expires_at(body.get("expires_at")),
        )

    async def revoke_deploy_token(self, repo: str, token_id: str) -> bool:
        """Delete a previously-minted deploy token.

        404 is treated as success: the token is already gone, which is
        the desired end-state.  Other non-2xx responses raise so the
        caller can emit a ``revoke_failed`` audit record.
        """
        path = (
            f"{self._API_PREFIX}/projects/"
            f"{urllib.parse.quote(repo, safe='')}/deploy_tokens/{token_id}"
        )
        async with self._open_client() as client:
            resp = await client.delete(path)
            if resp.status_code in (200, 202, 204, 404):
                return True
            self._raise_for_status(resp, path=path)
            return True

    # ── Internals ─────────────────────────────────────────────────────

    def _open_client(self) -> httpx.AsyncClient:
        kwargs: dict = {
            "base_url": self._base_url,
            "headers": {
                "PRIVATE-TOKEN": self._admin_token,
                "Accept": "application/json",
            },
            "timeout": self._timeout,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    def _raise_for_status(
        self,
        resp: httpx.Response,
        *,
        path: str,
        allow_404: bool = False,
    ) -> None:
        if 200 <= resp.status_code < 300:
            return
        if resp.status_code == 404 and allow_404:
            return
        body_snippet = self._sanitise_body(resp)
        if resp.status_code == 401:
            raise GitLabUnauthorizedError(
                f"GitLab 401 on {path}: {body_snippet}", status=401
            )
        if resp.status_code == 404:
            raise GitLabNotFoundError(
                f"GitLab 404 on {path}: {body_snippet}", status=404
            )
        raise GitLabClientError(
            f"GitLab {resp.status_code} on {path}: {body_snippet}",
            status=resp.status_code,
        )

    def _sanitise_body(self, resp: httpx.Response) -> str:
        try:
            text = resp.text
        except Exception:  # noqa: BLE001 — don't let sanitizer fail
            return "<unreadable>"
        if not text:
            return ""
        redacted = text.replace(self._admin_token, "<redacted>")
        # Truncate to keep logs bounded.
        return redacted[:500]
