# hekswerk-scry

A workbench for untangling convoluted, machine-written mathematical proofs into steps
a person can follow.

Machine-written proofs often work but take strange detours. Scry turns a proof into a
map of steps, shows you where to look first, lets you poke at it to see what relies on
what, and lets you safely swap a tangled group of steps for a shorter route. It never
claims more than it has actually checked.

> **Status: Checkpoint 1 of 6.** Everything Scry can check today is *wiring*: whether
> the facts feed into each other correctly. It does not read the math yet, so nothing
> it shows counts as proven. Lean arrives in Checkpoint 2.

## Try it

Needs Python 3.13 and nothing else.

```bash
make demo                      # walk through the bundled example
```

Or install the `scry` command:

```bash
python3 -m pip install -e '.[dev]'
scry demo
scry check  path/to/map.json
scry scan   path/to/map.json
scry what-if path/to/map.json --remove-step cube-split
scry what-if path/to/map.json --drop-fact "x >= 0"
```

The bundled example is in
[`src/hekswerk_scry/examples/shifted_fraction.json`](src/hekswerk_scry/examples/shifted_fraction.json).
It proves that `x / (x + 7)` is never 1 when `x >= 0`, but shows that `x + 7 > 0` the
long way round, through cubes and squares.

## The ideas, in plain English

- **Proof map**: a proof stored as steps. Each step **assumes** some facts and
  **proves** one fact. Arrows show which steps use facts from which. The map also says
  what you may assume at the start (**starting facts**) and what you want to reach (the
  **goal**).
- **Views**: each step can be shown in plain English, as math, as Lean code, or any mix.
- **Wiring check**: confirms every fact a step needs is a starting fact or comes from a
  step it points to. It does not read the math.
- **Chokepoint**: a step that every route to the goal passes through. Read these first.
- **Knot**: a group of steps that only exists to produce one result. It can be swapped
  for a shorter route with the same inputs and the same result.
- **Unused step**: a step that doesn't lead to the goal.
- **What-If test**: remove a step or a starting fact and see which steps lose a fact
  they rely on.
- **Simplification card**: a proposal to swap a group of steps for a shorter route. It
  is refused if it brings in a new assumption, stops providing something the rest of
  the proof needs, or targets steps that have changed since it was drafted. It is
  re-checked at the moment of the swap. Swapped-out steps are archived, not deleted.

Every result says who produced it. Step statuses are **Lean-checked**, **Wiring checked
(not proven)**, **Wiring broken**, or **Not checked**. AI-produced claims will be
labelled **AI's reading** and must cite their evidence.

## Proof map files

Plain JSON, strictly checked: unknown fields are rejected so typos don't go unnoticed.

```json
{
  "format": "hekswerk-scry/proof-map",
  "version": 1,
  "map_id": "shifted-fraction",
  "title": "A fraction that never reaches 1",
  "starting_facts": ["x >= 0"],
  "goal": "x / (x + 7) != 1",
  "goal_step_id": "fraction-not-one",
  "steps": [
    {
      "id": "less-than-shift",
      "title": "x is less than x + 7",
      "assumes": [],
      "proves": "x < x + 7",
      "depends_on": [],
      "views": {"plain_english": "...", "math": "...", "code": "..."}
    }
  ]
}
```

Facts are compared as text after tidying spaces, so `"x + 7 > 0"` and `"x+7>0"` are
different facts. Deciding when two formulas mean the same thing is Lean's job.

## Roadmap

| # | What you get | Status |
|---|---|---|
| 1 | Proof maps, wiring check, scanner, What-If tests, Simplification cards, receipts, CLI | Done (this checkpoint) |
| 2 | Lean runner and exporter: a Lean file in, a proof map out; What-If tests re-checked by Lean | Next |
| 3 | Simplification cards checked by Lean before any swap | |
| 4 | AI helper via OpenRouter that tests your hunches before answering | |
| 5 | Three-pane browser workbench | |
| 6 | Importing written proofs and finding where English and code disagree | |

## For contributors and coding agents

Read [`AGENTS.md`](AGENTS.md) first. Run `make check` (ruff, `mypy --strict`, tests)
before finishing any change.
