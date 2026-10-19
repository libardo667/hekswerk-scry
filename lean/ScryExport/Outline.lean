import Lean
import ScryExport.Load
import ScryExport.Statement

/-!
# The outline of a result (Lean v4.10.0-rc2)

`scry-export --outline FILE THEOREM` elaborates FILE and reports, as JSON, THEOREM and every
theorem and definition from the project that it rests on: the ones its statement and proof
use, then the ones those use, and so on. Library constants (Lean, Mathlib, ...) are not
followed. Each *part* of the outline is one declaration a person wrote, with:

* where it is written, its doc string, and its statement as Lean prints it;
* `statement_uses`: the parts its statement mentions;
* `body_uses`: the parts its body uses (a theorem's proof, a definition's value, the fields of
  a structure or the constructors of an inductive type);
* for a theorem, `unused_hypotheses`: hypotheses its proof takes and never uses.

All of it is read from Lean's own record of the finished declarations, never from their text.

Lean also makes declarations nobody wrote: pattern-match helpers, pieces of proofs it splits
off, equation lemmas. These are looked through: whatever such a helper uses counts as used by
the part that uses the helper. Constructors, field accessors and recursors count as their
structure or inductive type. An instance made by `deriving` is a part, written where its
`deriving` clause is (Lean records that place for it); see `sameWriting` for its helpers.
-/

open Lean Elab Meta
open ScryStatement (inProject isGenerated moduleOf? kindOf pp clip positionJson collectAxioms)

namespace ScryOutline

/-- An outline with more parts than this is refused rather than cut short. -/
def maxParts : Nat := 20000

/-- The structure or inductive type that a constructor, field accessor or recursor belongs to,
one step up. -/
def ownerStep? (env : Environment) (n : Name) : Option Name :=
  match env.find? n with
  | some (.ctorInfo c) => some c.induct
  | some (.recInfo _) => some n.getPrefix
  | _ =>
    match env.getProjectionFnInfo? n with
    | some info => match env.find? info.ctorName with
      | some (.ctorInfo c) => some c.induct
      | _ => none
    | none => if isAuxRecursor env n || isNoConfusion env n then some n.getPrefix else none

/-- The declaration `n` belongs to, all the way up: `Config.mk.noConfusion` belongs to the
constructor `Config.mk`, which belongs to the structure `Config`. -/
def ownerOf (env : Environment) (n : Name) : Name := Id.run do
  let mut n := n
  for _ in [0:8] do
    match ownerStep? env n with
    | some m => n := m
    | none => break
  return n

/-- Climb from `n` to the declaration named above it while Lean places both at exactly the same
spot in the file: they are one piece of writing (`deriving DecidableEq` on Lean v4.34 makes
both `instDecidableEqPt` and `instDecidableEqPt.decEq` at the `deriving` clause). A helper a
person writes with `where` has a place of its own, so it stays a part. -/
def sameWriting (n : Name) : MetaM Name := do
  let mut n := n
  for _ in [0:8] do
    let above := n.getPrefix
    if above.isAnonymous then break
    let some here ← findDeclarationRanges? n | break
    let some there ← findDeclarationRanges? above | break
    unless here.range.pos == there.range.pos && here.range.endPos == there.range.endPos do break
    n := above
  return n

structure Walk where
  /-- What each constant met so far is shown as: a part, or nothing (looked through or library). -/
  shown : NameMap (Option Name) := {}
  /-- For each looked-through constant, the parts it leads to. -/
  through : NameMap NameSet := {}

abbrev OutlineM := StateRefT Walk MetaM

/-- The part `n` is shown as, if any: a project declaration a person wrote, which Lean
records a place in a file for. -/
def shownAs? (n : Name) : OutlineM (Option Name) := do
  if let some r := (← get).shown.find? n then return r
  let env ← getEnv
  let owner ← sameWriting (ownerOf env n)
  let r := if inProject env owner && !isGenerated env owner &&
      (← findDeclarationRanges? owner).isSome then some owner else none
  modify fun w => { w with shown := w.shown.insert n r }
  return r

/-- What a looked-through constant is made of. -/
def contents : ConstantInfo → List Expr
  | .defnInfo d => [d.type, d.value]
  | .thmInfo d => [d.type, d.value]
  | other => [other.type]

mutual
  /-- The parts that using constant `c` amounts to. -/
  partial def partsFor (c : Name) : OutlineM NameSet := do
    if let some p ← shownAs? c then return NameSet.empty.insert p
    let env ← getEnv
    if !inProject env c then return {}
    if let some r := (← get).through.find? c then return r
    -- Marked before following it, so a helper that refers to itself ends.
    modify fun w => { w with through := w.through.insert c {} }
    let some info := env.find? c | return {}
    let mut out : NameSet := {}
    for e in contents info do out := out.append (← partsOf e)
    modify fun w => { w with through := w.through.insert c out }
    return out

  /-- The parts an expression uses. -/
  partial def partsOf (e : Expr) : OutlineM NameSet := do
    let mut out : NameSet := {}
    for c in e.getUsedConstants do out := out.append (← partsFor c)
    return out
end

/-- The parts that part `n` uses through the constants in `todo`. A piece of `n` itself that
Lean made (see `sameWriting`) is looked through, so what the piece uses counts. -/
partial def partsOfPart (n : Name) (todo : List Name) (seen : NameSet := {})
    (out : NameSet := {}) : OutlineM NameSet := do
  match todo with
  | [] => return out.erase n
  | c :: rest =>
    if seen.contains c then return ← partsOfPart n rest seen out
    let seen := seen.insert c
    if c != n && (← shownAs? c) == some n then
      let more := match (← getEnv).find? c with
        | some info => (contents info).foldl (fun acc e => acc ++ e.getUsedConstants.toList) []
        | none => []
      partsOfPart n (more ++ rest) seen out
    else
      partsOfPart n rest seen (out.append (← partsFor c))

/-- The expressions that make up a part's body. -/
def bodyOf (env : Environment) : ConstantInfo → List Expr
  | .defnInfo d => [d.value]
  | .thmInfo d => [d.value]
  | .inductInfo d => d.ctors.filterMap fun c => (env.find? c).map (·.type)
  | _ => []

/-- A name a person wrote, or nothing for a name Lean made up (`x✝`). -/
def written? (n : Name) : Option String :=
  if n.hasMacroScopes || n.isAnonymous then none else some (toString n)

/-- Hypotheses the statement gives the proof that the proof never uses.

This walks the proof and the statement together, along the statement's own shape: `∀` and
`→` (the proof is a `fun`), `∃`, `∧`, `↔` and `¬`. It stops at anything else, including a
definition or structure from the project, so a hypothesis written inside a definition is not
counted as one of the statement's. A hypothesis is reported when it is a proposition, the
rest of the proof never mentions it, and the rest of the statement doesn't either. -/
partial def unusedHypotheses (proof type : Expr) : MetaM (Array Json) := do
  let proof := proof.consumeMData
  let type ← whnfR (← instantiateMVars type)
  match proof with
  | .letE n t v b _ =>
    return ← withLetDecl n t v fun x => unusedHypotheses (b.instantiate1 x) type
  | _ => pure ()
  match proof, type with
  | .lam n _ b _, .forallE m t rest bi =>
    withLocalDecl m bi t fun x => do
      let mut here := #[]
      if !b.hasLooseBVar 0 && !rest.hasLooseBVar 0 && (← isProp t) then
        let name := (written? n).orElse fun _ => written? m
        here := here.push (Json.mkObj [("name", toJson name), ("statement", ← pp t)])
      return here ++ (← unusedHypotheses (b.instantiate1 x) (rest.instantiate1 x))
  | .lam .., .app (.const ``Not _) p =>
    unusedHypotheses proof (← mkArrow p (mkConst ``False))
  | _, _ =>
    let args := proof.getAppArgs
    match proof.getAppFn, type.getAppFn with
    | .const ``And.intro _, .const ``And _ =>
      if args.size == 4 then
        return (← unusedHypotheses args[2]! type.appFn!.appArg!) ++ (← unusedHypotheses args[3]! type.appArg!)
    | .const ``Iff.intro _, .const ``Iff _ =>
      if args.size == 4 then
        let (a, b) := (type.appFn!.appArg!, type.appArg!)
        return (← unusedHypotheses args[2]! (← mkArrow a b)) ++
          (← unusedHypotheses args[3]! (← mkArrow b a))
    | .const ``Exists.intro _, .const ``Exists _ =>
      if args.size == 4 then
        return ← unusedHypotheses args[3]! (type.appArg!.beta #[args[2]!])
    | _, _ => pure ()
    return #[]

def partKind (env : Environment) (n : Name) (info : ConstantInfo) : String :=
  if isClass env n then "class"
  else if isStructure env n then "structure"
  else if Meta.isInstanceCore env n then "instance"
  else if info matches .inductInfo _ then "inductive type"
  else kindOf info

def names (s : NameSet) : Json := toJson (s.toArray.map toString)

def partJson (n : Name) : OutlineM Json := do
  let env ← getEnv
  let some info := env.find? n | throwError "Scry bug: '{n}' is in the outline but not in Lean."
  let ranges ← findDeclarationRanges? n
  let statementUses ← partsOfPart n info.type.getUsedConstants.toList
  let bodyUses ← partsOfPart n ((bodyOf env info).foldl (fun acc e => acc ++ e.getUsedConstants.toList) [])
  let unused ← match info with
    | .thmInfo d => unusedHypotheses d.value d.type
    | _ => pure #[]
  return Json.mkObj [
    ("id", toString n),
    ("name", toString ((privateToUserName? n).getD n)),
    ("private", isPrivateName n),
    ("kind", partKind env n info),
    ("module", toJson ((moduleOf? env n).map toString)),
    ("start", toJson (ranges.map (positionJson ·.range.pos))),
    ("end", toJson (ranges.map (positionJson ·.range.endPos))),
    ("doc", toJson (← findDocString? env n)),
    ("statement", clip (← pp info.type)),
    ("statement_uses", names statementUses),
    ("body_uses", names bodyUses),
    ("unused_hypotheses", toJson unused)]

def outlineJson (root : Name) : OutlineM Json := do
  let env ← getEnv
  let some _ := env.find? root | throwError "There is no theorem called '{root}' in this file."
  let mut seen : NameSet := NameSet.empty.insert root
  let mut queue : Array Name := #[root]
  let mut parts : Array Json := #[]
  let mut i := 0
  while i < queue.size do
    let n := queue[i]!
    i := i + 1
    let part ← partJson n
    parts := parts.push part
    for key in ["statement_uses", "body_uses"] do
      for u in (← IO.ofExcept (part.getObjValAs? (Array String) key)) do
        let u := u.toName
        unless seen.contains u do
          if queue.size ≥ maxParts then
            throwError "'{root}' rests on more than {maxParts} declarations; Scry won't outline it."
          seen := seen.insert u
          queue := queue.push u
  return Json.mkObj [
    ("format", "hekswerk-scry/lean-outline"), ("version", 1),
    ("lean_version", Lean.versionString), ("result", toString root),
    ("axioms", toJson ((← collectAxioms root).map toString)),
    ("parts", toJson parts)]

/-- Elaborate `path` and outline `thm`. -/
unsafe def run (path : System.FilePath) (thm : Name)
    (loaded : Option ScryLoad.Loaded := none) : IO Json := do
  let done ← ScryLoad.elaborate loaded path (info := false)
  ScryLoad.requireNoErrors done
  let (inputCtx, s, opts) := (done.inputCtx, done.state, ScryLoad.options)
  let env := s.commandState.env
  let space := thm.getPrefix
  let coreCtx : Core.Context := { fileName := path.toString, fileMap := inputCtx.fileMap,
                                  options := opts, currNamespace := space,
                                  openDecls := [OpenDecl.simple space []],
                                  maxHeartbeats := 0 }
  let coreState : Core.State := { env }
  let (json, _) ← (((outlineJson thm).run' {}).run' {} {}).toIO coreCtx coreState
  return json

end ScryOutline
