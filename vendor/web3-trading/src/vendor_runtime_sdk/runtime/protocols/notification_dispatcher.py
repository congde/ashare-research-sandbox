# -*- coding: utf-8 -*-
"""
NotificationDispatcher — PR-E6 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E6.

Goal
----
Replace the engine layer's direct dependency on ``lark.push_service``,
``lark.integration_service``, ``lark.card_builder``, ``lark.models``,
and ``lark.approval_service`` with a Protocol-based seam. SDK
consumers install their own NotificationDispatcher at boot;
ai-buddy installs an adapter that wraps ``LarkPushService`` so the
existing engine code path is byte-identical.

Today every engine call site that needs to dispatch a user-facing
notification does::

    from lark.integration_service import get_integration, get_client
    from lark.push_service import LarkPushService
    from lark.models import AlertEvent
    integration = await get_integration("default")
    push = LarkPushService(lark_client=get_client(integration),
                          tenant_id=integration.tenant_id)
    await push.push_alert(AlertEvent(type="cost", title=..., detail=...))

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``lark/`` is the channel-adapter
layer, kept outside the engine). PR-E6 introduces the abstraction —
the Protocol's methods are coarse-grained verbs ("notify user about
X"), not thin Lark API passthroughs.

Scope (V1)
----------
This PR handles 3 tier-1 call-site anchors:

* ``src/runtime/alert/dispatcher.py`` — ``build_lark_push_sender``
  rebuilt on top of the Protocol (THE motivating use case)
* ``src/runtime/collab_deliverable_artifacts.py`` —
  ``create_lark_doc_from_text`` (deliverable doc creation)
* ``src/agent/orchestration/rule_engine.py`` — ``_action_notify_lark``
  (rule-engine user notifications)

Plus the conversation-history-formatter sibling Protocol scope in
:mod:`runtime.protocols.conversation_history_formatter`.

Fall-back path (PR-E6 only; deleted in Phase 2)
-----------------------------------------------
When no dispatcher is installed via :func:`set_notification_dispatcher`,
:func:`get_notification_dispatcher` lazily synthesises one that wraps
``lark.push_service.LarkPushService``. Unlike PR-E4 (which raises when
neither installed-provider nor legacy DAO is reachable), notification
dispatch is **fail-soft** — a fresh :class:`NoOpNotificationDispatcher`
is returned silently when ``lark.*`` is unreachable. This mirrors the
existing ``build_lark_push_sender`` behaviour of returning ``None``
when no Lark integration is configured.

PII discipline
--------------
Five hard rules baked into the Protocol + impls:

1. ``logger.info`` on ``set_notification_dispatcher`` logs ONLY the
   implementation class name — NEVER the dispatcher instance contents.
2. ``logger.warning`` on send-failure logs the exception class name
   only — NEVER the AlertNotification / CardNotification payload
   (which can contain workspace data, cost figures, prompt excerpts).
3. NoOp's ``_sent`` log stores sanitised payload summaries (verb +
   truncated title to 64 chars) — bounded so long test runs cannot
   accumulate PII.
4. Adapter NEVER calls ``repr(alert)`` / ``repr(card)`` in any log
   path. Dataclasses' default ``__repr__`` would dump all fields
   including ``detail`` text.
5. The legacy adapter pipes ``alert.detail`` + ``card.fields`` through
   ``security.secret_scanner.redact_secrets`` BEFORE constructing the
   Lark payload — last line of defense before content leaves the
   engine boundary.

Same pattern as PR-E1 :class:`EngineConfig`, PR-E3
:class:`ContextStore`, PR-E4 :class:`CostRecordRepository`, and PR-E5
:class:`BackendClientProvider` — engine carries its own contract;
business layer keeps its own concrete types; the SDK seam lives at
the import boundary.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    Any,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Union,
    runtime_checkable,
)

logger = logging.getLogger(__name__)


# ── Engine-owned notification dataclasses (channel-neutral) ─────────────


@dataclass(frozen=True)
class UserRef:
    """Channel-neutral handle for a user notification target.

    ``user_id`` is a tenant-scoped opaque ID — the engine never parses
    or formats it. The Lark adapter maps it to a Feishu open_id /
    union_id via its own resolver. A Slack adapter would map to a
    Slack user-id; a Teams adapter to AAD user_id.
    """

    user_id: str
    tenant_id: Optional[str] = None


@dataclass(frozen=True)
class ChatRef:
    """Channel-neutral handle for a group / chat notification target.

    ``chat_type`` is an opaque hint for adapters — e.g. ``'group'`` /
    ``'p2p'`` / ``'topic'``. Engine code MUST NOT branch on its
    value; only the adapter consumes it.
    """

    chat_id: str
    tenant_id: Optional[str] = None
    chat_type: Optional[str] = None


@dataclass(frozen=True)
class AlertNotification:
    """Cost / quota / policy alert payload.

    ``kind`` is one of ``'cost'`` | ``'quota'`` | ``'policy'`` |
    ``'rate_limit'``. ``severity`` defaults to ``'warning'``.
    """

    kind: str
    title: str
    detail: str
    tenant_id: Optional[str] = None
    dashboard_url: Optional[str] = None
    severity: str = "warning"


@dataclass(frozen=True)
class CardNotification:
    """Structured card payload — adapter picks the channel-specific
    renderer based on ``kind``.

    ``fields`` is a ``Mapping[str, Any]`` so card-content schema stays
    flexible without exploding the engine surface. The adapter
    validates per-kind. ``actions`` is an opaque sequence of
    button/link descriptors interpreted by the adapter.
    """

    kind: str
    title: str
    fields: Mapping[str, Any]
    actions: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True)
class ApprovalNotification:
    """HITL / approval-flow card payload."""

    approval_id: str
    title: str
    detail: str
    expires_at: Optional[datetime] = None
    callback_url: Optional[str] = None


@dataclass(frozen=True)
class DocumentRef:
    """Channel-neutral handle for a created document (Lark Doc /
    Google Doc / Confluence page / Notion page).

    Returned by :meth:`NotificationDispatcher.create_document` so
    callers can persist the URL alongside their domain entity. The
    engine never parses ``document_id`` — the adapter owns that
    format.
    """

    document_id: str
    url: str
    title: str


class NotificationDispatcherNotInstalledError(RuntimeError):
    """Raised by :func:`get_notification_dispatcher` ONLY when the
    caller explicitly bypasses the fail-soft fallback. In normal
    operation :func:`get_notification_dispatcher` never raises — it
    returns :class:`NoOpNotificationDispatcher` when no dispatcher is
    installed and ``lark.*`` is unreachable.

    Reserved for future use; kept in the module surface to mirror
    PR-E3/E4/E5 contract shape.
    """


# ── Protocol ────────────────────────────────────────────────────────────


@runtime_checkable
class NotificationDispatcher(Protocol):
    """Pluggable dispatcher for engine-emitted user-facing notifications.

    Methods are coarse-grained verbs (``notify user about X``), NOT
    thin channel-API passthroughs. Implementations translate the
    engine dataclasses to their channel-specific envelopes internally.

    All methods are fail-soft: return ``Optional[str]`` (message_id on
    success, ``None`` on dispatch failure). Implementations MUST NOT
    raise on transient channel failures — log and return ``None``.
    Notification text MUST NOT be logged at INFO+ level (it may
    contain workspace context / tool outputs / prompt excerpts).
    """

    async def send_alert(
        self,
        alert: AlertNotification,
    ) -> Optional[str]: ...

    async def send_text_to_user(
        self,
        *,
        user_ref: UserRef,
        text: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]: ...

    async def send_text_to_chat(
        self,
        *,
        chat_ref: ChatRef,
        text: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]: ...

    async def send_card_to_user(
        self,
        *,
        user_ref: UserRef,
        card: CardNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]: ...

    async def send_card_to_chat(
        self,
        *,
        chat_ref: ChatRef,
        card: CardNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]: ...

    async def send_approval_card(
        self,
        *,
        target: Union[UserRef, ChatRef],
        approval: ApprovalNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]: ...

    async def resolve_default_target(
        self,
        *,
        integration_id: str = "default",
    ) -> Optional[ChatRef]: ...

    async def create_document(
        self,
        *,
        title: str,
        body_text: str,
        folder_token: Optional[str] = None,
        integration_id: str = "default",
    ) -> Optional[DocumentRef]:
        """Create a channel-native document (Lark Doc / Google Doc /
        ...) with plain-text body. Returns a :class:`DocumentRef` on
        success, ``None`` when no channel is configured.

        Engine callers use this for deliverable export (see
        :mod:`runtime.collab_deliverable_artifacts`). Implementations
        translate ``body_text`` to channel-specific block structures
        internally — engine code never builds Lark / Google blocks.
        """
        ...

    def has_notification_channel(self) -> bool:
        """Return ``True`` iff this dispatcher has a real delivery
        channel attached (NOT the NoOp sink).

        Engine callers use this as a capability sentinel to decide
        whether to attempt notification at all.  Replaces fragile
        ``isinstance(dispatcher, NoOpNotificationDispatcher)`` checks
        — review feedback identified those as leaky abstraction (any
        test subclass of NoOp would silently disable delivery).

        Returns:
            ``False`` for :class:`NoOpNotificationDispatcher` (test
            sink / SDK-default fallback when no channel is configured).
            ``True`` for any concrete dispatcher with a real channel
            attached (e.g. :class:`_LegacyLarkNotificationDispatcher`
            when ``lark.*`` is importable).
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_notification_dispatcher: Optional[NotificationDispatcher] = None


def set_notification_dispatcher(dispatcher: NotificationDispatcher) -> None:
    """Install the NotificationDispatcher used by all engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO with the
    implementation class name only — NEVER logs the dispatcher
    instance contents (PII discipline).

    Raises:
        TypeError: when ``dispatcher`` does not satisfy the
            :class:`NotificationDispatcher` Protocol at the structural
            level.
    """
    if not isinstance(dispatcher, NotificationDispatcher):
        raise TypeError(
            f"set_notification_dispatcher: dispatcher must satisfy "
            f"NotificationDispatcher Protocol (send_alert / "
            f"send_text_to_user / send_text_to_chat / send_card_to_user "
            f"/ send_card_to_chat / send_approval_card / "
            f"resolve_default_target / create_document / "
            f"has_notification_channel), got {type(dispatcher).__name__}"
        )
    global _notification_dispatcher
    _notification_dispatcher = dispatcher
    logger.info(
        "NotificationDispatcher installed: %s",
        type(dispatcher).__name__,
    )


def get_notification_dispatcher() -> NotificationDispatcher:
    """Return the installed dispatcher, falling back to a lazy adapter
    that wraps :class:`lark.push_service.LarkPushService` when no
    explicit dispatcher is installed AND ``lark.*`` is importable,
    otherwise to :class:`NoOpNotificationDispatcher`.

    Notification dispatch is fail-soft by design — this function
    NEVER raises in normal operation. A fresh
    :class:`NoOpNotificationDispatcher` is returned silently when no
    dispatcher is installed and ``lark.*`` is unreachable. This
    mirrors the existing ``build_lark_push_sender`` behaviour of
    returning ``None`` when no Lark integration is configured.
    """
    if _notification_dispatcher is not None:
        return _notification_dispatcher

    # PR-E6 fall-back. Probe ``lark.push_service`` reachability.
    try:
        import importlib
        importlib.import_module("lark.push_service")
    except ImportError:
        # No Lark adapter available — return NoOp silently (fail-soft).
        return _NoOpFallbackSingleton.get()

    return _LegacyLarkNotificationDispatcher.get_singleton()


def reset_notification_dispatcher_for_test() -> None:
    """Test-only helper to clear the installed dispatcher between
    cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.cost_record_repository.reset_cost_record_repository_for_test`.
    """
    global _notification_dispatcher
    _notification_dispatcher = None
    _LegacyLarkNotificationDispatcher.reset_singleton_for_test()
    _NoOpFallbackSingleton.reset_for_test()


# ── NoOp impl (test sink + SDK default) ─────────────────────────────────


def _sanitise_for_test_log(payload: Any) -> Mapping[str, Any]:
    """Return a bounded summary of a notification payload suitable
    for the in-memory test log. NEVER stores the raw text — only
    payload type + truncated title (64 chars, middle redacted).
    """

    def _trunc(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        s = str(value)
        if len(s) <= 64:
            return s
        # Replace middle with ellipsis to keep both ends visible
        # without retaining raw content beyond the bound.
        head = s[:28]
        tail = s[-28:]
        return f"{head}…{tail}"

    type_name = type(payload).__name__
    title = getattr(payload, "title", None)
    kind = getattr(payload, "kind", None)
    return {
        "type": type_name,
        "title": _trunc(title),
        "kind": kind,
    }


class NoOpNotificationDispatcher:
    """In-memory sink. Records every dispatch call so tests can assert
    on verb + payload summary, without retaining raw PII.

    Returned by :func:`get_notification_dispatcher` when no installed
    provider exists and the legacy ``lark.*`` path is unreachable.

    WARNING: this impl deliberately does NOT log notification bodies
    at INFO+ level — only the in-memory ``_sent`` log keeps a
    sanitised summary. Tests asserting on raw text must use a custom
    test double.
    """

    def __init__(self) -> None:
        self._sent: List[Tuple[str, Any]] = []

    def _record(self, verb: str, payload: Any) -> str:
        self._sent.append((verb, _sanitise_for_test_log(payload)))
        return f"noop-msg-{uuid.uuid4().hex[:12]}"

    async def send_alert(
        self,
        alert: AlertNotification,
    ) -> Optional[str]:
        return self._record("send_alert", alert)

    async def send_text_to_user(
        self,
        *,
        user_ref: UserRef,
        text: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        # Wrap text into a pseudo-payload object purely for the test
        # log summariser — never persisted long-term.
        payload = type(
            "TextPayload", (), {"title": text, "kind": "text"}
        )()
        return self._record("send_text_to_user", payload)

    async def send_text_to_chat(
        self,
        *,
        chat_ref: ChatRef,
        text: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        payload = type(
            "TextPayload", (), {"title": text, "kind": "text"}
        )()
        return self._record("send_text_to_chat", payload)

    async def send_card_to_user(
        self,
        *,
        user_ref: UserRef,
        card: CardNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        return self._record("send_card_to_user", card)

    async def send_card_to_chat(
        self,
        *,
        chat_ref: ChatRef,
        card: CardNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        return self._record("send_card_to_chat", card)

    async def send_approval_card(
        self,
        *,
        target: Union[UserRef, ChatRef],
        approval: ApprovalNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        return self._record("send_approval_card", approval)

    async def resolve_default_target(
        self,
        *,
        integration_id: str = "default",
    ) -> Optional[ChatRef]:
        # NoOp impl returns None — no default channel target
        # configured.
        return None

    async def create_document(
        self,
        *,
        title: str,
        body_text: str,
        folder_token: Optional[str] = None,
        integration_id: str = "default",
    ) -> Optional[DocumentRef]:
        payload = type(
            "DocPayload", (), {"title": title, "kind": "document"}
        )()
        self._record("create_document", payload)
        synthetic_id = f"noop-doc-{uuid.uuid4().hex[:12]}"
        return DocumentRef(
            document_id=synthetic_id,
            url=f"noop://document/{synthetic_id}",
            title=title,
        )

    def has_notification_channel(self) -> bool:
        """NoOp impl — explicitly reports "no delivery channel"
        so engine callers (build_lark_push_sender,
        create_lark_doc_from_text, etc.) can detect the test / SDK-
        default fallback case without an isinstance leak.

        See PR-E6 review: any subclass of NoOp would silently bypass
        an isinstance check; this Protocol method is the durable
        capability sentinel.
        """
        return False

    # ── Test helpers (not part of the Protocol) ──────────────────

    @property
    def sent(self) -> List[Tuple[str, Any]]:
        """Read-only view of the recorded (verb, summary) log.

        NOT part of the NotificationDispatcher Protocol — callers
        relying on this must depend on the concrete NoOp type.
        """
        return list(self._sent)

    def drain_sent(self) -> List[Tuple[str, Any]]:
        """Return + clear the recorded (verb, summary) log."""
        out = list(self._sent)
        self._sent.clear()
        return out

    def clear(self) -> None:
        """Clear the recorded send log without returning it."""
        self._sent.clear()


class _NoOpFallbackSingleton:
    """Holds the singleton NoOpNotificationDispatcher returned by
    :func:`get_notification_dispatcher` when ``lark.*`` is
    unreachable. Singleton (not per-call construction) so test
    assertions that introspect the in-memory log can find prior
    records across distinct ``get_notification_dispatcher()`` calls.
    """

    _INSTANCE: Optional[NoOpNotificationDispatcher] = None

    @classmethod
    def get(cls) -> NoOpNotificationDispatcher:
        if cls._INSTANCE is None:
            cls._INSTANCE = NoOpNotificationDispatcher()
        return cls._INSTANCE

    @classmethod
    def reset_for_test(cls) -> None:
        cls._INSTANCE = None


# ── Legacy LarkPushService adapter (fallback) ───────────────────────────


def _redact_or_passthrough(text: Optional[str]) -> str:
    """Redact secrets from notification text before it leaves the
    engine boundary. Falls back to the raw text when the secret
    scanner is unreachable (e.g. trimmed SDK build).
    """
    if text is None:
        return ""
    try:
        from security.secret_scanner import redact_secrets
        return redact_secrets(text)
    except Exception:
        return text


class _LegacyLarkNotificationDispatcher:
    """Adapter that exposes :class:`lark.push_service.LarkPushService`
    via the :class:`NotificationDispatcher` Protocol.

    Used only via the fall-back path in
    :func:`get_notification_dispatcher` when no SDK-side dispatcher
    is installed. ai-buddy can choose to install this adapter
    explicitly at boot (cleaner audit trail) or rely on the fall-back
    (zero boot wiring).

    Each method re-resolves ``lark.integration_service.get_integration``
    lazily — same fail-soft pattern as ``build_lark_push_sender``.
    Exceptions are caught + logged at WARN (never ERROR — notification
    failure is operational, not a bug); the method returns ``None``.
    """

    _SINGLETON: Optional["_LegacyLarkNotificationDispatcher"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyLarkNotificationDispatcher":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    async def _push_service_or_none(
        self, tenant_id: Optional[str], integration_id: str = "default"
    ) -> Optional[Any]:
        try:
            from lark.integration_service import get_integration, get_client
            from lark.push_service import LarkPushService

            try:
                integration = await get_integration(integration_id)
            except Exception as exc:
                logger.info(
                    "NotificationDispatcher: no Lark integration (%s) "
                    "configured — skipping push: %s",
                    integration_id,
                    type(exc).__name__,
                )
                return None

            if integration is None:
                return None
            client = get_client(integration)
            return LarkPushService(
                lark_client=client,
                tenant_id=tenant_id or integration.tenant_id,
            )
        except Exception as exc:
            # Class name only — never log raw exception message which
            # may contain credentials / URLs.
            logger.warning(
                "NotificationDispatcher: Lark unreachable: %s",
                type(exc).__name__,
            )
            return None

    async def send_alert(
        self,
        alert: AlertNotification,
    ) -> Optional[str]:
        push = await self._push_service_or_none(alert.tenant_id)
        if push is None:
            return None
        try:
            from lark.models import AlertEvent

            lark_evt = AlertEvent(
                type=alert.kind,
                title=_redact_or_passthrough(alert.title),
                detail=_redact_or_passthrough(alert.detail),
                tenant_id=getattr(push, "tenant_id", "") or "",
                dashboard_url=alert.dashboard_url or "",
            )
            return await push.push_alert(lark_evt)
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.send_alert failed: %s",
                type(exc).__name__,
            )
            return None

    async def send_text_to_user(
        self,
        *,
        user_ref: UserRef,
        text: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        push = await self._push_service_or_none(tenant_id or user_ref.tenant_id)
        if push is None:
            return None
        try:
            safe = _redact_or_passthrough(text)
            return await push.push_to_user(
                user_ref.user_id, "text", {"text": safe}
            )
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.send_text_to_user failed: %s",
                type(exc).__name__,
            )
            return None

    async def send_text_to_chat(
        self,
        *,
        chat_ref: ChatRef,
        text: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        push = await self._push_service_or_none(tenant_id or chat_ref.tenant_id)
        if push is None:
            return None
        try:
            safe = _redact_or_passthrough(text)
            return await push.push_to_chat(
                chat_ref.chat_id, "text", {"text": safe}
            )
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.send_text_to_chat failed: %s",
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _render_card(card: CardNotification) -> Optional[Mapping[str, Any]]:
        """Dispatch on ``card.kind`` to a LarkCardBuilder method.

        Unknown ``kind`` returns ``None`` (logged at WARN). Unknown
        renderer methods do not raise into the engine.
        """
        try:
            from lark.card_builder import LarkCardBuilder
        except ImportError:
            return None
        method_name = f"{card.kind}_card"
        method = getattr(LarkCardBuilder, method_name, None)
        if method is None:
            logger.warning(
                "NotificationDispatcher: unknown card kind %r — "
                "no LarkCardBuilder.%s",
                card.kind,
                method_name,
            )
            return None
        try:
            # Redact secrets in fields before passing to the renderer.
            safe_fields = {
                k: _redact_or_passthrough(v) if isinstance(v, str) else v
                for k, v in card.fields.items()
            }
            return method(title=_redact_or_passthrough(card.title), **safe_fields)
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher: card render failed (kind=%r): %s",
                card.kind,
                type(exc).__name__,
            )
            return None

    async def send_card_to_user(
        self,
        *,
        user_ref: UserRef,
        card: CardNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        push = await self._push_service_or_none(tenant_id or user_ref.tenant_id)
        if push is None:
            return None
        rendered = self._render_card(card)
        if rendered is None:
            return None
        try:
            return await push.push_to_user(
                user_ref.user_id, "interactive", rendered
            )
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.send_card_to_user failed: %s",
                type(exc).__name__,
            )
            return None

    async def send_card_to_chat(
        self,
        *,
        chat_ref: ChatRef,
        card: CardNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        push = await self._push_service_or_none(tenant_id or chat_ref.tenant_id)
        if push is None:
            return None
        rendered = self._render_card(card)
        if rendered is None:
            return None
        try:
            return await push.push_to_chat(
                chat_ref.chat_id, "interactive", rendered
            )
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.send_card_to_chat failed: %s",
                type(exc).__name__,
            )
            return None

    async def send_approval_card(
        self,
        *,
        target: Union[UserRef, ChatRef],
        approval: ApprovalNotification,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        try:
            from lark.approval_service import LarkApprovalService
            from lark.integration_service import get_integration, get_client

            try:
                integration = await get_integration("default")
            except Exception as exc:
                logger.info(
                    "NotificationDispatcher.send_approval_card: no Lark "
                    "integration (default) — skipping: %s",
                    type(exc).__name__,
                )
                return None
            if integration is None:
                return None
            client = get_client(integration)
            svc = LarkApprovalService(
                tenant_id=tenant_id or integration.tenant_id,
                lark_client=client,
            )
            return await svc.sync_to_lark(approval)
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.send_approval_card failed: %s",
                type(exc).__name__,
            )
            return None

    async def resolve_default_target(
        self,
        *,
        integration_id: str = "default",
    ) -> Optional[ChatRef]:
        try:
            from lark.receive_id import resolve_default_group_chat_id

            chat_id = await resolve_default_group_chat_id()
            if not chat_id:
                return None
            return ChatRef(chat_id=chat_id, chat_type="group")
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.resolve_default_target failed: %s",
                type(exc).__name__,
            )
            return None

    async def create_document(
        self,
        *,
        title: str,
        body_text: str,
        folder_token: Optional[str] = None,
        integration_id: str = "default",
    ) -> Optional[DocumentRef]:
        try:
            from lark.integration_service import get_client_sync

            client = get_client_sync(integration_id)
            if not client:
                return None

            safe_title = _redact_or_passthrough(title).strip()[:256] or "Deliverable"
            doc = await client.create_doc(
                title=safe_title, folder_token=folder_token
            )
            doc_id = doc.get("document_id", "") if isinstance(doc, dict) else ""
            if not doc_id:
                return None

            # Resolve the public URL using the legacy heuristic in
            # ``collab_deliverable_artifacts``. Inlined here to keep
            # the engine module free of the lark.* base URL switch.
            import os
            base = os.environ.get("LARK_DOC_PUBLIC_BASE", "").strip()
            if not base:
                lark_base = os.environ.get(
                    "LARK_BASE_URL", "https://open.feishu.cn"
                )
                if "open.feishu.cn" in lark_base:
                    base = "https://bytedance.feishu.cn/docx"
                elif "open.larksuite.com" in lark_base:
                    base = "https://larksuite.com/docx"
                else:
                    base = "https://bytedance.feishu.cn/docx"
            doc_url = f"{base.rstrip('/')}/{doc_id}"

            # Body blocks — delegate to the standalone block converter
            # in runtime.lark_block_utils.  Imported from the dedicated
            # util module (NOT runtime.collab_deliverable_artifacts) to
            # avoid the circular import flagged by PR-E6 review.
            try:
                from vendor_runtime_sdk.runtime.lark_block_utils import (
                    plain_text_to_lark_blocks,
                )
                safe_body = _redact_or_passthrough(body_text or "")
                blocks = plain_text_to_lark_blocks(safe_body)
                if blocks:
                    await client.create_doc_block(
                        doc_token=doc_id, block_id=doc_id, children=blocks
                    )
            except Exception as exc:
                logger.warning(
                    "NotificationDispatcher.create_document: blocks "
                    "population failed (doc still created): %s",
                    type(exc).__name__,
                )

            return DocumentRef(
                document_id=doc_id, url=doc_url, title=safe_title
            )
        except Exception as exc:
            logger.warning(
                "NotificationDispatcher.create_document failed: %s",
                type(exc).__name__,
            )
            return None

    def has_notification_channel(self) -> bool:
        """Legacy adapter reports True iff ``lark.*`` is importable.

        Probed lazily on every call so a deferred Lark install (e.g.
        sidecar boot order) surfaces correctly.  This is the
        capability sentinel engine code uses to decide whether to
        attempt notification — replaces fragile ``isinstance(d,
        NoOpNotificationDispatcher)`` checks.
        """
        try:
            import importlib
            importlib.import_module("lark.push_service")
            return True
        except Exception:  # noqa: BLE001 — any import failure = no channel
            return False


__all__ = [
    "NotificationDispatcher",
    "NotificationDispatcherNotInstalledError",
    "NoOpNotificationDispatcher",
    "UserRef",
    "ChatRef",
    "AlertNotification",
    "CardNotification",
    "ApprovalNotification",
    "DocumentRef",
    "set_notification_dispatcher",
    "get_notification_dispatcher",
    "reset_notification_dispatcher_for_test",
]
# ``_LegacyLarkNotificationDispatcher`` is intentionally NOT exported —
# matches the PR-E3/E4/E5 convention of keeping the legacy adapter
# private (tests import it by name).
