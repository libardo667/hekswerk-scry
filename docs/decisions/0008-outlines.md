# Decision 0008: Outlines, the level a proof is understood at

**Status:** accepted for Checkpoint 6, milestone 2.

## The problem

The owner reads the workbench without a mathematician's training. With proof maps drawn and
folded, they still "can't grok this without an agent helping me navigate it". A second agent
put the reason well: a tactic map is assembly language. Sixty boxes of `dsimp`, `push_cast`
and `linarith` show how Lean was persuaded line by line, not what the proof does. In the
Navier–Stokes velocity result the ideas weren't inside step s21 of a 76-step uniqueness
lemma. They were in how the force was defined, in how `main_result` wired its pieces
together, and in which hypotheses the proof never needed. `main_result` itself is three
tactic steps; it rests on 1,948 declarations across 152 files.

## Decisions

**An outline is a result and every declaration of its project that it rests on**
(`models/outline.py`). Each *part* is one declaration a person wrote: a theorem, definition,
instance, structure, class or inductive type. Each records the parts its statement mentions
(`statement_uses`) and the parts its body uses (`body_uses`: a theorem's proof, a definition's
value, a structure's fields). Library declarations (Lean, Mathlib and their usual packages)
are not followed.

**The arrows come from Lean's record, never from text.** `scry-export --outline` elaborates
the file and walks the finished declarations (`ScryExport/Outline.lean`, one per Lean
version, changed together). Lean also makes declarations nobody wrote: pattern-match helpers,
proof pieces it splits off, equation lemmas, a constructor's own `noConfusion`. These are
looked through, so whatever a helper uses counts as used by the part that uses the helper.
Constructors, field accessors and recursors count as their structure or inductive type.
A part is a project declaration that Lean records a place in a file for; an instance made by
`deriving` is one, written where its `deriving` clause is. Scry adds each part's text from
that file, and each file's fingerprint; the workbench says when files have changed since.

`make openai-test` outlines the same file on both Lean versions and requires the same parts,
uses, hypotheses and text. It found two differences, both fixed for the class rather than
the case. Lean v4.34's `deriving DecidableEq` also makes a helper, `instDecidableEqPt.decEq`,
and records the same place for it as for the instance; a declaration placed exactly where the
one named above it is placed is now one piece of writing, one part, and what the helper uses
counts for that part (`sameWriting`, `partsOfPart`). And v4.34 counts a doc comment as part
of where a declaration is written while v4.10 doesn't; the text now always starts after the
doc comment, which is shown separately anyway.

**Hypotheses a proof never uses are reported, read from Lean's record.** The exporter walks
the proof and the statement together along the statement's own shape (`∀`, `→`, `∃`, `∧`,
`↔`, `¬`) and stops at anything else. A hypothesis written inside a definition the statement
mentions is that definition's, not the statement's, so it is not counted. A first version
walked through every structure the proof built and reported conditions written inside
`ComparisonClass`, which no reader of the theorem would call its hypotheses; the fixture
keeps that case (`Loose`). A hypothesis is reported when it is a proposition, the rest of the
proof never mentions it, and the rest of the statement doesn't either. Names Lean made up are
not shown. The finding is exactly "the theorem holds without it"; whether that matters is
for a person to judge, and the page says so.

On Navier–Stokes this finds that `main_result` assumes the viscosity is computable
(`_hcomputable : ComputableReal ν`) and its proof never uses that. Nineteen other theorems
have such hypotheses, most named with a leading `_` (the author's own "not needed"), and ten
are a `CompleteSpace E` that a whole section of `WeakVolterra` assumes.

**Private declarations are parts, shown by their written name.** Lean names a private
declaration `_private.<module>.0.<name>`, which looks like a generated name. The statement
reader used the same test and silently left private definitions out of a statement's
meaning; it was fixed at the same time (`ScryStatement.isGenerated`). The project has 32.

**The outline view** (`#/outline/...`, `web/static/outline.js`) has four parts, built so
that a non-specialist can start at the top:

- *What it claims*: the statement, then the definitions you need to read it. These are found
  by following definitions' bodies but not theorems' proofs (`Outline.claim`), nearest first:
  the ones the statement names, then the 165 those are built from, folded.
- *Worth a look*: unused hypotheses, the result's first; and *what the proof constructs*,
  definitions its proof uses that the claim doesn't mention. In an existence proof those are
  the heart of the argument (here, the two force fields).
- *How the proof is built*: a tree you open a level at a time. Each theorem lists the
  theorems its proof uses, then its constructions, heaviest first, and folds the claim's own
  definitions into one line. *Heaviest* is the lines of Lean beneath a part (everything it
  rests on), shown as a bar.
- *Find*, by name.

Choosing a part shows its statement as Lean prints it and as written, its doc string, the
shortest chain of "uses" from the result to it, what it uses and what uses it, and its
step-by-step map when there is one. The index the page loads first refers to parts by number
and leaves out what the page can work out, so the 1,949-part outline is about 70 KB
compressed; a part's text is fetched when it is chosen. Every word of it comes from Lean or
from the file. Nothing on the page is the AI's reading.

**Proof maps stay, renamed "step-by-step maps"**: the level for checking one step, linked
from each theorem that has one.

## Not yet

- A plain-English line for each part, written by the AI helper offline, labelled AI's
  reading and citing the part it describes. The doc strings authors write are shown, but this
  project has none.
- Outlines of more results, and statement audits linked from an outline's claim.
- What-If tests at the outline level (what stops holding if a theorem is removed).
