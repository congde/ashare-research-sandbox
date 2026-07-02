---
name: research-report-check
description: Check quantitative-trading research reports for traceable evidence, declared assumptions, reproducible commands, failure records, and research-only safety boundaries. Use when reviewing a market summary, LLM signal report, backtest report, or combined research delivery before publication or handoff.
---

# Research Report Check

Review the report as evidence, not as persuasive writing.

## Required inputs

Ask for or locate:

- the report draft or handoff note;
- source paths, snapshot names, time ranges, and field definitions behind market claims;
- commands that generated charts, backtests, audits, or risk reports;
- model name or fallback engine for LLM-derived signals;
- backtest assumptions: sample, strategy version, parameters, costs, position rules, exits, and risk metrics;
- known failed checks, missing data, rejected orders, limitations, and manual decisions.

If the report is missing these inputs, do not fill the gaps with plausible prose. Mark the missing items in the output ledger and choose `revise` or `reject` according to the decision rules below.

## Workflow

1. Identify every market claim, signal claim, performance claim, and recommendation-like sentence.
2. Classify each claim as fact, calculation, interpretation, decision, or unknown.
3. Require facts and calculations to name their source, time range, field definition, and generating command.
4. Require LLM output to name the model or fallback engine, supplied context, structured result, and failure state.
5. Require backtest output to name the sample, strategy version, parameters, fees, slippage, position rules, exits, and risk metrics.
6. Confirm the report preserves conflicting evidence, failed checks, limitations, and non-passed items.
7. Reject real-account access, wallet authorization, order execution, personalized investment advice, or future-return promises.

## Decision rules

- Return `pass` only when every material fact and calculation has traceable evidence, assumptions are declared, failed checks are preserved, and no safety-boundary violation appears.
- Return `revise` when the report is research-only but has missing commands, unclear fields, missing failure records, weak assumptions, or ambiguous wording that can be repaired before handoff.
- Return `reject` when the report asks for live trading, wallet/account access, order execution, personalized investment advice, future-return promises, or when key claims cannot be traced to evidence.

## Output

Return:

- `pass`, `revise`, or `reject`;
- a claim ledger with claim type, evidence path, command, status, and decision impact;
- missing or ambiguous evidence, grouped by source, command, assumption, failure record, and safety boundary;
- critical failures and safety-boundary violations;
- the smallest changes needed before handoff.

Use this shape:

```text
decision: pass | revise | reject
claim_ledger:
  - claim:
    type: fact | calculation | interpretation | decision | unknown
    evidence:
    command:
    status: supported | missing | ambiguous | unsafe
missing_evidence:
critical_failures:
smallest_changes:
handoff_boundary:
```

Do not turn missing evidence into plausible prose. Do not treat LLM confidence as a probability of profit. Do not treat historical performance as evidence of future returns.
