# Ticket: compare offline-first note apps

You need a short research report to decide whether to migrate personal notes to
Obsidian or stay on Notion.

## Input materials

- Official Obsidian pricing and sync documentation
- Official Notion pricing and platform documentation

## Output

Save a report with sections: Facts, Inferences, Recommendations, Unknowns.
Use traceable IDs:

- Facts use `F1`, `F2`, ... and cite a source URL.
- Inferences use `I1`, `I2`, ... and declare `Supports: F...`.
- Recommendations use `R1`, `R2`, ... and declare `Supports: I...`.
- Unknowns use `U1`, `U2`, ... and include both `Impact:` and `Next check:`.

Do not invent pricing or platform support. A source URL is not enough by
itself: manually record whether at least two important Facts are fully,
partially, or not supported by their source.

## Done when

- `verify.py` passes against your report and research-package files;
- the source review log contains at least two reviewed Facts;
- at least one reviewed Fact concerns pricing;
- every recommendation can be traced back to Facts through an Inference.
