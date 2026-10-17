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
| `LEAN_CHECKED` | Lean-checked | Only the Lean runner (Checkpoint 2) |
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

## 3. Never swap steps without re-checking at the moment of the swap

- A Receipt is a record, not a permission slip. Nothing applies a change because a
  receipt says it passed: `apply_card` re-runs the full check itself, every time.
- A Simplification card remembers the exact contents of the steps it replaces. If any
  of them change, the card is **stale** and must be redrafted.
- A swap may not bring in new assumptions, and it must keep providing every fact the
  rest of the proof takes from the replaced steps.
- Replaced steps are never deleted. They move to `ProofMap.archived_steps`, and the
  swap is recorded in `ProofMap.history`.

## 4. Truth over flattery

Any AI feature must test a person's hunch against a real check before answering. If
the hunch breaks something, report the breakage instead of agreeing.

## 5. Standard library only at runtime

The `hekswerk_scry` package uses only the Python 3.13 standard library. Development
tools (ruff, mypy) are fine. Lean will be an external program Scry runs, not a
Python dependency. No FastAPI, Pydantic, SQLAlchemy, LangChain, or npm bundlers.

## 6. Fail closed, in plain words

Reject anything unexpected (unknown fields in a file, an ID that does not exist) with
a message that says what is wrong and how to fix it. Never guess and carry on.

## How work is organised

The project is built checkpoint by checkpoint (see `README.md`). After each checkpoint
the work is pushed and stops for the owner's review before the next one begins.

## Quality gates

Before finishing any change, run:

```bash
make check
```

It runs ruff, `mypy --strict`, and the full test suite. All three must pass with no
warnings. If a tool is missing, `make check` fails and says how to install it; it
never skips silently.
