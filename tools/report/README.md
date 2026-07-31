# report — regenerable presentation decks

Two PowerPoint decks, generated from live project state rather than hand-edited. Both pull
their figures from `tools/dashboard/server.py:collect()`, so KOL counts, dataset sizes, GPU
and service status are always current — regenerate instead of editing slides.

```powershell
.\.venv\Scripts\python.exe tools\report\make_progress_deck.py   # 10 slides, technical
.\.venv\Scripts\python.exe tools\report\make_exec_deck.py       # 14 slides, management
```

Needs `pip install python-pptx`.

| Deck | Audience | Covers |
|---|---|---|
| `docs/AI-KOL-Progress-Report.pptx` | Technical / team | Architecture, delivered tooling, verification results, the environment blockers in detail, next steps |
| `docs/AI-KOL-Executive-Review.pptx` | Management | Resources, architecture, models in plain language, **cost model**, improvement areas, a 4 h/day week plan, roadmap, learnings |

## Cost assumptions (executive deck)

All cost inputs live in the `COST` dict at the top of `make_exec_deck.py` so they are visible
and reviewable, not buried in slide text. Override the main ones from the CLI:

```powershell
.\.venv\Scripts\python.exe tools\report\make_exec_deck.py --rate-twd 3.5 --hourly-twd 250
```

| Input | Default | Basis |
|---|---|---|
| Electricity | NT$4.00 / kWh | assumption — adjust to your tariff |
| GPU price / life | NT$20,000 / 36 months | street price, straight-line |
| Intern cost | NT$200 / h | placeholder for finance to replace |
| Power draw | 13 W serving, ~100 W training | **measured on this machine** |
| GPU time per voice | 20 min | **measured** end-to-end |

Power and timing are measured, not estimated. The resulting figures were cross-checked against
an independent calculation before the deck was shipped.

Vendor/SaaS prices are deliberately **not** quoted as numbers — they move often and were not
verified. The comparison slide makes the structural argument instead (SaaS cost scales with
output volume, ours does not), and says explicitly that figures need verifying before any
build-vs-buy sign-off.

## Note on review

Neither PowerPoint nor LibreOffice is installed on this machine, so slides cannot be rendered
to images here. Layout is validated programmatically instead (slide-bounds check: 0 shapes out
of bounds on both decks). **Open each deck once before presenting** to confirm nothing wraps
awkwardly in your PowerPoint version.
