# Ticket: evaluate Tencent Docs to Feishu Docs migration

You need a short research report for an 8-person project team deciding whether
to pilot a migration from 腾讯文档 to 飞书文档.

## Input materials

- Official 腾讯文档 product documentation
- Official 飞书文档 product and pricing documentation
- A representative project space for a later migration test

## Output

Save a report with sections: Facts, Inferences, Recommendations, Unknowns.
Use traceable IDs:

- Facts use `F1`, `F2`, ... and cite a source URL.
- Inferences use `I1`, `I2`, ... and declare `Supports: F...`.
- Recommendations use `R1`, `R2`, ... and declare `Supports: I...`.
- Unknowns use `U1`, `U2`, ... and include both `Impact:` and `Next check:`.

Do not invent pricing, migration fidelity, or team requirements. A source URL
is not enough by itself: manually record whether at least two important Facts
are fully, partially, or not supported by their source.

## Done when

- `verify.py` passes against your report and research-package files;
- the source review log contains at least two reviewed Facts;
- at least one reviewed Fact concerns pricing;
- every recommendation can be traced back to Facts through an Inference.
