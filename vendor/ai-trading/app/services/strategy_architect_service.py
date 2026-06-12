"""Strategy Architect agent service — natural language → safe Python.

Sprint-S5 deliverable. Wires together:

  * The Strategy Architect SKILL.md (system prompt + Level-3 examples)
  * The shared LLMClient (LiteLLM-based, with provider fallback)
  * The DSL safelist validator
  * The lookahead-bias linter
  * A bounded self-correction loop (default ≤ 3 retries)

The service is the only place that knows the **agentic loop shape**:

    user_prompt
        ↓
    [LLM call]  ←──┐
        ↓          │  if validator OR lookahead REJECTS,
    extract code   │  re-prompt with rule ids + suggestions
        ↓          │  and try again (≤ max_retries times)
    [validate]  ───┘
        ↓
    GenerationResult (final code + telemetry)

Why not stream
--------------

v1.0 ships the non-streaming variant on purpose. The LLM emits a
single fenced Python block; streaming token-by-token to the UI tempts
the user to read intermediate (incomplete, possibly invalid) code.
Streaming makes sense for explanatory text, not for the strict-format
output this agent produces. We ship streaming when the agent grows
multi-step natural-language reasoning (v1.5+).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.core.llm.llm_client import LLMClient, LLMMessage, LLMResponse
from app.services.strategy_architect_cost import (
    DEFAULT_MAX_USD_PER_SESSION,
    CostEstimate,
    estimate_cost,
    should_continue,
)
from app.services.strategy_card import StrategyCard, parse_card_json
from app.strategy_engine.dsl import (
    LookaheadFinding,
    ValidationError,
    check_lookahead_bias,
    validate_strategy_code,
)

logger = logging.getLogger("strategy_architect")


# ── Where the SKILL prompt body lives ────────────────────────────


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL_PATH = _REPO_ROOT / "app" / "skills" / "builtin" / "strategy-architect.md"


# ── Result types ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GenerationAttempt:
    """One LLM round-trip + its post-processing verdict.

    Records BOTH the raw LLM output and the extracted-code findings
    so the UI can show the user every retry that happened (helpful
    for debugging "why did this take 3 tries").
    """

    iteration: int  # 0-indexed; 0 = first attempt, 1 = first retry
    raw_response: str
    extracted_code: str
    validator_errors: tuple[ValidationError, ...]
    lookahead_errors: tuple[LookaheadFinding, ...]
    input_tokens: int
    output_tokens: int
    # Per-attempt USD cost. Aggregated across attempts in
    # ``GenerationResult.total_usd`` so cost-gate decisions and UI
    # tooltips both have data. ``model_used`` is the literal
    # ``LLMResponse.model`` string — useful for audit when a fallback
    # provider answered.
    model_used: str = ""
    cost_usd: float = 0.0
    cost_known: bool = True

    @property
    def rejected(self) -> bool:
        """Did either checker fire an error-severity finding?"""
        return bool(self.validator_errors) or bool(self.lookahead_errors)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Outcome of a full :meth:`StrategyArchitectService.generate` call.

    ``success`` distinguishes the two terminal states:
      * True  — final attempt passed both checkers; ``code`` is safe
      * False — exhausted retries; ``code`` is the last attempt's
        extracted code (NOT safe; surfaced for debugging only)
    """

    success: bool
    code: str
    attempts: tuple[GenerationAttempt, ...]
    elapsed_seconds: float
    # Token totals across ALL attempts — for cost accounting.
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    # Aggregated USD spend across all attempts. ``budget_exhausted``
    # distinguishes "we hit retry limit" (success=False, budget=False)
    # from "we hit budget limit" (success=False, budget=True) — they
    # surface different UI / soft-upgrade prompts.
    total_usd: float = 0.0
    budget_usd: float = DEFAULT_MAX_USD_PER_SESSION
    budget_exhausted: bool = False
    # Best-effort strategy card from a SECOND, isolated LLM call after the
    # code passes. None when generation failed, the card call failed, or the
    # card JSON didn't parse — the card never gates the code result.
    card: StrategyCard | None = None


# ── Code extractor ───────────────────────────────────────────────


# Matches a ```python fenced block. Tolerates ``` python (with space),
# ``` Python (capitalised), and falls back to any ``` block if no
# python-tagged one exists — adversarial LLM outputs sometimes drop
# the language tag.
_PRIMARY_BLOCK_RE = re.compile(
    r"```\s*python\s*\n(.*?)```",
    flags=re.DOTALL | re.IGNORECASE,
)
_FALLBACK_BLOCK_RE = re.compile(r"```\n?(.*?)```", flags=re.DOTALL)


def extract_python_code(raw: str) -> str:
    """Pull the first Python fenced block out of an LLM response.

    Strategy:
      1. Prefer ``` ```python … ``` ``` blocks.
      2. Fall back to any ``` ``` … ``` ``` block.
      3. If neither exists, return the raw text — let the validator
         downstream report the inevitable SyntaxError.

    Never raises; returns at worst an empty / malformed string that
    the validator handles.
    """
    m = _PRIMARY_BLOCK_RE.search(raw)
    if m:
        return m.group(1).rstrip()
    m = _FALLBACK_BLOCK_RE.search(raw)
    if m:
        return m.group(1).rstrip()
    return raw.strip()


# ── Re-prompt builder ────────────────────────────────────────────


def build_correction_prompt(
    *,
    validator_errors: tuple[ValidationError, ...],
    lookahead_errors: tuple[LookaheadFinding, ...],
) -> str:
    """Translate static-checker findings into an LLM-friendly retry
    prompt. Each finding becomes a single line with rule + suggestion
    — matching what the SKILL.md's self-correction protocol instructs
    the LLM to expect.

    Returned string is the body of a user-role message to append to
    the conversation.
    """
    lines: list[str] = [
        "The strategy you emitted failed validation. Fix all findings "
        "below in ONE pass and re-emit the FULL module (not a diff). "
        "See SKILL.md 'Self-correction protocol' for the rules.",
        "",
    ]

    if validator_errors:
        lines.append("Safelist validator findings:")
        for e in validator_errors:
            line = f"  L{e.line}:C{e.col} [{e.rule}] {e.message}"
            if e.suggestion:
                line += f"  → {e.suggestion}"
            lines.append(line)
        lines.append("")

    if lookahead_errors:
        lines.append("Lookahead-bias linter findings:")
        for f in lookahead_errors:
            line = f"  L{f.line}:C{f.col} [{f.rule}] {f.message}"
            if f.suggestion:
                line += f"  → {f.suggestion}"
            lines.append(line)
        lines.append("")

    lines.append("Re-emit the corrected strategy in a single ```python block.")
    return "\n".join(lines)


# ── Strategy-card generator (second, isolated LLM call) ──────────


@dataclass(frozen=True, slots=True)
class _CardCall:
    """Outcome of the best-effort card LLM call: the card (or None) plus the
    call's tokens/cost so they roll into the result totals + budget accounting."""

    card: StrategyCard | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


_CARD_SYSTEM_PROMPT = (
    "You are a quant strategy reviewer. Given a trading strategy's intent and "
    "its final Python code, summarise it as a STRATEGY CARD.\n\n"
    "Respond with ONLY a single JSON object (no prose) with exactly these keys:\n"
    '  "name": short title (<= 60 chars)\n'
    '  "thesis": 1-2 sentence edge thesis\n'
    '  "valid_when": array of strings — market conditions where the edge holds\n'
    '  "invalid_when": array of strings — conditions that kill the edge\n'
    '  "risk_checklist": array of strings — risks to monitor\n'
    '  "expected_metrics": object with optional numeric keys pnl_pct_min, '
    "sharpe_min, max_drawdown_pct_max, win_rate_min and a notes string\n\n"
    "Keep each array to 2-5 concise items. Output must be valid JSON."
)

_JSON_BLOCK_RE = re.compile(r"```\s*json\s*\n(.*?)```", flags=re.DOTALL | re.IGNORECASE)
_ANY_BLOCK_RE = re.compile(r"```\n?(.*?)```", flags=re.DOTALL)


def extract_json_block(raw: str) -> str:
    """Pull a JSON object from an LLM response — a ```json fence, any fence,
    or the first ``{...}`` span. Returns the raw text if nothing matches
    (``parse_card_json`` then raises and the caller drops the card)."""
    m = _JSON_BLOCK_RE.search(raw) or _ANY_BLOCK_RE.search(raw)
    if m:
        return m.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        return raw[start : end + 1]
    return raw.strip()


def build_card_user_prompt(*, user_prompt: str, symbol: str, timeframe: str, code: str) -> str:
    return (
        f"Symbol: {symbol}\nTimeframe: {timeframe}\n"
        f"Intent: {user_prompt}\n\n"
        f"Final strategy code:\n```python\n{code}\n```\n\n"
        "Emit the strategy card JSON now."
    )


# ── Service ──────────────────────────────────────────────────────


class StrategyArchitectService:
    """Convert natural-language strategy intent into safe Python.

    Stateless — one instance per process is fine; instantiate per
    request if you need per-user cost tracking via ``session_key``.

    Dependency injection:
      * ``llm_client`` — any object exposing ``async def chat(
        messages, *, tools=None, tool_choice="auto", effort_hint=None)
        -> LLMResponse``. Defaults to a fresh :class:`LLMClient`.
      * ``skill_md_loader`` — callable returning the SKILL.md body.
        Defaults to reading from disk. Override in tests so the
        unit suite doesn't depend on the file layout.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        max_retries: int = 3,
        skill_md_loader: object | None = None,
        budget_usd: float = DEFAULT_MAX_USD_PER_SESSION,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._max_retries = max_retries
        self._loader = skill_md_loader
        # Per-session USD spend cap. Checked BEFORE every LLM call so
        # the first attempt always runs (spent=0 < any positive budget)
        # but retries can abort early when the prior attempt's tokens
        # pushed the total past the limit.
        self._budget_usd = budget_usd

    def _load_system_prompt(self) -> str:
        """Return the SKILL.md body (without the YAML frontmatter)
        that goes into the system role of every LLM call."""
        if self._loader is not None:
            loaded: str = self._loader()  # type: ignore[operator]
            return loaded
        text: str = _SKILL_PATH.read_text()
        # Strip the YAML frontmatter — the LLM doesn't need the
        # loader-only metadata, and dropping it saves ~150 tokens
        # per call.
        if text.startswith("---\n"):
            _, _, body = text.partition("---\n")
            _, _, body = body.partition("---\n")
            return body.strip()
        return text.strip()

    async def generate(
        self,
        user_prompt: str,
        *,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
    ) -> GenerationResult:
        """Run the agentic loop.

        Args:
          user_prompt: natural-language intent
            ("BTC 1h 网格,价差 0.5%,12 格").
          symbol / timeframe: hints injected into the system message
            so the LLM doesn't have to ask back. The strategy code
            itself is symbol/timeframe-agnostic; these only shape
            the prompt's "default values" guidance.

        Returns:
          :class:`GenerationResult` with the final code + per-attempt
          telemetry + total token counts.
        """
        system_prompt = self._load_system_prompt()
        # Light user-prompt augmentation — keeps the system prompt
        # static (cache-friendly) and varies only the user turn.
        augmented_user = f"Symbol: {symbol}\nTimeframe: {timeframe}\n\nUser intent: {user_prompt}"

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=augmented_user),
        ]

        attempts: list[GenerationAttempt] = []
        t0 = time.perf_counter()
        budget_exhausted = False

        for iteration in range(self._max_retries):
            # Pre-call budget check. The first iteration always allowed
            # (spent=0). Later iterations may abort here if the prior
            # attempt's tokens pushed the running total past the cap.
            spent = sum(a.cost_usd for a in attempts)
            verdict = should_continue(spent, budget_usd=self._budget_usd)
            if not verdict.allowed:
                logger.warning("Strategy Architect budget gate fired: %s", verdict.reason)
                budget_exhausted = True
                break

            response = await self._llm.chat(messages)
            code = extract_python_code(response.content or "")

            validator_result = validate_strategy_code(code)
            lookahead_result = check_lookahead_bias(code)

            # The lookahead linter splits findings into errors vs
            # warnings; ONLY errors block. Warnings (e.g. L004
            # ``history[5]``) are surfaced via the report.warnings
            # property but don't trigger a retry.
            lookahead_errors = lookahead_result.errors

            cost: CostEstimate = estimate_cost(
                input_tokens=response.usage_prompt_tokens,
                output_tokens=response.usage_completion_tokens,
                model=response.model or "unknown",
            )

            attempt = GenerationAttempt(
                iteration=iteration,
                raw_response=response.content or "",
                extracted_code=code,
                validator_errors=tuple(validator_result.errors),
                lookahead_errors=tuple(lookahead_errors),
                input_tokens=response.usage_prompt_tokens,
                output_tokens=response.usage_completion_tokens,
                model_used=response.model or "unknown",
                cost_usd=cost.total_usd,
                cost_known=cost.price_known,
            )
            attempts.append(attempt)

            if not attempt.rejected:
                logger.info(
                    "Strategy Architect succeeded on attempt %d (%d retries used, $%.4f)",
                    iteration + 1,
                    iteration,
                    sum(a.cost_usd for a in attempts),
                )
                card_call = await self._generate_card(
                    user_prompt=user_prompt,
                    symbol=symbol,
                    timeframe=timeframe,
                    code=code,
                    spent=sum(a.cost_usd for a in attempts),
                )
                return _build_result(
                    success=True,
                    attempts=attempts,
                    t0=t0,
                    budget_usd=self._budget_usd,
                    budget_exhausted=False,
                    card_call=card_call,
                )

            # Rejected — append assistant turn + correction prompt,
            # loop. Last attempt skips this (no point appending if
            # we're not going to call again).
            if iteration < self._max_retries - 1:
                correction = build_correction_prompt(
                    validator_errors=attempt.validator_errors,
                    lookahead_errors=attempt.lookahead_errors,
                )
                messages.append(LLMMessage(role="assistant", content=response.content or ""))
                messages.append(LLMMessage(role="user", content=correction))

        # Loop exited without success. Distinguish budget-exhaustion
        # from retry-exhaustion — they ship different UI messages
        # (soft-upgrade vs "refine your prompt").
        if budget_exhausted:
            logger.warning(
                "Strategy Architect budget exhausted after %d attempts ($%.4f / $%.4f)",
                len(attempts),
                sum(a.cost_usd for a in attempts),
                self._budget_usd,
            )
        else:
            logger.warning(
                "Strategy Architect exhausted %d retries; final attempt still rejected",
                self._max_retries,
            )
        return _build_result(
            success=False,
            attempts=attempts,
            t0=t0,
            budget_usd=self._budget_usd,
            budget_exhausted=budget_exhausted,
        )

    async def _generate_card(
        self, *, user_prompt: str, symbol: str, timeframe: str, code: str, spent: float
    ) -> _CardCall:
        """Best-effort SECOND LLM call → a :class:`_CardCall` (card + its cost).

        Isolated from the code-generation loop: any failure (LLM error, bad
        JSON, missing required fields) yields an empty ``_CardCall``. The card
        is a nice-to-have and must NEVER gate a successfully-generated strategy.
        Skipped when the session budget is already spent (best-effort isn't
        worth exceeding the cap); when it does run, its tokens/cost are reported
        so the result totals match real spend.
        """
        if not should_continue(spent, budget_usd=self._budget_usd).allowed:
            logger.info("Strategy card skipped — session budget already spent.")
            return _CardCall()

        messages = [
            LLMMessage(role="system", content=_CARD_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=build_card_user_prompt(
                    user_prompt=user_prompt, symbol=symbol, timeframe=timeframe, code=code
                ),
            ),
        ]
        try:
            response = await self._llm.chat(messages)
        except Exception as exc:  # noqa: BLE001 — call failed; nothing was spent
            logger.warning("Strategy card LLM call failed (non-fatal): %s", type(exc).__name__)
            return _CardCall()

        # The call happened → count its cost even if the JSON doesn't parse.
        cost = estimate_cost(
            input_tokens=response.usage_prompt_tokens,
            output_tokens=response.usage_completion_tokens,
            model=response.model or "unknown",
        )
        card: StrategyCard | None = None
        try:
            card = parse_card_json(extract_json_block(response.content or ""))
            # Backfill the symbol/timeframe the LLM may have left blank so the
            # saved card carries the market (the library reads card.symbol).
            if not card.symbol or not card.timeframe:
                card = replace(
                    card, symbol=card.symbol or symbol, timeframe=card.timeframe or timeframe
                )
        except Exception as exc:  # noqa: BLE001 — bad card JSON; keep cost, drop card
            logger.warning("Strategy card parse failed (non-fatal): %s", type(exc).__name__)
            card = None
        return _CardCall(
            card=card,
            input_tokens=response.usage_prompt_tokens,
            output_tokens=response.usage_completion_tokens,
            cost_usd=cost.total_usd,
        )


def _build_result(
    *,
    success: bool,
    attempts: list[GenerationAttempt],
    t0: float,
    budget_usd: float = DEFAULT_MAX_USD_PER_SESSION,
    budget_exhausted: bool = False,
    card_call: _CardCall | None = None,
) -> GenerationResult:
    """Assemble the public-facing result. Token + USD totals roll up across all
    attempts PLUS the best-effort card call, so the reported cost matches real
    spend (a 3-retry session + a card call reports the full amount)."""
    elapsed = time.perf_counter() - t0
    last_code = attempts[-1].extracted_code if attempts else ""
    card_call = card_call or _CardCall()
    total_in = sum(a.input_tokens for a in attempts) + card_call.input_tokens
    total_out = sum(a.output_tokens for a in attempts) + card_call.output_tokens
    total_usd = sum(a.cost_usd for a in attempts) + card_call.cost_usd
    return GenerationResult(
        success=success,
        code=last_code,
        attempts=tuple(attempts),
        elapsed_seconds=elapsed,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_usd=total_usd,
        budget_usd=budget_usd,
        budget_exhausted=budget_exhausted,
        card=card_call.card,
    )


# ── A fake client used by tests + the unit suite ────────────────


@dataclass
class _FakeLLMResponse:
    """Drop-in replacement for :class:`LLMResponse` in offline tests.

    Defined here (rather than in the test module) so consumers
    across multiple test files can re-use it without copy-paste.
    Marked private — public callers should use the real
    :class:`LLMResponse`.
    """

    content: str
    usage_prompt_tokens: int = 0
    usage_completion_tokens: int = 0
    finish_reason: str = "stop"
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    model: str = "fake"
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_blocks: list[dict[str, object]] = field(default_factory=list)


@dataclass
class ScriptedFakeLLM:
    """LLM stub returning a pre-scripted sequence of responses.

    Used by ``test_strategy_architect_service.py`` to exercise the
    agentic loop without real LLM calls. ``responses`` is consumed
    in order; ``chat`` records the messages it was called with so
    tests can inspect the re-prompt content.
    """

    responses: list[str]
    calls: list[list[LLMMessage]] = field(default_factory=list)
    tokens_per_response: tuple[int, int] = (100, 50)  # (input, output)

    async def chat(  # noqa: D401 — matches LLMClient.chat signature
        self,
        messages: list[LLMMessage],
        *,
        tools: object | None = None,
        tool_choice: object = "auto",
        effort_hint: str | None = None,
    ) -> LLMResponse:
        """Return the next scripted response. Records the messages
        for test inspection. Raises ``IndexError`` if the test under-
        provisioned its responses list — surface this as a loud
        failure instead of silently looping the last response."""
        self.calls.append(list(messages))
        idx = len(self.calls) - 1
        if idx >= len(self.responses):
            raise IndexError(
                f"ScriptedFakeLLM exhausted: {len(self.responses)} responses "
                f"provided, but call #{idx + 1} requested"
            )
        content = self.responses[idx]
        in_toks, out_toks = self.tokens_per_response
        return LLMResponse(
            content=content,
            usage_prompt_tokens=in_toks,
            usage_completion_tokens=out_toks,
            finish_reason="stop",
            model="fake",
        )
