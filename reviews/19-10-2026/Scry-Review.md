# Hekswerk Scry — independent source and behavior review

Reviewed 19 October 2026. Basis: the two conversation-uploaded repository archives, especially `hekswerk-scry-main (2).zip`. This is a review of that snapshot, not the current remote repository.

**Assessment:** a substantial advance toward a useful proof-investigation workbench. The strongest new work is the separation of statement meaning from proof construction, the concrete Truffet audit, and the beginnings of inspectable experiment records. Several reproducible evidence-integrity defects should be fixed before treating the resulting labels or benchmark scores as reliable assurance.

Nothing in this review establishes that the Truffet theorem is mathematically wrong. Several tests deliberately supply synthetic exporter output or a synthetic executable. They test Scry's handling of evidence, not Lean's kernel.

## What I actually checked

I compared the archives, read the implementation and architectural decisions, executed the standard-library tests, exercised the repository's listed mutations, wrote additional negative tests, and rendered the shipped browser modules using the real Python `Library` handlers and supplied fixtures.

The old archive has 83 files; the new has 159: 76 additions, 25 changed files, no removals. The old clean Python suite passed 126 tests. The new clean Python suite passed **232 tests in 48.679 seconds**. All **seven** browser JavaScript modules passed `node --check`.

The mutation set contains 71 specified changes. Each was applied in an isolated copy and the full unit suite run. Those parallel runs all rejected their mutations, but also exposed unrelated one-second process-startup races under load. I did not count unrelated timing failures as evidence of detection. A second pass runs a relevant test for each mutation, first on pristine code and then on that exact mutation. **All 71 were independently confirmed: the selected control passed and the mutation failed.** See `results/mutation-confirmation/results.json` for those outcomes and `results/mutations/` for the full-suite logs.

The additional reviewer suite contains **10 desired-behavior tests, all of which fail on this snapshot**. These are not 10 failed existing tests and not 10 independent root causes. They cover the eight reproduced findings below; dependency-cache invalidation and benchmark scoring each have two cases. There are also static-review observations not represented by those tests.

The core source tree was compared byte-for-byte with the uploaded archive after execution. No tracked source file was changed. Tests and experiments ran in disposable copies or temporary folders.

### Limits of this review

Lean and Lake were unavailable. I did not build either exporter, compile the OpenAI corpus, independently replay Truffet's auxiliary lemmas, or run the Lean integration suites. Ruff and mypy were unavailable; package installation failed because the package host could not be resolved. The complete `make check` gate was therefore **not** independently passed.

No paid model requests were launched. The saved audit and benchmark costs, times, mathematical results and corpus-coverage counts remain project-reported observations, not newly reproduced measurements.

Browser network navigation to localhost was blocked by the environment. I rendered the actual shipped modules offline, supplying responses from the actual Python `Library` implementation. This exercised DOM rendering and fixture navigation, not a deployed HTTP service, Content-Security-Policy enforcement or Cloudflare Access configuration. No errors or document-level horizontal overflow occurred in the inspected desktop and 390-pixel-wide phone map, outline and Truffet-report views. The outline render used the repository's small real-export fixture, not a newly exported large theorem.

## What became meaningfully better

### 1. The outline is the right abstraction above a tactic map

The implementation distinguishes references that contribute to a declaration's statement from references used by its proof. `Outline.claim()` follows definition meaning without dragging in the bodies of proofs. `rests_on()` separately tracks the proof's dependency closure. That gives a reader two different starting questions: “What does this result mean?” and “How is this result established?”

This is more useful than merely drawing a larger tactic graph. The screen's “What it claims”, “Worth a look”, “How the proof is built”, and declaration-detail views expose genuinely different structures. It also preserves the distinction between a hypothesis unused by this proof and a proof that can safely be edited without a recheck.

The graph implementation is not just untested visual plumbing: the existing tests compare closure computation against independent traversal on random graphs, exercise cycles and missing references, and check the distinction between statement and proof dependencies. The browser shows authors' source and documentation rather than quietly manufacturing mathematical explanations.

### 2. The Truffet audit asks the correct additional questions

The saved Truffet report distinguishes the fixed two-step procedure, its feasible output of cost 1, and a feasible point of cost 0 from the stronger claim that 0 is the exact optimum. It also distinguishes that main formal statement from the claim that the first substitution removes every optimum.

The report says auxiliary Lean checks established the missing lower bounds: feasible normalized points in the initial system have first coordinate at least 0; feasible normalized points after the first substitution have first coordinate at least 1. Combined with the exhibited points, those explain the stronger prose claims. It explicitly records a failed tactic attempt without treating that failure as a counterexample to the mathematics.

That is the intended investigation loop: locate a scope gap, formulate an exact supplementary claim, ask the formal checker, and retain the distinction between the original theorem and the supplementary evidence.

The report also leaves search-endpoint conditions and fidelity to Truffet's original v4 rules unresolved. That restraint is valuable. A theorem about the formalizer's algorithmic model does not by itself certify that the model faithfully reconstructs the original paper.

**Important evidence limit:** the archive contains a written summary of E7/E9/E10, not a replayable bundle of those original Lean checks. The browser explicitly says this first audit predates run logs. I can evaluate the reported reasoning and the implementation, but I cannot certify those runs from the shipped summary.

### 3. The benchmark is aimed at semantic failures a proof checker alone cannot rule out

The six plants include reversing an inequality within a definition, dropping a normalization, weakening an exponent bound, using the line instead of the plane, and limiting a universal-looking coloring property to a bounded region. These are useful targets for testing statement correspondence rather than just proof syntax.

The saved results name specific differing features, not generic unease. The code separates blind copies from the answer key, and the documentation acknowledges the small sample, shared model-family provenance, lack of repetition and loose scoring rule. That is a promising development set, not an established accuracy estimate.

### 4. The engineering has useful boundaries worth keeping

The AI drafts proof changes but does not apply them itself. Applying a Lean card checks the whole changed file with a fresh process; the original remains intact. The code separates lookup, wiring checks and Lean-derived evidence. Logs retain tool arguments, returned evidence and model activity; these should become the basis of reproducible case-study bundles.

The persistent Lean worker is a sensible performance direction, with code and tests addressing import/build invalidation and stopping child processes. I did not validate its semantic equivalence to fresh Lean here. The supplied integration tests attempt that comparison, which is the right kind of test.

The read-only browser avoids turning a page view into a paid audit or a source edit. It has explicit localhost/public-host boundaries and file-scope guards. The DOM renderer constructs nodes instead of interpreting arbitrary report HTML. These are good design choices, not a claim of comprehensive security certification. The repository correctly warns that compiling a Lean file can execute code; a clean subprocess environment is not a filesystem sandbox.

## Findings to address

Priority means impact on the product's own assurance claims. It is not a vulnerability score.

### F1 — Statement-cache identity excludes imported meaning

**Priority: high. Reproduced through the public `read_statement` path with a controlled exporter.**

Locations: `src/hekswerk_scry/lean/statement.py:118–143, 189–201`.

The cache key includes the top-level file bytes, theorem name, toolchain string, exporter bytes and probe switch. It does not include imported project definitions or the dependency manifest. The cached result is returned before `build_imports` is called.

In one regression I read a statement importing a separate definition file, changed the definition, and read again. The old report was returned; the exporter and import-build hook had each been called only once. A second regression changes `lake-manifest.json` instead and gets the same reuse.

This is directly relevant to the purpose of Scry. The visible theorem can stay byte-identical while a referenced definition changes its meaning. Displaying the old definitions and probe outcomes as the reading of the new state defeats the audit boundary.

**Repair:** identify the complete semantic input set, not just the entry file. Validate/build dependencies before deciding reuse, and bind cached results to the relevant source and dependency identities. Include manifest/package revisions and exporter identity. A project-source timestamp is an expedient invalidator, not a complete content-identity design. Imported package changes and missing files need explicit treatment. Test direct/transitive imports, definitions, local package changes and manifest changes.

### F2 — A failed fresh process can still receive a passing Lean label

**Priority: high. Reproduced with an actual, explicitly synthetic subprocess.**

Locations: `src/hekswerk_scry/lean/runner.py:113–175, 223–258`.

`check_file` records the process exit code, but `_judged` does not use it to reject the check. Its decision uses the parsed message stream, axiom report and timeout flag.

My stand-in executable prints one valid-looking no-axioms information record and exits **23**. The real fresh-run path produces `passed=True`, a receipt containing `exit_code=23`, and a “Lean-checked” summary. This is a protocol failure: a crash/failure is not required to leave an error-shaped JSON message.

This does **not** demonstrate that Lean accepted a false proposition. It demonstrates that Scry's success criterion fails open when execution has failed.

**Repair:** require successful process completion as well as successful logical diagnostics. Missing, negative or nonzero exit codes must not yield a passing fresh-run receipt. Keep execution failure distinct from “the submitted proof attempt did not check”, and from “the mathematical claim is false”. Defend the invariant at the receipt boundary as well as the caller.

### F3 — An audit assumes a checked proof before establishing it

**Priority: high. Reproduced at audit orchestration; no model call.**

Locations: `src/hekswerk_scry/ai/audit.py:70–71, 152–168`; `src/hekswerk_scry/ai/statement_tools.py:80–84`.

`PROVED_CHALLENGE` unconditionally tells the helper that Lean has checked a proof of this comparator statement. `audit_challenge` reads the statement and constructs the prompt without verifying the solution/comparator relationship in that execution path. The default claim-note also describes an imported result as proved before the import/check occurs.

The regression supplies a statement report containing `sorryAx` and a challenge whose solution file does not exist. The audit still constructs the “Lean has checked a proof” prompt. The existence of a comparator entry is metadata, not a local verification receipt.

The upstream corpus may supply valid proof/comparator evidence. That is a different claim from this command having established it for the exact current checkout. Importing a module in a later auxiliary check also does not by itself check that the comparator declaration corresponds to the intended solution declaration.

**Repair:** make proof status structured and evidence-derived. Distinguish “upstream reports a proof”, “not checked here”, “checked against this solution and exact input identity”, and “check failed”. A verified proof/comparator receipt may be cached with complete provenance. Do not put an unsupported assertion into the model's instructions and expect the model to correct it.

### F4 — Paper IDs collide across multiple papers

**Priority: high for multi-paper audits. Reproduced with real temporary files and the real toolbox.**

Locations: `src/hekswerk_scry/ai/statement_tools.py:193–227`.

A file is labelled by its path inside a directory named `build`. Thus `PaperA/build/main.tex` and `PaperB/build/main.tex` are both `main.tex`. `read_paper` resolves a label with the first match.

In the regression, asking for the second paper using its advertised file identifier returns the first paper's text. Searches and citations can become ambiguous too. The Truffet report's scope involves two papers, but I did not establish that those particular upstream files collided during its saved run.

**Repair:** namespace source IDs by paper identity, preserve full corpus-relative location and source hash, and reject ambiguous references rather than picking the first match. Test identical filenames and section paths in two papers, including search → read → citation.

### F5 — Probe “found” status is not restricted to trusted axioms

**Priority: high for the probe trust boundary. Python acceptance reproduced; Lean route is static analysis, not compiled here.**

Locations: both `ScryExport/Statement.lean` versions, especially `tryTactic`, `kernelAccepts`, and `probeResult`; Python `lean/statement.py:81–90, 243–261`; `ai/statement_tools.py:155–170`.

The Lean probe rejects a direct `sorry` in the proof expression, adds the candidate declaration, and collects its axioms. It does not compare that collected set with Scry's allowed standard axioms. The Python side accepts `found=True` without filtering the supplied axioms; its user-facing headline can then say the hypotheses contradict each other. The statement tool displays that headline without the probe's axiom list.

The regression passes a probe report whose proof depends on `sorryAx`; it becomes an authoritative-looking contradiction flag. A plausible Lean-side route is a tactic using an admitted or extra-axiomatic helper through a constant reference. That route needs an actual Lean integration test before claiming it has been demonstrated end to end.

The ordinary theorem runner already has the relevant standard-axiom allowlist. Apply a consistent policy to auxiliary probe evidence too. A proof relative to an untrusted global axiom is not evidence that the theorem's own hypotheses are contradictory.

**Repair:** check the transitive axiom set before assigning trusted probe-found status; surface untrusted assumptions explicitly; expose them in the tool output and receipt. Retain the difference between no proof found and a proof found with unacceptable dependencies.

### F6 — The benchmark rewards “unclear” as a successful catch

**Priority: high for evaluation claims. Reproduced directly against the scorer.**

Location: `src/hekswerk_scry/ai/benchmark.py:235–250`.

Any non-`matches` verdict overlapping the planted lines is `caught`. The valid verdict `unclear` therefore counts as detection. Worse, a `matches` row on the planted lines plus an `unclear` row on the same lines is still `caught`: the first branch masks false reassurance.

Two regressions demonstrate those cases. This is not a hidden interpretation: the documentation describes the loose mechanical rule. The issue is that “caught” overstates what that rule establishes.

The six saved catching rows identify substantive differences, so these regressions do not establish that the six saved examples were incorrectly classified. They show that future scores can look successful without the helper diagnosing the planted error.

**Repair:** separate substantive detection, unresolved/abstained, false assurance, unreviewed, and conflicting outcomes. Require a localized account of the actual semantic change for a true positive. Never let generic uncertainty erase a false reassurance. Score controls separately, and independently adjudicate a small sample before expanding the automated benchmark. A safe abstention deserves recognition, but not the same credit as identifying an error.

### F7 — Reused benchmark trials lack complete experimental identity

**Priority: medium. Partial-run reuse reproduced; missing context fields confirmed in code.**

Locations: `src/hekswerk_scry/ai/benchmark.py:314–353, 365–386, 451–489`.

The reuse predicate checks only the copied statement's hash. Model identity, instructions, tool implementation, paper text, imported definitions and other experiment inputs are absent from `EarlierResult`. An audit that hit its round limit is still reusable through the ordinary completed-results route; the headline summary does not make that completion limit prominent.

Reusing earlier work is good cost control. It is not an independent new trial and should not silently represent changed audit conditions. The saved benchmark does disclose six reused audits, which should be preserved in any external description.

**Repair:** fingerprint the experimental setup and inputs. Carry trial/run lineage, model settings, source identities, completion state and reuse status into the score and summary. Allow explicit resumption of partial work, but do not make it indistinguishable from a complete fresh experiment. The included partial-run test expresses this proposed stricter policy; preserving incomplete data with an explicit incomplete status is another valid design.

### F8 — The browser can keep an outdated source-freshness warning

**Priority: medium. Reproduced with the actual `Library` and outline fixture.**

Locations: `src/hekswerk_scry/web/server.py:251–297`.

The outline cache is keyed by the saved JSON's size and modification time. `changed_files(outline)` is computed while creating that cached index. If a Lean source changes but the outline JSON does not, later requests return the old freshness list.

The regression loads an outline, appends a source edit to its Lean file, and reads the outline again. `changed_files` remains empty. The low-level file-hash check is correct and already tested; the caching layer stops it from being called again. This is why the existing mutation “changed outline file is still shown as it was” does not cover a changed underlying Lean source.

**Repair:** cache the expensive static index separately from dynamic freshness state. Recompute source freshness on access, or include a sound invalidation mechanism for those underlying files. The disclaimer that an outline is not a fresh proof check is useful but does not repair an inaccurate changed-files warning.

## Additional static and interface observations

The statement exporter limits its project-definition closure to **80 constants** without returning an omitted-count/frontier/completeness flag. Printed definitions are clipped at **3,000 characters**, with a visible cut marker, while the read-definition tool describes its output as “in full” and has no full-body pagination path. These are reasonable performance limits but inadequate completeness signals. The current Truffet report is not shown to exceed them. Add explicit coverage metadata and ways to retrieve omitted definitions before describing an audit as covering every relevant definition.

A paper can distribute its claims among several comparator challenges. The saved PlaneColoring control flags scope absent from this challenge even though a sibling challenge covers the larger result. That is useful evidence about this statement, not automatically evidence that the paper's entire formalization is missing its main result. Offer a neutral inventory of sibling declarations without leaking the answer-key scope prose.

The browser renders the remainder of a multiline HTML comment in the Truffet report: the Markdown renderer skips the opening-comment line, not the whole comment. This is a small presentation defect, not script injection. Add a multiline comment test.

For an expert, the outline reduces navigation work. For the “smart adult” audience, it is not yet a full explanation layer: most declarations remain mathematical symbols and source code. Preserve the same evidence underneath, but add separately labelled, limited explanations of the target claim, its objects, and why a selected definition matters. Do not solve this by replacing accurate structure with confident analogies.

## A coherent next milestone

I would make the next checkpoint **trustworthy evidence identity and status**, rather than another large feature.

First, make process completion, proof/comparator status and trusted probe axioms fail closed. Second, bind every result to the exact statement, definitions, dependency versions and source documents it concerns; fix cache freshness and paper IDs as one coherent provenance task. Third, distinguish benchmark detection from abstention and distinguish new trials from reused or unfinished ones.

Then publish a compact replayable Truffet case study. It should carry the exact corpus revision, both relevant papers and original-rule version identifiers, challenge/solution identity, toolchain/dependency identities, exported statement and definitions, auxiliary Lean source, raw check results, event log, and a short separation of what the original theorem proves, what the added checks establish, and what remains unresolved.

Success is not another impressive summary. It is a skeptical Lean user being able to reproduce the evidence and a reader being able to tell which sentence is a verified formal fact, which is a correspondence judgment, and which is an open question.

The project is worth continuing because the workflow now has substance. These findings do not require abandoning its architecture. They require extending its strongest original rule—claims need evidence—to freshness, provenance, imported assumptions, and the benchmark's own claims.

## Reproduction and packet contents

The axiom-policy background was checked against the Lean Language Reference, “Axioms”, and the Lean community’s “Did you prove it?” guidance (accessed 19 October 2026). These external references support the interpretation of transitive axiom dependencies; they are not evidence that the current exporters were compiled here.

Run the additional tests from any directory:

```bash
python review_regression_tests.py --repo /path/to/hekswerk-scry -v
```

They intentionally fail on the reviewed snapshot. The implementation may evolve; tests importing private helpers may need mechanical adaptations without weakening the desired behaviors. They use no real Lean or provider API. The probe-report regression tests the Python trust boundary; add a real Lean integration test for transitive admitted/extra-axiomatic dependencies.

`source-evidence.md` contains numbered excerpts from the exact reviewed files. `results/` contains execution logs and controlled mutation results. `screenshots/` and `browser-observations.json` record the offline render. `project-reports/` contains the two supplied saved report summaries, unaltered, for comparison.

Archive SHA-256:

```text
old: 9d1c6785d0eac211c80b6502b4085f2c6bab046c82e539f8de65fc342b2e7e20
new: 0a648d2a9a0604a2ed883c91fa81269ba0d34fa76a841468ed117088ada0351a
```
