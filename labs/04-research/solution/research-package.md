# Research package: note-app comparison

## Research question map

| ID | Question | Why it matters | Preferred source | Stop condition |
|---|---|---|---|---|
| Q1 | How are notes stored? | Affects local ownership and archive strategy | Official storage documentation | Official mechanism is documented |
| Q2 | What pricing roles apply to personal use and sync? | Affects operating-cost comparison | Official pricing pages | Current plan and add-on roles are documented |
| Q3 | Does a representative export preserve links and attachments? | Could make migration cost unacceptable | A real export test | One representative project is inspected |

## Source cards

### S1

- URL: https://obsidian.md/pricing
- Source role: official pricing
- Retrieved: 2026-06-11
- Supports: Obsidian is free to use and lists Sync and Publish as optional paid add-ons.
- Does not support: The total cost of a self-managed backup workflow or whether Obsidian is the better choice.
- Freshness or access concern: Pricing can change and should be rechecked before a purchase decision.

### S2

- URL: https://www.notion.so/pricing
- Source role: official pricing
- Retrieved: 2026-06-11
- Supports: Notion lists Free, Plus, Business, and Enterprise plans.
- Does not support: Whether a specific reader should stay on Notion.
- Freshness or access concern: The page redirects by locale and displays localized prices.

## Claim ledger

| ID | Claim | Type | Supports | Status |
|---|---|---|---|---|
| F1 | Obsidian is free to use and lists paid Sync and Publish add-ons | Fact | S1 | accepted |
| F2 | Notion lists Free, Plus, Business, and Enterprise plans | Fact | S2 | accepted |
| I1 | Sync cost should be compared separately from the base license | Inference | F1, F2 | accepted |
| R1 | Compare sync and backup workflows before deciding | Recommendation | I1 | accepted |
| U1 | Export fidelity for representative notes is unknown | Unknown | Q3 | open |
| F5 | Obsidian is always cheaper | Fact | S1 | rejected: source does not support total cost |

## Source review log

| Fact ID | Review result | What the source supports | Required rewrite |
|---|---|---|---|
| F1 | fully supported | Free use plus optional paid Sync and Publish add-ons | None |
| F2 | fully supported | Free, Plus, Business, and Enterprise plan names | None |

## Handoff

- Questions covered: Q1 and Q2 have official-source candidates; Q2 pricing roles were manually reviewed.
- Questions still open: Q3 requires a representative export test.
- Sources that could not be accessed: None recorded in this fixture.
- Claims rejected or downgraded: F5 was rejected because a pricing page cannot prove total cost.
- Next action: Run the representative export test before making a migration decision.
