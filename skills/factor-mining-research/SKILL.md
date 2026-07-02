---
name: factor-mining-research
description: Run, extend, and review the Web3 research sandbox factor-mining workflow. Use when working on /backtests factor mining, GP/ML/template/LLM alpha proposal generation, factor feature libraries, mined-factor backtests, IC/RIC validation, overfit warnings, or Codex course exercises that need reproducible factor discovery under src/factor_mining/.
---

# Factor Mining Research

Use this skill to treat factor mining as an auditable research workflow, not as a signal generator.

## Core Workflow

1. Inspect the current implementation before changing behavior:
   - `src/factor_mining/features.py`
   - `src/factor_mining/service.py`
   - `src/factor_mining/templates.py`
   - `src/factor_mining/llm.py`
   - `src/backtest/rolling/strategies/mined_factor.py`
   - `src/web/src/pages/trading/BacktestsPage.tsx`
2. Classify the request:
   - feature-library expansion;
   - GP/ML/template search behavior;
   - LLM proposal generation;
   - validation/reporting;
   - mined-factor backtest integration;
   - UI controls or result display.
3. Keep every new factor point-in-time. Do not use future labels, future prices, future rolling windows, or post-split statistics in features.
4. Route all candidates through the same validation path: train/test chronological split, IC or RIC, quintile spread, turnover proxy, t-stat/p-value, rank autocorrelation, overfit gap, and warnings.
5. Preserve deterministic fallback behavior. LLM proposals may improve candidate generation, but the sandbox must work without network or API keys.
6. Verify with targeted tests first, then project verification:
   ```powershell
   py -m pytest tests/test_factor_mining.py
   py scripts/course.py verify
   ```

## Implementation Rules

- Put reusable feature definitions in `build_feature_matrix`; return numeric series aligned to candle index.
- Add interpretable formula templates to `templates.py`; serialize expression candidates with `expr_to_dict`.
- Add LLM proposal logic only as constrained JSON candidate generation. Sanitize feature names and weight ranges before evaluation.
- For factor specs:
  - expression sources: `gp`, `template`;
  - weight sources: `ml`, `llm`;
  - risk factors set `application: position_scale`;
  - return factors may expose `backtest_spec`.
- Do not claim a factor works because an LLM suggested it. Only validated test metrics and backtest output count as evidence.
- Do not import `vendor/` from `src/`.

## External Patterns

Read [references/factor-mining-patterns.md](references/factor-mining-patterns.md) when adding new mining capabilities, LLM behavior, or factor families. It summarizes public approaches worth borrowing without copying code.

## Output Checklist

When reporting factor-mining work, include:

- changed factor families or candidate sources;
- mode support: `gp`, `ml`, `template`, `llm`, `both`, `all`;
- number of features exposed by `build_feature_matrix`;
- whether LLM uses live API or fallback templates;
- leader method and test IC/RIC;
- overfit warnings and limitations;
- exact commands run and whether they passed.
