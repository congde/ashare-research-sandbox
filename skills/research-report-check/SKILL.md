---
name: research-report-check
description: Check quantitative-trading research reports for traceable evidence, declared assumptions, reproducible commands, failure records, and research-only safety boundaries. Use when reviewing a market summary, LLM signal report, backtest report, or combined research delivery before publication or handoff.
---

# Research Report Check

Review the report as evidence, not as persuasive writing.

## Workflow

1. Identify every market claim, signal claim, performance claim, and recommendation-like sentence.
2. Classify each claim as fact, calculation, interpretation, decision, or unknown.
3. Require facts and calculations to name their source, time range, field definition, and generating command.
4. Require LLM output to name the model or fallback engine, supplied context, structured result, and failure state.
5. Require backtest output to name the sample, strategy version, parameters, fees, slippage, position rules, exits, and risk metrics.
6. Confirm the report preserves conflicting evidence, failed checks, limitations, and non-passed items.
7. Reject real-account access, wallet authorization, order execution, personalized investment advice, or future-return promises.

## Output

Return:

- `pass`, `revise`, or `reject`;
- a claim ledger with evidence paths;
- missing or ambiguous evidence;
- critical failures and safety-boundary violations;
- the smallest changes needed before handoff.

Do not turn missing evidence into plausible prose. Do not treat LLM confidence as a probability of profit. Do not treat historical performance as evidence of future returns.
