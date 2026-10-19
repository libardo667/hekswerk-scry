Okay, Levi. **This is a substantial step forward—and I found some important things to fix.**

The encouraging part is that Scry now has a concrete investigation to point to, not just an architecture for conducting one. The Truffet work, the distinction between statements and proofs, and the new outline interface fit together into something useful.

The corrective part is that **some of Scry’s assurances are stronger than the evidence its implementation actually checks**. I reproduced several cases where outdated, incomplete, or unsuccessful work receives a more confident interpretation than it should.

Those are fixable problems. They matter especially because trustworthy interpretation is the product.

I put the detailed findings, line-numbered source excerpts, regression tests, execution logs, screenshots, and an agent handoff into a Scry-Review-Packet.zip[complete review packet](sandbox:/mnt/data/Scry-Review-Packet.zip). The Scry-Review\.md[written review](sandbox:/mnt/data/Scry-Review.md) is also available separately.

## What I actually tested

I compared both archives, traced the new code paths, ran the Python suite, exercised the listed mutations, and wrote additional adversarial tests.

| Check | Result |
|---|---|
| Earlier version’s Python tests | **126 passed** |
| Updated version’s Python tests | **232 passed** |
| Repository’s deliberate bug mutations | **71 independently confirmed as detected** |
| Additional reviewer regression tests | **10 exposed unmet expectations** |
| Browser JavaScript syntax | **All 7 modules passed** |

For the mutation tests, I went beyond counting unsuccessful test runs. Parallel execution caused some unrelated process-startup timing errors, so I subsequently checked every mutation against a relevant test: **the unmodified control passed; the corresponding mutation failed**. All 71 passed that comparison. The evidence is in the Scry-Review-Packet.zip[test logs and mutation records](sandbox:/mnt/data/Scry-Review-Packet.zip).

The 10 additional failures are **not** failures in your existing suite, nor 10 independent architectural disasters. They are new tests covering eight related findings.

Important limits: I could not run Lean or Lake in this environment, and Ruff/mypy were unavailable. Consequently, I have **not** independently passed the complete build gate, rebuilt the exporters, or replayed the actual Truffet Lean checks. No paid model audits were launched.

I also rendered the shipped browser modules with responses from Scry’s actual Python data handlers. That was an offline rendering exercise, not a deployed-server or Cloudflare security test.

## The most meaningful advance: Scry now separates two different maps

The new **outline** is, in my opinion, one of the best decisions in this version.

A tactic map answers:

> How did this proof get from its starting conditions to its conclusion?

The outline can instead answer:

> What does this result actually mean, and what mathematical constructions does its proof depend on?

Those sound similar until you implement them. Your implementation treats them differently: statement dependencies contribute to understanding the claim; proof dependencies contribute to understanding its justification. `Outline.claim()` follows definitions without dragging in the proofs of every theorem it encounters. The proof-dependency closure is handled separately. source-evidence.md[Source excerpts: outline implementation.](sandbox:/mnt/data/scry_review/final/source-evidence.md)

**That is not merely a nicer visualization. It is a better starting point for investigation.**

Someone auditing a definition should not first have to navigate every tactic used to establish a supporting lemma. Conversely, someone studying a proof technique needs to see the constructions the proof introduces, not just the vocabulary in the theorem statement.

The browser’s “What it claims,” “Worth a look,” and “How the proof is built” sections make that distinction visible. In the desktop-outline.png[desktop outline I rendered](sandbox:/mnt/data/scry_review/final/screenshots/desktop-outline.png), I could see the claim, its definitions, unused hypotheses, source text, and supporting declarations without those becoming one undifferentiated graph.

That is a meaningful realization of your “smart adult should understand what they’re looking at” requirement. It does not yet teach that adult all the mathematics, but it gives them intelligible questions to ask.

## The Truffet audit does the kind of work you wanted

The saved Truffet report contains something more interesting than “the code and paper seem to agree.”

It distinguishes:

**The original formal result:** the specified procedure reaches a feasible output with cost 1, while another feasible point has cost 0.

**A stronger claim in the prose:** 0 is the actual minimum, not merely a better value.

**Another stronger claim:** the first substitution already removes every optimal solution.

The report identifies the latter two as things the original theorem does not itself state, then reports supplementary Lean checks establishing the relevant lower bounds. It also records a failed tactic attempt without presenting that failure as evidence that the mathematical claim is false. truffet-statement-audit.md[Saved Truffet report.](sandbox:/mnt/data/scry_review/final/project-reports/truffet-statement-audit.md)

That is exactly the distinction this tool should preserve:

> “This claim is absent from that theorem” does not mean “this claim is false.”

And:

> “My attempted proof failed” does not mean “I disproved the claim.”

The audit also leaves the right question open: whether the formalizer’s definitions faithfully reconstruct the rules in Truffet’s original paper. Checking the formalized algorithm is different from checking that it is the intended algorithm.

There is an important correction to my earlier explanation, too. I talked about the exact minimum of zero alongside what the original Lean theorem establishes. **The new audit separates those more carefully:** exhibiting a better point belongs to the original result; proving the exact lower bound is supplementary evidence.

One limitation prevents me from independently endorsing those supplementary runs: this archive preserves their written summary, not a replayable bundle of the original E7/E9/E10 checks. The browser explicitly acknowledges that this first audit predates the run logs.

So my conclusion is: **the recorded investigation is substantive and appropriately discriminating; its historical execution is not independently reproducible from this ZIP alone.**

## The highest-priority problems I found

These are not reasons to discard Scry. They are places where its evidence discipline needs to extend further.

### 1. A definition can change while Scry keeps using its old statement audit

This is the most thematically important bug.

In `lean/statement.py`, the statement-cache key includes the theorem file, theorem name, toolchain string, exporter, and probe setting. It does **not** include imported project definitions or the dependency manifest.

Worse, a cache hit returns before rebuilding imports.

I reproduced this through the real statement-reading function with a controlled exporter:

The statement imports a definition from another file. Scry reads and caches the statement. I change that imported definition. Scry reads again—and returns the old report without asking the exporter again.

Changing the dependency manifest also failed to invalidate the cached report.

**The visible theorem can remain identical while its meaning changes underneath it.** That is precisely the class of problem Scry exists to investigate. A theorem-file hash alone is not an identity for a mathematical claim.

The fix is to bind results to their relevant imported definitions and dependency state, and validate those inputs before deciding that old evidence remains reusable. This needs transitive-import and dependency-change tests, not just a test that edits the theorem file itself. source-evidence.md[Finding F1 and exact source excerpts.](sandbox:/mnt/data/scry_review/final/source-evidence.md)

### 2. A failed process can still receive “Lean-checked”

I exercised the actual fresh-process runner using an explicitly synthetic executable.

The executable emitted a valid-looking no-axioms information message, then exited with code **23**.

Scry returned:

```text
passed = True
exit_code = 23
summary = "Lean-checked: Lean accepts..."
```

The runner records the exit code, but its judgment does not use that code to reject the check.

This is **not** a demonstration that Lean proved false mathematics. It is a demonstration that Scry can call an unsuccessful execution successful when the output happens to look reassuring.

A process failure does not have to produce a well-formed Lean error message. Successful completion must be an independent requirement, alongside the message and axiom checks.

I would fix this before relying on any further “Lean-checked” demonstrations. It is a small-looking condition with a large effect on the meaning of the label. Scry-Review-Regressions.py[Finding F2; the reproduction is included in the regression suite.](sandbox:/mnt/data/Scry-Review-Regressions.py)

### 3. The auditor is told a proof has been checked before that is established

The audit prompt contains this unconditional statement:

> “This statement is a comparator challenge: Lean has checked a proof of it…”

But `audit_challenge` does not establish that proof/comparator relationship before supplying the statement to the model.

I reproduced the orchestration with a comparator containing `sorry`, a report carrying `sorryAx`, and a solution file that did not exist. The prompt still asserted that Lean had checked a proof.

The upstream repository may genuinely have a checked solution. **That is not the same as Scry establishing it for the exact current inputs.**

This should become an explicit status: upstream-reported, not checked here, checked against this solution and input identity, or failed. It should not be an assumption embedded in the assistant’s instructions.

This is particularly important for a project designed to resist agreeable storytelling: an assistant can diligently follow its instructions and still begin from an unsupported assertion that the application supplied. source-evidence.md[Finding F3 and audit orchestration.](sandbox:/mnt/data/scry_review/final/source-evidence.md)

### 4. Two different papers can resolve to the same source identifier

The paper reader labels files by their path inside a directory called `build`.

Consequently:

```text
PaperA/build/main.tex → main.tex
PaperB/build/main.tex → main.tex
```

When asked to read `main.tex`, it returns the first match.

I created two such files and asked for the second using its advertised identifier. **The toolbox returned the first paper’s text.**

That is a real source-provenance problem, not just an awkward filename. The wrong paper can be read under an apparently legitimate citation label.

The Truffet scope involves two papers, although I have not established that their actual files collided during the saved audit. The supported multi-paper workflow nevertheless needs unique paper-qualified identifiers and explicit rejection of ambiguous references. source-evidence.md[Finding F4.](sandbox:/mnt/data/scry_review/final/source-evidence.md)

### 5. The probes do not consistently enforce the theorem runner’s axiom policy

The ordinary theorem runner restricts acceptable axiom dependencies. The probes collect their axiom dependencies but do not apply the same restriction before marking a contradiction or triviality proof as found.

On the Python side, I supplied a probe result containing:

```text
found = True
axioms = ["sorryAx"]
```

It became a confident-looking claim that Lean had derived a contradiction from the hypotheses.

That is not sufficient evidence. Lean tracks axioms used indirectly through other proofs, and `sorryAx` is the placeholder axiom associated with unfinished proofs; it can support arbitrary propositions. Merely obtaining kernel acceptance relative to such a dependency does not establish the desired conclusion under Scry’s intended assumptions. [Lean Language](https://lean-lang.org/doc/reference/latest/Axioms/)

**Scope of my finding:** I reproduced the Python acceptance and inspected the Lean path. I did not compile a Lean example exploiting an indirect admitted helper here.

The next integration test should do exactly that. The fix is to validate the transitive axiom set and show unacceptable dependencies as a qualification, rather than hiding them behind a “red flag” headline.

## The benchmark is promising—but its success metric needs tightening

The six planted differences are well chosen for development testing. Reversing an inequality inside a definition, dropping a normalization, or replacing the plane with the line are much closer to the real correspondence problem than inserting an obvious syntax error.

The saved report also names the particular discrepancies it found. That is useful evidence about those examples. statement-benchmark-1.md[Saved benchmark report.](sandbox:/mnt/data/scry_review/final/project-reports/statement-benchmark-1.md)

But the scorer currently treats **any non-`matches` verdict overlapping the planted lines as a catch**.

That includes `unclear`.

I reproduced both of these outcomes:

```text
"unclear" on the planted lines
    → caught

"matches" plus "unclear" on the planted lines
    → caught
```

The second is especially concerning: uncertainty can mask false reassurance.

Remember the three outcomes we discussed earlier—confirmed alignment, evidence of divergence, unresolved? **Your evaluation needs to preserve that distinction too.** An honest abstention is better than confidently approving a bad statement, but it is not the same achievement as locating and explaining the error.

I would separate substantive detection, unresolved, false assurance, unreviewed, and conflicting findings. Eventually, a small independently reviewed set should also check whether the explanation identifies the *actual* planted semantic difference, not merely overlapping lines.

This does not establish that the six saved catches were bogus: their recorded rows identify substantive differences. It establishes that the scoring rule allows future results to overstate success.

There is a related reuse problem. Benchmark reuse checks the copied statement’s hash, not the complete experimental setup. Changes to the model, prompt, paper, tools, or imported definitions are not represented in that reuse decision. A run that hit its round limit is also reusable through the ordinary results path.

Reusing work is sensible. **Reused work is not a fresh trial, and unfinished work is not a completed investigation.** Those distinctions need to survive into the headline result. Your saved report does disclose six reused audits; keep that transparency and extend it. source-evidence.md[Findings F6–F7.](sandbox:/mnt/data/scry_review/final/source-evidence.md)

## The browser is moving in the right direction, with one freshness bug

The inspected desktop and phone views rendered without JavaScript errors or document-level horizontal overflow. The mobile-map.png[phone proof-map view](sandbox:/mnt/data/scry_review/final/screenshots/mobile-map.png) was readable, and the distinction between “wiring checked” and “proven” remained visible.

I also like that the interface is read-only. Opening a page does not quietly launch a paid investigation or apply a proposed proof edit.

However, I reproduced a stale-warning problem: load an outline, edit its underlying Lean source, then ask for the outline again. The browser’s data layer still reports no changed files.

The underlying file-hash checker works. The cached outline index prevents it from running again because the cache watches the saved outline JSON, not the source files whose freshness it reports.

This is another instance of the same theme as the statement cache: **a correct check can become misleading when its result outlives the inputs it checked.**

Two smaller observations belong in the next polish pass. The statement reader stops after 80 project constants without a completeness signal, and definition text is clipped at 3,000 characters even though the tool describes its output as “in full.” Limits are reasonable; the user and auditor must know when coverage is incomplete. Also, the Markdown renderer leaks the remainder of a multiline HTML comment into the Truffet report—a minor presentation defect, not script execution.

For the nonexpert audience, the remaining challenge is explanatory rather than navigational. The outline makes it easier to find the relevant definition; it does not yet explain that definition’s mathematics. I would add that as a separately labelled interpretation layer, not replace the accurate structure with polished analogies.

## What I would make the next checkpoint

**Evidence identity and status.**

Not another major interface feature. Not a larger collection of impressive-looking audits.

First, make unsuccessful execution, unchecked proof status, and untrusted probe dependencies fail safely. Then make every result refer unambiguously to the exact statements, definitions, dependencies, and papers it concerns. Finally, make the benchmark preserve uncertainty and experimental history.

After that, produce one replayable Truffet case study: exact inputs, supplementary Lean source, compiler results, event log, and a clear separation between the original theorem, the added claims, and unresolved correspondence questions.

A skeptical Lean user should be able to reproduce the evidence. A curious reader should be able to tell which sentences describe formally checked facts and which express the auditor’s interpretation.

That would be a stronger milestone than another dozen features.

I included a Scry-Agent-Handoff.md[Claude Code handoff](sandbox:/mnt/data/Scry-Agent-Handoff.md) and the Scry-Review-Regressions.py[10-test regression suite](sandbox:/mnt/data/Scry-Review-Regressions.py), so the findings can become concrete work rather than another document to vaguely “address.”

**My overall assessment is more positive about the direction, and more demanding about the assurances.** The outline and Truffet investigation make the intended usefulness much more tangible. The bugs show where the application still needs to earn the confidence its labels imply.

You are no longer only proposing a workbench for scrutinizing mathematical claims. You have built enough of one that it can itself be scrutinized in concrete, productive ways. That is real progress.