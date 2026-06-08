# KDD Paper

## 审阅 / Review（推荐）

**Human-readable draft:** [`REVIEW.md`](REVIEW.md) — Markdown，含 Mermaid 图、表格、C1–C5 映射，适合批注和协作 review。

**LaTeX 投稿稿:** [`main.tex`](main.tex) — 仅用于 Overleaf / KDD 排版编译；日常修改建议先改 `REVIEW.md`，再同步到 `main.tex`。

## Quick start (Overleaf)

1. [New Project → ACM Conference Proceedings Template (sigconf)](https://www.overleaf.com/latex/templates/acm-conference-proceedings-primary-article-template/wbvnghkzwppv)
2. Replace template `main.tex` with this repo's `Paper/main.tex`
3. Upload `Paper/refs.bib` and `Paper/figures/*.tex`
4. Compile with **pdfLaTeX**

## Files

```
Paper/
├── REVIEW.md             # ★ 审阅用 Markdown（优先改这个）
├── main.tex              # KDD LaTeX 投稿稿
├── refs.bib
└── figures/              # TikZ 图源（编译 PDF 用）
```

## Submission checklist

- [x] System architecture figure (Fig. 1, TikZ)
- [x] Retrieval pipeline figure (Fig. 2, TikZ)
- [x] ACM acmart template + anonymous mode
- [x] Anonymized product references (no internal codenames in body)
- [ ] Experimental results tables (deferred)
- [ ] CCS concepts (add before camera-ready)
- [ ] Author / affiliation (remove `anonymous` for camera-ready)

## Anonymization notes

Current draft removes internal codenames (e.g., KC-Bot) from the main text. Before de-anonymizing for camera-ready, restore deployment-specific details in Section 5 if desired.

## Local evaluation

- **FAQ issue-ID pipeline (Runs 1–4):** [`data/README.md`](data/README.md) + `scripts/kcbot_test/paper_faq_pipeline_eval.py`
- **Full agent acceptance:** `scripts/kc_bot_eval/README.md`
