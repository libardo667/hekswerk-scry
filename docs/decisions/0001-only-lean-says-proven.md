# Decision 0001: Only Lean may say "proven"

**Status:** accepted by the owner, Checkpoint 1.

## Background

The first draft of Checkpoint 1 had a built-in checker that matched fact names as
text, looked for divisions with a regular expression, and compared English with code
by searching for keywords. It labelled steps `VERIFIED` and issued receipts the demo
called "cryptographic".

When the draft was run, its tests and type checks passed, but nine small probes showed
the checker approving broken proofs:

| # | Input | What the draft said |
|---|---|---|
| P1 | A one-step "proof" of the Riemann Hypothesis that assumes it, with code `sorry` | Verified |
| P2 | A step whose math was changed to `2 + 2 = 5` | All steps verified |
| P3 | The divide-by-zero guard removed, then re-declared by the step that needed it | Passed |
| P4 | Division by a value that can be zero, written without parentheses | Passed |
| P5 | Division by `(core)`, "guarded" by a condition about `vortex_core + 7` | Passed (substring match) |
| P6 | English reworded slightly, or the word "energy" added as a code comment | No mismatch warning |
| P7 | A card applied after one of its target steps was rewritten | Applied |
| P8 | A card with a nonsense declared contract | Approved (field never checked) |
| P9 | A hand-made receipt labelled as coming from Lean | Accepted |

Its own demo told users that a load-bearing "+7" term was "redundant search noise".

## Decision

1. Only a Lean check may mark a step as proven. The built-in check is a *wiring* check:
   it follows which facts feed which steps and never reads math, code, or English. Its
   best result is labelled "Wiring checked (not proven)".
2. No regex or keyword "checks" of math, code, or prose that present themselves as
   verification. Disagreements between English and code are judgements, and will come
   from the AI helper labelled "AI's reading", with evidence (Checkpoint 4 and 6).
3. Receipts are records, not permission slips. Applying a card always re-runs the check.
4. Safety conditions (like "the bottom of a fraction isn't zero") are ordinary facts. A
   step can't grant itself one.
5. A card's inputs and outputs are worked out from the map, never declared by the card.
   A card goes stale if any step it replaces changes.

## Consequences

- Statuses are computed by checkers, never stored in maps or files.
- `CheckKind` has a single member (`WIRING`) until the Lean runner exists, so nothing
  can be labelled as Lean-checked before Lean has run.
- Each of P1 to P9 is a permanent test in `tests/test_review_regressions.py`.
- Lean becomes a required external tool for anything marked proven (Checkpoint 2).
