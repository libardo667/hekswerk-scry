# Decision 0002: How a Lean proof becomes a proof map

**Status:** accepted for Checkpoint 2.

## The question

A Lean tactic proof is a list of tactics, often nested (`·` bullets, `have ... := by`,
`by` blocks inside terms). Scry needs steps and "uses a fact from" arrows. Reading the
tactic *text* can't give honest arrows: `norm_num [*] at *` may use any hypothesis or
none, and machine-written proofs are full of such calls.

## Decision

The arrows come from Lean's own record of the finished proof. The exporter
(`lean/ScryExport/Export.lean`) elaborates the file and, for each tactic step, reads:

- **the goal it works on**: a goal that was open before the tactic and filled in by it;
- **its own piece of the finished proof**: Lean's final record of the whole proof, with
  every *other* step's goal temporarily un-filled, read back at this step's goal;
- **the holes in that piece**: goals left for other steps;
- **the hypotheses that piece uses**, and the hypotheses it introduces together with
  the term that justifies them (`have`, `suffices`, `obtain := ...`).

Python (`hekswerk_scry/lean/importer.py`) then builds the map:

| Lean | Proof map |
|---|---|
| A tactic step | A step that proves its goal ("Goal n: ...") assuming the goals it leaves and the hypotheses it uses |
| A justified hypothesis `h : T` | A separate step "Why h holds" proving "h : T" from what its justification relies on; users of `h` depend on it |
| A hypothesis from the theorem statement | A starting fact |
| A hypothesis from `intro`, `cases`, ... | Context: no fact, no arrow |
| A hypothesis passed along unchanged under a new identity (as `rw ... at h` does) | The original hypothesis |

Which tactics count as steps: every tactic written in the source, except pure layout
(sequences, `·` bullets, parentheses, `focus`). Tactics that run inside another step's
combinator (`t₁ <;> t₂`, `repeat`, `first`) belong to that step, except those written
inside one of the step's own `by` blocks, which are steps of their own.

## Details that matter (each one found on real proofs)

- **Copied `by` blocks.** When Lean finishes a term like `pow_pos (by linarith) 3`, it
  copies the finished block into the surrounding proof, leaving no hole. The exporter
  restores the hole by matching the copy, and only against blocks written inside that
  same step, matching each copy once (two identical `by left` blocks are two holes).
- **Abandoned attempts.** Tactics such as `use` try things and back out. Lean keeps a
  record of those attempts, but their goals are not part of the finished proof, so they
  are ignored.
- **Goals Lean closes itself.** A leftover goal that no step works on but that is filled
  in in the finished proof (by unification, instance search, or a tactic's own clean-up)
  counts as part of the step that left it. So do `by` blocks that tactics generate for
  themselves, as opposed to ones written in the source.

## What "unused" means for a Lean map

A step is unused when Lean's finished proof doesn't rely on what it proves. That is not
the same as "you can delete it": a hint given to `nlinarith` must still be proved for the
file to compile, even if `nlinarith` never used it. The scanner says this, and a Lean
What-If test (make the step do nothing, re-run Lean) gives the definitive answer. On P2,
every tactic the scanner flagged turned out to be needed for compilation in exactly this
way.

## Known limitations

- **One Lean version.** The workspace is pinned to Lean v4.10.0-rc2 so that AlphaProof's
  published proofs compile. The exporter uses Lean internals and may need changes to run
  on other versions.
- **Tactic proofs only.** A theorem proved by a term (no `by`) is rejected with a plain
  message.
- **Goal-shaped maps.** Tactic proofs are trees of goals, so their maps have few
  chokepoints and knots that tend to be whole branches. Better ways to point a reader at
  the interesting parts of large Lean maps are future work.
- **What-If tests only make a step do nothing (`skip`).** Dropping a starting fact would
  mean editing the theorem statement, which Scry doesn't do yet.
- **Checked against AlphaProof P1, P2, and P6** and Scry's own example. Other proof
  styles may expose cases the exporter doesn't handle yet. When the wiring check fails on
  a freshly imported map, that is the signal.
