# hekswerk-scry

A workbench for untangling convoluted, machine-written mathematical proofs into steps
a person can follow.

Machine-written proofs often work but take strange detours. Scry turns a proof into a
map of steps, shows you where to look first, lets you poke at it to see what relies on
what, and lets you safely swap a tangled group of steps for a shorter route. It never
claims more than it has actually checked.

> **Status: Checkpoint 5.** Scry can turn a Lean proof into a proof map, ask Lean whether
> the theorem is proven, run What-If tests that Lean judges, and swap any fact's proof for a
> new one, which Lean must accept before anything changes. An AI helper works through the
> same tools with you. Scry also checks the other half of trust: whether a formal
> *statement* says what its paper claims. It works on Lean v4.10 (AlphaProof) and v4.34.1
> (OpenAI's mathematics repository). Maps written by
> hand (without Lean) can still only be *wiring checked*: Scry follows how the facts feed
> into each other but does not read the math, so nothing in them counts as proven.

## Try it

Needs Python 3.13 and nothing else. With [uv](https://docs.astral.sh/uv/), for example:

```bash
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -e '.[dev]'
make check                     # the Makefile uses .venv automatically when it exists
```

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

With Lean installed (see [Setting up Lean](#setting-up-lean)):

```bash
make lean-demo                 # the same example as a real Lean proof, checked by Lean
scry fetch-alphaproof          # download DeepMind's AlphaProof proofs from IMO 2024
scry lean-import lean/fetched/alphaproof/P2.lean imo_2024_p2 -o p2.json
scry lean-check p2.json        # is the theorem proven? (Lean decides)
scry scan p2.json
scry what-if p2.json --remove-step s7 --lean   # make step s7 do nothing; Lean judges
scry lean-region p2.json --fact s7             # what re-proving step s7's fact would replace
scry lean-card p2.json --fact s7 --tactics NEW_TACTICS.lean --apply P2_simpler.lean
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

Every result says who produced it. Step statuses are **Lean-checked**, **Lean found an
error**, **Wiring checked (not proven)**, **Wiring broken**, or **Not checked**.
AI-produced claims will be labelled **AI's reading** and must cite their evidence.

## Proofs from Lean

`scry lean-import` asks Lean itself how a tactic proof fits together. For every tactic it
records which goal the tactic worked on, which goals it left for later, and which
hypotheses its piece of the *finished* proof really uses. So the arrows show what the
proof actually relies on, not what the tactic text appears to mention. Each `have`-style
hypothesis gets its own small "Why h holds" step, so a lemma that is proved but never
used shows up as an unused step. The details and known limitations are in
[`docs/decisions/0002-proof-maps-from-lean.md`](docs/decisions/0002-proof-maps-from-lean.md).

- **Lean-checked** means Lean accepts the theorem with no errors, no `sorry`, and no
  axioms beyond Lean's standard three (propext, Classical.choice, Quot.sound).
- **Lean What-If tests** replace a step with `skip` (a tactic that does nothing) in a
  copy of the file and re-run Lean. "Not needed" means Lean still accepts the whole proof.
- **Unused**, for a Lean map, means Lean's finished proof doesn't rely on the step's
  result. The code may still need it to compile (a hint that has to be proved even though
  the tactic it was given to didn't use it); a Lean What-If test settles that.

### Simplification cards for Lean proofs

`scry lean-card` re-proves **one fact** (a goal, or a `have`-style lemma) with new tactics
you supply. Scry works out the fact's whole proof: the steps whose results are needed
only inside it, plus the `have` lines that become dead without it. It splices the new
tactics in, and Lean checks the whole changed file. Only if Lean accepts it does
`--apply` write the simpler proof to a new file; the original is never touched. Run
`scry lean-region` first to see exactly what would be replaced. The details are in
[`docs/decisions/0003-simplification-cards-for-lean.md`](docs/decisions/0003-simplification-cards-for-lean.md).

For example, DeepMind's own comment in AlphaProof's P2 says "The agent wastes the next 16
lines proving then discarding a lemma." Re-proving that goal (step `s7`) with just the
direct proof that follows `exfalso` removes those 16 lines, and Lean accepts the result.

## Does the statement say what the paper claims?

A Lean proof settles the formal statement, and only that. The formal statement can still
differ from the published claim: more assumptions, a weaker conclusion, a special case, or
definitions that mean something other than the paper's words.

```bash
scry lean-statement FILE.lean THEOREM      # what Lean says the theorem states
scry fetch-openai-math && make openai-setup
scry openai-challenges                     # OpenAI's formal statements (comparator challenges)
scry openai-challenge TruffetCounterexample
scry audit-statement TruffetCounterexample # the AI helper lines it up against the paper
scry statement-benchmark --prepare-only    # planted-error benchmark: check the copies
scry statement-benchmark                   # audit them blind and score (costs money)
```

- **Anatomy, from Lean:** the hypotheses, the conclusion, and every definition from the
  project itself that the statement relies on (Lean and Mathlib definitions are trusted
  vocabulary; the project's own are where meaning can drift).
- **Two probes, judged by Lean's kernel:** do the hypotheses contradict each other (the
  theorem says nothing)? Does the conclusion hold without them? A probe counts only when the
  kernel accepts a proof; finding nothing is reported as finding nothing.
- **An audit by the AI helper:** it compares the paper's LaTeX with Lean's reading point by
  point and can have Lean check claims of its own (a special case, an example). Its report
  is labelled as its reading except where it cites a Lean check. It never sees OpenAI's own
  scope notes; the saved audit puts the note next to the report so you can judge it.

- **Audits are measured:** `scry statement-benchmark` plants known differences into copies of
  real statements and scores blind audits of them. First run: six of six caught, no audit
  passing a planted error as "matches" ([results](docs/examples/statement-benchmark-1.md)).

Details: [`docs/decisions/0005-statement-checking.md`](docs/decisions/0005-statement-checking.md).

## Following along in the browser

```bash
scry serve        # then open http://127.0.0.1:8765/
```

Start with an **outline**: a result, the definitions you need to read what it claims, and how
its proof is built from the theorems of its project, heaviest first, with the hypotheses its
proofs never use. It is read from Lean's record of the compiled project:

```bash
scry lean-outline lean-projects/openai-math/lean/OAI/MathematicalPhysics/NavierStokes/VelocityDetection/MainResult.lean \
  OAI.VelocityDetection.main_result -o lean-projects/maps/navier_stokes_main_result.outline.json
```

Details: [`docs/decisions/0008-outlines.md`](docs/decisions/0008-outlines.md).

It is also a read-only workbench: follow an audit while it runs (each piece of evidence, labelled with
who produced it; the helper's rows lighting up the Lean lines they are about), read benchmark
results, and look at proof maps drawn as steps and arrows (in Lean maps, what each `have`
writes inside itself starts folded into one box). It starts nothing, spends nothing
and changes nothing. Besides the bundled example, it shows the proof maps saved in
`lean-projects/maps/` (for example `scry lean-import File.lean Name -o lean-projects/maps/name.json`);
`--maps DIR` shows another folder instead. It can also be reached from a phone at a public
name behind Cloudflare Access (`--public-host`, `--access-team`, `--access-audience`; set-up in
the decision record). Details: [`docs/decisions/0007-the-workbench.md`](docs/decisions/0007-the-workbench.md).

## Lean checks that cost seconds

Loading Mathlib takes Lean a minute or more, so Scry keeps a Lean process running with a
file's imports loaded. Later checks of files with the same imports take seconds, and each
still starts from a clean slate: nothing one check declares carries over to the next. A
test requires identical results to a fresh `lean` run, and the check that applies a change
always uses a fresh one. Set `SCRY_LEAN_WORKER=off` to run a fresh `lean` every time.
Details: [`docs/decisions/0006-kept-running-lean.md`](docs/decisions/0006-kept-running-lean.md).

## The AI helper

```bash
scry chat p2.json        # needs OPENROUTER_API_KEY in .env (git ignores .env)
```

A terminal conversation about one proof map. The helper finds things out only through
Scry's tools: it reads steps and code, scans, runs Lean What-If tests, and drafts
Simplification cards that Lean judges. Every tool result becomes numbered evidence
(E1, E2, ...) labelled with its checker. Each answer is shown as **AI's reading**, together
with the evidence it cites. Scry points out citations to evidence that doesn't exist, and
answers that rest on no check. The helper is told to test your hunches with Lean before
agreeing, and to write Lean a person can follow. It can draft cards but can't apply them:
`/apply C1 New.lean` is yours to type, and Lean checks the card again when you do.

Chat commands: `/cards`, `/apply CARD NEW.lean`, `/evidence E3`, `/cost`, `/quit`.

Settings (in `.env` or the environment): `SCRY_MODEL` (default `anthropic/claude-opus-5.5`),
`SCRY_EFFORT` (`low` to `max`, default `high`). The cost of each turn is shown as you go.
The design is in [`docs/decisions/0004-the-ai-helper.md`](docs/decisions/0004-the-ai-helper.md).

**Lean files are programs.** Compiling one can run code written in it. Only use Scry's
Lean features on files you trust, or somewhere isolated.

## Setting up Lean

1. Install [elan](https://github.com/leanprover/elan), Lean's installer. The `lean/`
   folder pins the exact Lean version (v4.10.0-rc2), and elan fetches it automatically.
2. From the repository root, run `make lean-setup`. It downloads Mathlib's prebuilt files
   (about 4.5 GB) and builds Scry's Lean exporter.
3. Run `make lean-test` to confirm everything works. It runs real Lean, including on the
   three AlphaProof proofs, and takes a few minutes.

For OpenAI's mathematics repository (Lean v4.34.1, about 10 GB more): `scry
fetch-openai-math`, then `make openai-setup`, then `make openai-test`.

Network access needed for setup: `release.lean-lang.org`, `github.com`, and
`lakecache.blob.core.windows.net`. Fetching the AlphaProof proofs needs
`storage.googleapis.com`. The AlphaProof archive is not stored in this repository; Scry
downloads it and checks its fingerprint before using it.

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
| 1 | Proof maps, wiring check, scanner, What-If tests, Simplification cards, receipts, CLI | Done |
| 2 | Lean runner and exporter: a Lean file in, a proof map out; What-If tests re-checked by Lean | Done |
| 3 | Simplification cards checked by Lean before any swap | Done |
| 4 | AI helper via OpenRouter that works with you on clearer proofs, tests your hunches, and lets Lean judge | Done (this checkpoint) |
| 5 | Statement checking (does the formal statement say what the paper claims?) and Lean v4.34.1 / `openai/math` | Done (this checkpoint) |
| 6 | Browser workbench: follow audits; outlines of whole results; step-by-step maps | In progress |

## For contributors and coding agents

Read [`AGENTS.md`](AGENTS.md) first. Run `make check` (ruff, `mypy --strict`, tests)
before finishing any change, and `make lean-test` too when you touch anything Lean.
