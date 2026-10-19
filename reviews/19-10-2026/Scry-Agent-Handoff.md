# Scry: evidence-integrity hardening checkpoint

Review the attached `Review.md`, numbered source excerpts and additional regression suite before editing. They refer to a fixed repository snapshot; reconcile against the current checkout rather than mechanically copying patches.

Preserve Scry's existing distinctions: lookup versus wiring versus Lean evidence; formal proof versus paper correspondence versus AI explanation; proposals versus human-authorized application; old source versus a newly checked copy. Preserve the read-only browser. Do not add unrelated features during this checkpoint.

The review ran 232 existing Python tests and independently confirmed all 71 listed mutations. Its 10 additional tests expose eight reproduced findings; some use controlled exporter output and one uses a synthetic failing executable. No real Lean compiler or model request was used in the review. Do not present these as examples of Lean proving false mathematics.

## First: passing evidence must actually mean a successful trusted check

Fix nonzero fresh-process completion being accepted by the runner. Add positive controls and negative cases for nonzero exit after otherwise valid output, termination by signal, incomplete output and timeout. Preserve the distinction between execution failure and a rejected proof attempt.

Replace the audit prompt's unconditional claim of an already checked proof with evidence-derived status. Establish the current comparator/solution relationship, or label the proof status as upstream-reported/not checked here. Do not infer proof status merely from a known corpus entry, a filename or the existence of an import string.

Apply a consistent transitive axiom policy to probes. The Python regression shows `found=True` plus `sorryAx` currently becomes a trusted-looking flag. Add real integration cases where automation uses an admitted or extra-axiomatic helper through a referenced declaration, on both supported Lean versions. Preserve the relevant dependencies in the output rather than hiding them behind a headline. Do not reinterpret failure to find a probe as evidence of consistency or significance.

## Second: evidence must refer to the current, correct inputs

Design a shared run/input identity. A statement's meaning includes imported project definitions and relevant dependency versions, not only the visible theorem file. Fix statement-cache invalidation for direct/transitive source changes and dependency/manifest changes; validate imports before reusing cached readings. Include missing-file and stale-build cases.

Give paper files unique identities across papers. Two `build/main.tex` files must remain separately listable, searchable, readable and citable. Reject ambiguous references rather than picking the first file.

Separate the browser's expensive static outline cache from the freshness status of its underlying Lean files. A source edit must update the changed-files warning even when the saved outline JSON is unchanged.

Expose definition-closure completeness: included count, truncation/frontier status, and a supported way to retrieve omitted or clipped definitions. Do not promise a full definition through a tool that returns a clipped body.

## Third: the evaluator must preserve uncertainty and trial provenance

Do not count `unclear` alone as successful detection. Separate substantive detection, abstention/unresolved, false reassurance, no coverage and contradictory findings. A conflicting “matches” row must not disappear because another row is uncertain. Retain exact localization and add adjudication of whether the stated difference is the planted semantic difference.

Bind benchmark reuse to experiment identity, including model/settings, prompt/tools, sources and definitions. Make fresh trials, resumed work, reused complete results and incomplete runs visibly different. Existing reuse can still save money; it must not masquerade as a new or complete experiment.

## Completion evidence

Run all existing and new Python tests, lint, strict type checks, and the original mutation gate. Run Lean integration tests for the affected paths on both supported exporters. Add real Lean tests where the review could only test Python acceptance or inspect source. Record exactly what was run and any skipped gate.

Create a replayable Truffet audit bundle with exact corpus/dependency identities, original statement and paper sources, supplementary Lean claims, compiler results, event log and correspondence judgments. Do not invent missing historical E7/E9/E10 artifacts; rerun them and identify them as a new run.

The desired outcome is not fewer warnings or a higher score. It is a reader being able to tell what was checked, against which exact inputs, under which assumptions, and what remains unresolved.
