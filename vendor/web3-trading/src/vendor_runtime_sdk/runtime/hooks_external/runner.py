"""S2.1 · Subprocess runner for external hooks.

Each hook runs in its own subprocess.  stdin = encoded
:class:`HookInput`, stdout = JSON parsed via
:func:`decode_output`.  stderr captured (capped 4 KiB) and logged
but never surfaced to the LLM.

Operator safety:
- Hard timeout (default 10 s).  Timeout = killed subprocess +
  :class:`HookTimeout` raised so the caller can fail-soft.
- Subprocess CWD = workspace_root when supplied (NOT the agent's
  CWD; hooks need to read project-local config like
  ``<workspace>/.coder/hooks.toml``).
- ``shell=False`` — command is parsed via ``shlex.split`` so an
  attacker can't inject extra commands via shell metacharacters.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass
from typing import Optional

from .protocol import HookInput, HookOutput, decode_output, encode_input

logger = logging.getLogger(__name__)


_STDERR_CAP = 4 * 1024
"""Hook stderr cap — beyond this we truncate so a noisy hook can't
blow the agent log."""


class HookTimeout(RuntimeError):
    """Raised when a hook subprocess exceeds its declared timeout.

    The caller (AgentLoop integration in S2.1 PR2) treats this as
    fail-soft: log + continue without applying any hook output.
    """


@dataclass(frozen=True)
class HookSpec:
    """Configuration for a single hook entry from
    ``~/.aibuddy/hooks.toml`` or ``<workspace>/.coder/hooks.toml``.

    Attributes:
        name: Human-readable label for logs / Toast notifications.
        command: Shell-style command string parsed via ``shlex.split``.
        timeout_seconds: Hard timeout; subprocess killed when exceeded.
    """

    name: str
    command: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("hook name is required")
        if not self.command:
            raise ValueError("hook command is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")


async def run_hook(
    spec: HookSpec,
    payload: HookInput,
    *,
    workspace_root: Optional[str] = None,
) -> HookOutput:
    """Execute ``spec`` as a subprocess, feed ``payload`` to stdin,
    parse stdout JSON into a :class:`HookOutput`, return it.

    Raises:
        HookTimeout: subprocess exceeded ``spec.timeout_seconds``.
        FileNotFoundError: command's executable couldn't be found.
        ValueError: stdout is not valid JSON or violates the protocol.
        RuntimeError: spawn-time failure other than missing executable.
    """
    try:
        argv = shlex.split(spec.command)
    except ValueError as exc:
        raise RuntimeError(
            f"hook {spec.name!r}: invalid command syntax — {exc}"
        ) from exc
    if not argv:
        raise RuntimeError(f"hook {spec.name!r}: empty command after parsing")

    stdin_bytes = encode_input(payload).encode("utf-8")

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_root,
        )
    except FileNotFoundError:
        # Surface verbatim so the caller can distinguish "configured a
        # hook for an executable that doesn't exist" from other failure
        # modes.
        raise
    except Exception as exc:  # noqa: BLE001 — wrap in RuntimeError
        raise RuntimeError(
            f"hook {spec.name!r}: failed to spawn subprocess — {exc}"
        ) from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_bytes),
            timeout=spec.timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        # Best-effort kill — the loop will clean up the zombie
        # process even if the kill races.
        try:
            proc.kill()
            await proc.wait()
        except Exception:  # noqa: BLE001 — already failing, log + continue
            logger.warning(
                "hook %s: kill after timeout raised", spec.name, exc_info=True
            )
        raise HookTimeout(
            f"hook {spec.name!r} exceeded {spec.timeout_seconds}s"
        ) from exc

    stderr_text = (stderr or b"").decode("utf-8", errors="replace")
    if stderr_text:
        truncated = stderr_text[:_STDERR_CAP]
        marker = (
            ""
            if len(stderr_text) <= _STDERR_CAP
            else f" …[truncated {len(stderr_text) - _STDERR_CAP}b]"
        )
        # Logged at INFO so operators can debug hook behaviour without
        # filling the default WARNING channel; never surfaced to LLM.
        logger.info(
            "hook %s stderr: %s%s",
            spec.name, truncated, marker,
        )

    stdout_text = (stdout or b"").decode("utf-8", errors="replace")
    decoded = (
        HookOutput()
        if not stdout_text.strip()
        else decode_output(stdout_text)
    )

    # Sprint 10 PR-4 (T2.1) — close the silent-failure gap.  When the
    # hook exits non-zero and didn't set its own ``final_message``, the
    # runner synthesises a structured one so PostFailure-event callers
    # (and downstream LLM context via dispatcher's
    # ``MergedPostToolUseFailure.final_message``) see a clear signal
    # instead of an empty no-op.  Hooks that explicitly set their own
    # ``final_message`` always win — operator authority preserved.
    rc = proc.returncode if proc.returncode is not None else 0
    if rc != 0 and decoded.final_message is None:
        decoded = decoded.__class__(
            updated_input=decoded.updated_input,
            permission_override=decoded.permission_override,
            reason=decoded.reason,
            additional_feedback=decoded.additional_feedback,
            retry=decoded.retry,
            final_message=_synthesise_final_message(
                spec, rc, stderr_text,
            ),
        )

    return decoded


def _synthesise_final_message(
    spec: HookSpec, returncode: int, stderr_text: str,
) -> str:
    """Sprint 10 PR-4 + PR-review fix HIGH-1.

    Build the structured ``[hook:<name>] exit=<rc>; stderr=<...>``
    message that surfaces a silent hook crash to the LLM.

    Security-review HIGH-1: stderr is operator-script output and may
    legitimately contain a secret printed by an erroring hook
    subprocess (e.g. an exception that includes ``DB_PASSWORD`` from
    env).  The truncated string is run through
    :func:`security.secret_scanner.redact_secrets` BEFORE
    interpolation so secrets never reach the next-turn LLM context.
    Fail-soft on import / scanner error so an inability to import
    the scanner doesn't drop the diagnostic entirely.
    """
    truncated = (stderr_text or "").strip()[:_STDERR_CAP]
    try:
        from security.secret_scanner import redact_secrets

        truncated = redact_secrets(truncated)
    except Exception:  # noqa: BLE001 — fail-soft per design
        # Scanner unavailable in this runtime — surface the
        # diagnostic anyway; the operator log already captured the
        # raw stderr at INFO so there's no information loss.
        pass
    return (
        f"[hook:{spec.name}] exit={returncode}; "
        f"stderr={truncated or '<empty>'}"
    )
