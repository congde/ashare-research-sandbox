# Factor Mining Patterns

Use these public patterns as design inspiration. Do not copy code or claim equivalence.

## Borrowable Patterns

### Skill and memory loop

FactorMiner-style systems frame factor mining as a set of reusable skills plus a memory library of past attempts. Borrow the pattern by keeping candidate source, formula/weights, validation metrics, warnings, and trial counts in the payload or ledger. Do not let memory replace chronological validation.

Useful in this repo:

- persist enough `trial_summary` context to discourage repeated overfit searches;
- show the candidate source (`gp`, `ml`, `template`, `llm`);
- preserve rejected or weak candidates in warnings.

### Formula alpha templates

WorldQuant-style formulaic alphas use simple operators over price, volume, ranks, delays, correlations, and rolling statistics. Borrow the pattern by maintaining a curated template set in `src/factor_mining/templates.py`, then scoring those templates with the same train/test metrics as GP and ML.

Useful in this repo:

- keep templates interpretable;
- prefer point-in-time operators: rank, delay, rolling z-score, momentum, reversal, volatility, volume pressure;
- serialize candidates into existing mined-factor specs.

### Qlib-style feature libraries

Qlib popularized organized feature handlers such as Alpha158/Alpha360 for repeatable ML experiments. Borrow the pattern by grouping feature families and exposing feature counts so users can see the search space.

Useful in this repo:

- group features by momentum, reversal, volatility, volume/liquidity, trend, candle anatomy, support/resistance, and interactions;
- keep features deterministic and cheap enough for the course sandbox;
- test only counts and alignment, not expected profitability.

### Alpha generation with graph or lineage constraints

AlphaGen and AlphaForge-like systems emphasize structured alpha expressions, combination, and avoiding redundant candidates. Borrow the pattern by recording candidate formulas and adding future similarity/originality checks before accepting new templates.

Useful in this repo:

- penalize formula complexity in GP;
- show expression text for templates and GP;
- add deduplication if templates start producing near-identical signals.

### LLM proposal, deterministic validation

LLM alpha systems such as AlphaForge/AlphaAgent use the model to propose ideas, then apply strict validation. Borrow only that boundary: LLM may propose constrained JSON candidates; the engine must sanitize feature names and weights, evaluate metrics, and fall back offline.

Useful in this repo:

- require `weights` over known feature names only;
- clamp numeric weights;
- never execute arbitrary LLM code;
- expose `proposal_source` as `llm` or `fallback_templates`;
- treat LLM output as hypothesis text, not evidence.

## Source Links

- Microsoft Qlib: https://github.com/microsoft/qlib
- Qlib data handlers and alpha feature examples: https://qlib.readthedocs.io/
- WorldQuant 101 Formulaic Alphas paper: https://arxiv.org/abs/1601.00991
- AlphaGen repository: https://github.com/RL-MLDM/alphagen
- AlphaForge paper page: https://arxiv.org/
- AlphaAgent paper page: https://arxiv.org/

## Validation Guardrails

Accept a mined factor only when:

- train/test split is chronological;
- test IC/RIC is shown separately from train IC/RIC;
- overfit gap is visible;
- quintile spread and turnover proxy are available;
- risk factors are not treated as directional return factors;
- backtest assumptions remain visible.
