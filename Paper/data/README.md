# Paper experiment artifacts

Headline numbers cited in `Paper/main.tex`. Full CSVs and repro scripts stay **local** or under `ai-kia-assistant/mytest/kcbot_test/` (not required in this repo).

## In git (paper branch)

| File | Role |
|------|------|
| `run4_joint_ft_measured.json` | Run 4 **FT joint** — **85.76%** (265/309) |
| `run4_joint_measured_v2.json` | Stock joint **reference** — 67.99% ($N{=}303$) |

## Local / eval repo (not in paper git)

| Artifact | Location |
|----------|----------|
| Top-20 live **81.23%** | `Paper/data/workflow_simple_issueid_eval_chain_aligned_20_live.csv` (local) |
| Top-10 live **78.96%** | `Paper/data/workflow_simple_issueid_eval_chain_aligned_10.csv` (local) |
| FT top-10/20 **85.76%** (#8/#9) | `ai-kia-assistant/mytest/kcbot_test/workflow_simple_issueid_eval_ft_rerank_qwen_top{10,20}_legacy.csv` |
| Live repro scripts | `Paper/data/run_chain_aligned_{10,20,both}.sh` (local; paths tuned to this machine) |

Legacy smoke / projection JSONs remain on branch `paper/kdd-eval-archive` or in existing `Paper/data/` commits.
