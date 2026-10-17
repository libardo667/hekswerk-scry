# hekswerk-scry: rules for anyone working in this repository

Scry is a workbench for untangling convoluted, machine-written mathematical proofs
into steps a person can follow. These rules apply to every human and AI agent working
here. When a rule and a request conflict, stop and ask the owner.

## 1. Plain technical English everywhere

A sharp, curious adult who is not a specialist should be able to read any class name,
field, message, report, or label and understand it.

- Do not bring in specialist jargon (`dominator_tree`, `ablation`, `diegetic`,
  `sycophancy`) for names, fields, or anything a user sees. Explaining an algorithm
  in a code comment is fine.
- Use the established vocabulary:

  | Term | Meaning |
  |---|---|
  | `ProofMap` | A whole proof, stored as steps connected by "uses a fact from" arrows |
  | `ProofStep` | One step. It has a `StepContract` and `StepViews` |
  | `StepContract` | `assumes` (facts the step needs) and `proves` (the one fact it gives back) |
  | `StepViews` | Up to three ways of showing a step: `plain_english`, `math`, `code` |
  | starting facts | What the theorem lets you assume at the start |
  | goal | The fact the whole proof sets out to prove |
  | Chokepoint | A step that every route to the goal passes through |
  | Knot | A group of steps that only exists to produce one result, and could be swapped for a shorter route |
  | unused step | A step that does not lead to the goal |
  | What-If test / Breakage report | Remove something and see which steps lose a fact they rely on |
  | Simplification card | A proposal to swap a group of steps for a shorter route |
  | Receipt | A record of one check: what was checked, by which checker, and the result |

## 2. Only Lean may say "proven"

Every claim Scry shows must say who made it. Step statuses use exactly these labels:

| Status | Label shown to people | Who can produce it |
|---|---|---|
| `LEAN_CHECKED` | Lean-checked | Only a real Lean run (`hekswerk_scry/lean/runner.py`) |
| `LEAN_REJECTED` | Lean found an error | Only a real Lean run |
| `WIRING_CHECKED` | Wiring checked (not proven) | The built-in wiring check |
| `WIRING_BROKEN` | Wiring broken | The built-in wiring check |
| `NOT_CHECKED` | Not checked | Anything that could not run a check |

Claims made by an AI model are labelled **AI's reading** and must cite the evidence
they rest on (Checkpoint 4).

- The built-in wiring check only follows which facts feed into which steps. It never
  reads a step's math, code, or English, and it must stay that way.
- Do not add regex or keyword "checks" of math, code, or prose that present their
  results as verification. That was tried in the first draft and approved broken
  proofs (see `docs/decisions/0001-only-lean-says-proven.md`).
- A theorem is Lean-checked only when Lean reports no errors, no `sorry`, and no axioms
  beyond the standard three (propext, Classical.choice, Quot.sound). Results labelled
  `CheckKind.LEAN` may only come from `lean/runner.py` actually running Lean; a test
  enforces this.
- A Lean-backed map records the fingerprint of the file it came from. Never check a map
  against a file that has changed since; re-import instead.
- The arrows of a Lean-backed map come from Lean's own record of the finished proof (see
  `docs/decisions/0002-proof-maps-from-lean.md`), never from reading the tactic text.

## 3. Never swap steps without re-checking at the moment of the swap

- A Receipt is a record, not a permission slip. Nothing applies a change because a
  receipt says it passed: `apply_card` re-runs the full check itself, every time.
- A Simplification card remembers the exact contents of the steps it replaces. If any
  of them change, the card is **stale** and must be redrafted.
- A swap may not bring in new assumptions, and it must keep providing every fact the
  rest of the proof takes from the replaced steps.
- Replaced steps are never deleted. They move to `ProofMap.archived_steps`, and the
  swap is recorded in `ProofMap.history`.
- For Lean proofs, a card re-proves one fact and **Lean judges the whole changed file**
  (see `docs/decisions/0003-simplification-cards-for-lean.md`). Applying a card writes a
  new file; never modify the original Lean file.

## 4. Truth over flattery

Any AI feature must test a person's hunch against a real check before answering. If
the hunch breaks something, report the breakage instead of agreeing.

## 5. Standard library only at runtime

The `hekswerk_scry` package uses only the Python 3.13 standard library. Development
tools (ruff, mypy) are fine. Lean is an external program Scry runs, not a Python
dependency; its workspace lives in `lean/`, pinned to Lean v4.10.0-rc2 and the Mathlib
release of the same name (the versions AlphaProof's published proofs compile on). No
FastAPI, Pydantic, SQLAlchemy, LangChain, or npm bundlers.

**Lean files are programs.** Compiling one can run code written in it. Only run Scry's
Lean features on files you trust, or somewhere isolated.

## 6. Fail closed, in plain words

Reject anything unexpected (unknown fields in a file, an ID that does not exist) with
a message that says what is wrong and how to fix it. Never guess and carry on.

## How work is organised

The project is built checkpoint by checkpoint (see `README.md`). After each checkpoint
the work is pushed and stops for the owner's review before the next one begins.

## Tests must be able to fail

A test you have never seen fail is unmeasured. When you add or change a test, break the
code it guards and watch it go red, then restore the code. Prefer invariants and whole
generated artifacts (for example, a complete spliced file) over hand-picked fragments.
Never assert on source text. Python's bytecode cache only notices a source change by
its modification time (to the second) and size, so a same-length edit that is undone
quickly can leave stale code running. Clear `__pycache__` after such edits.

`make mutation-check` breaks the code in known ways and confirms the tests notice. When
you add a test that guards a specific piece of behaviour, add a mutation for it to
`scripts/mutation_check.py`.

## Quality gates

Before finishing any change, run:

```bash
make check
```

It runs ruff, `mypy --strict`, and the full test suite. All three must pass with no
warnings. If a tool is missing, `make check` fails and says how to install it; it
never skips silently.

When you change anything under `src/hekswerk_scry/lean/` or `lean/`, also run
`make lean-test` (it needs Lean; see `make lean-setup`). It runs real Lean, including on
the three AlphaProof proofs, and takes a few minutes.
