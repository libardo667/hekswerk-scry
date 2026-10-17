# Decision 0003: Simplification cards for Lean proofs

**Status:** accepted for Checkpoint 3.

## The question

What should a swap in a Lean proof be allowed to replace? An early proposal limited
cards to "one `have`, or one sub-proof". The owner asked whether that was a stopgap or
the real thing. It was a stopgap, and the general form turned out to be no harder.

## Decision: re-prove any one fact

A card names one fact of a Lean-backed map and gives new tactics that prove it. The fact
can be a goal ("finish this goal differently from here") or a lemma introduced by `have`,
`suffices`, and the like ("prove this lemma differently").

Every group of steps someone might want to replace lies inside the proof of some fact,
and the smallest such fact is the natural thing to re-prove. So "re-prove one fact" covers
every swap, including every Knot the scanner finds. The fact's proof is worked out from
the map (`regions.proof_of`):

- the fact's own step, plus every earlier step whose results are needed only inside the
  group. **Dead ends don't count** when deciding this. A step that leads neither to the
  goal nor to the fact (an unused hint, or a rewritten copy of a hypothesis that nothing
  reads) can't make anything else necessary.
- `have` lines outside the group whose lemma is used only inside it. These become dead
  once the proof is replaced, so they are removed too.
- dead code inside the part being cut (a hint whose result the finished proof never
  used), and the "Why h holds" steps of lemmas that removed steps introduced, if
  nothing else needs them.

A step whose code sits inside the cut but which something outside still needs is a
conflict: the card is refused with a plain message instead of guessing.

## How a swap is judged

1. The new tactics are spliced in: for a lemma written `have h : T := value`, in place of
   `value` (as `by` and an indented block); for a goal, in place of the rest of its proof.
   Every new line is indented inside the proof, so the text can't escape it.
2. Lean checks the **whole changed file**. The card is ready only when Lean accepts the
   theorem with no errors, no `sorry`, and only the standard axioms. Errors are reported
   against the replacement's own lines when they fall inside it.
3. Applying a card checks it all again, writes the changed proof to a **new** file (the
   original is never touched), re-imports it from Lean, and confirms the theorem's
   statement is unchanged. The replaced steps are archived under `v<n>.` names, and the
   swap is recorded in the history with both file fingerprints.

Because Lean checks the whole theorem and its statement is fixed, a swap can't smuggle
in a new assumption. The new tactics can only use what is in scope where they sit, and
lemmas removed with the old proof are no longer in scope.

## Evidence

- On the bundled example, re-proving `shift_pos` with `linarith` removes the three
  `have` lines that only fed it (6 lines become 2, counting the comment). Lean accepts it.
- On AlphaProof's P2, DeepMind's comment says "The agent wastes the next 16 lines proving
  then discarding a lemma." A card that re-proves that goal (`False`, step `s7`) with only
  the direct proof that follows `exfalso` removes exactly 16 lines, and Lean accepts it.
  This is a permanent test (`lean_tests/test_cards_with_lean.py`).

## Readability

Lean can confirm that a new proof is correct, not that it is clearer. Scry reports sizes
(steps and lines replaced) and labels them as counts, never as a judgement. Replacements
may carry Lean comments, which stay in the file, so the simplified proof can explain
itself. The AI helper (Checkpoint 4) is meant to work with a person on writing proofs
that read well, with Lean as the judge of correctness.
