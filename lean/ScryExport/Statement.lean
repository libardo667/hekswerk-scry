import Lean
import ScryExport.Load

/-!
# What a theorem actually states (Lean v4.10.0-rc2)

`scry-export --statement FILE THEOREM` elaborates FILE and reports, as JSON:

* **Anatomy.** The theorem's hypotheses (each binder: name, statement, kind), its
  conclusion, and every *project-specific* definition the statement depends on (anything
  not from Lean, Std, Mathlib or their usual packages), followed through those
  definitions' own statements and bodies, printed in full. Definitions are where the meaning
  of a formal statement can quietly differ from the published claim. Past `maxDefinitions`,
  the rest are counted but not printed; `definitions_total` says how many there are.
* **Probes, judged by Lean.** Two red flags automation can sometimes find:
  - *vacuity*: the hypotheses contradict each other, so the theorem says nothing;
  - *triviality*: the conclusion follows without any of the hypotheses.
  A probe counts as found only if a short list of standard tactics produces a proof, the
  Lean kernel accepts it as a declaration, and it relies on no axioms beyond Lean's standard
  three. A proof that needs more (`sorryAx`, through a lemma left as `sorry`, or an axiom the
  project adds) is reported apart, with its axioms: it shows nothing about the hypotheses.
  When the tactics find nothing, that says nothing either way: it is not evidence that the
  hypotheses are consistent or the result is deep.
-/

open Lean Elab Meta

namespace ScryStatement

/-- Packages whose definitions count as "library", not as part of the project. -/
def libraryRoots : List String :=
  ["Init", "Lean", "Std", "Mathlib", "Batteries", "Aesop", "Qq", "ProofWidgets", "Plausible",
   "ImportGraph", "LeanSearchClient"]

def moduleOf? (env : Environment) (n : Name) : Option Name :=
  (env.getModuleIdxFor? n).map fun idx => env.header.moduleNames[idx.toNat]!

/-- Helpers Lean generates by itself (pattern-match compilers, recursors, and the like).
Nobody wrote them, so they don't belong on a list of definitions a person should read.
A `private` declaration is named `_private.<module>.0.<name>` inside Lean, which looks like a
generated name; it is judged by the name its author wrote. -/
def isGenerated (env : Environment) (n : Name) : Bool :=
  ((privateToUserName? n).getD n).isInternal || Meta.isMatcherCore env n ||
    isAuxRecursor env n || isNoConfusion env n || isRecCore env n

/-- Defined in the file itself, or in a module outside the libraries. -/
def inProject (env : Environment) (n : Name) : Bool :=
  match moduleOf? env n with
  | none => true
  | some m => !libraryRoots.contains m.getRoot.toString

/-- A constant from the project that a person wrote. -/
def isProjectConstant (env : Environment) (n : Name) : Bool :=
  !isGenerated env n && inProject env n

/-- The axioms a constant relies on (Lean v4.10 keeps this inside `#print axioms`). -/
def collectAxioms (n : Name) : CoreM (Array Name) := do
  let (_, s) := ((Lean.Elab.Command.CollectAxioms.collect n).run (← getEnv)).run {}
  return s.axioms

def kindOf : ConstantInfo → String
  | .defnInfo _ => "definition"
  | .thmInfo _ => "theorem"
  | .axiomInfo _ => "axiom"
  | .opaqueInfo _ => "opaque definition"
  | .inductInfo _ => "inductive type or structure"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"
  | .quotInfo _ => "quotient"

def pp (e : Expr) : MetaM String := do
  return toString ((← ppExpr e).pretty 100000)

def clip (s : String) (limit : Nat := 3000) : String :=
  if s.length ≤ limit then s else s.take limit ++ " …(cut)"

/-- What a constant contributes to the meaning of a statement: its type, and for
definitions its body; for inductive types, the types of its constructors. -/
def meaningExprs (info : ConstantInfo) (env : Environment) : List Expr :=
  match info with
  | .defnInfo d => [d.type, d.value]
  | .opaqueInfo d => [d.type]
  | .inductInfo d => d.type :: d.ctors.filterMap fun c => (env.find? c).map (·.type)
  | other => [other.type]

/-- How many definitions a statement report prints. Any more are counted, not printed. -/
def maxDefinitions : Nat := 400

/-- Project constants reachable from `roots` through types and definition bodies, in the
order found (breadth first): the first `limit` of them, and how many there are in all. -/
def projectClosure (env : Environment) (roots : Array Name) (limit : Nat := maxDefinitions) :
    Array (Name × Nat) × Nat := Id.run do
  let mut seen : NameSet := {}
  let mut out : Array (Name × Nat) := #[]
  let mut total := 0
  let mut queue : Array (Name × Nat) := roots.map (·, 1)
  let mut i := 0
  while i < queue.size do
    let (n, depth) := queue[i]!
    i := i + 1
    if seen.contains n || !isProjectConstant env n then continue
    seen := seen.insert n
    let some info := env.find? n | continue
    total := total + 1
    if out.size < limit then out := out.push (n, depth)
    for e in meaningExprs info env do
      for c in e.getUsedConstants do
        if !seen.contains c then queue := queue.push (c, depth + 1)
  return (out, total)

def positionJson (p : Position) : Json := Json.mkObj [("line", p.line), ("column", p.column)]

def binderKind : BinderInfo → String
  | .default => "explicit"
  | .implicit => "implicit"
  | .strictImplicit => "strict implicit"
  | .instImplicit => "instance"

/-- Tactics tried by the probes. Each must close the goal on its own. -/
def probeTactics : List String :=
  ["simp_all", "positivity", "omega", "linarith", "nlinarith", "norm_num at *", "tauto", "decide", "aesop"]

/-- How much work each probe tactic may do, in Lean's heartbeats (as for `maxHeartbeats`).
Automation that runs past it is stopped, and that attempt counts as finding nothing. -/
def probeHeartbeats : Nat := 20000

/-- Try to close `goal` with one tactic. Returns the proof if it closes with no `sorry`. -/
def tryTactic (goal : MVarId) (text : String) : TermElabM (Option Expr) := do
  let env ← getEnv
  let .ok stx := Parser.runParserCategory env `tactic text | return none
  let saved ← saveState
  try
    let remaining ←
      withTheReader Core.Context (fun ctx => { ctx with maxHeartbeats := probeHeartbeats * 1000 }) <|
        withCurrHeartbeats <| Term.withoutErrToSorry <| Tactic.run goal (Tactic.evalTactic stx)
    let proof ← instantiateMVars (mkMVar goal)
    if remaining.isEmpty && !proof.hasSorry && !proof.hasExprMVar then
      return some proof
    saved.restore
    return none
  catch _ =>
    saved.restore
    return none

/-- The axioms any Lean proof may rely on. A probe's proof that needs another proves nothing
about the statement. -/
def standardAxioms : List Name := [``propext, ``Classical.choice, ``Quot.sound]

/-- Ask the kernel to accept `value : type` as a new theorem; report whether it did and
which axioms the result relies on, all the way down (through every lemma it uses). -/
def kernelAccepts (name : Name) (levels : List Name) (type value : Expr) :
    TermElabM (Option (Array Name)) := do
  let saved ← saveState
  try
    addDecl <| .thmDecl { name, levelParams := levels, type, value }
    let axioms ← collectAxioms name
    saved.restore
    return some axioms
  catch _ =>
    saved.restore
    return none

/-- What the tactics found: a proof on the standard axioms, if any, and the proofs that
needed more. -/
structure Finds where
  trusted : Option (String × Array Name) := none
  untrusted : Array (String × Array Name) := #[]

/-- Record a proof the kernel accepted. Stop looking once one needs only the standard axioms. -/
def Finds.add (f : Finds) (tactic : String) (axioms : Array Name) : Finds :=
  if axioms.all standardAxioms.contains then { f with trusted := some (tactic, axioms) }
  else { f with untrusted := f.untrusted.push (tactic, axioms) }

def findJson : String × Array Name → Json
  | (tactic, axioms) => Json.mkObj [("tactic", tactic), ("axioms", toJson (axioms.map toString))]

def probeResult (found : Finds) (none_msg : String) : Json :=
  let untrusted := ("untrusted", toJson (found.untrusted.map findJson))
  match found.trusted with
  | some (tactic, axioms) => Json.mkObj [
      ("found", true), ("tactic", tactic),
      ("axioms", toJson (axioms.map toString)), untrusted]
  | none => Json.mkObj [("found", false), ("note", none_msg), untrusted]

def notApplicable (why : String) : Json :=
  Json.mkObj [("found", false), ("not_applicable", true), ("note", why)]

def hasHypotheses (info : ConstantInfo) : MetaM Bool :=
  forallTelescope info.type fun xs _ => xs.anyM fun x => do Meta.isProp (← x.fvarId!.getType)

/-- Vacuity: can the tactics derive `False` from all the hypotheses? -/
def vacuityProbe (thm : Name) (info : ConstantInfo) : TermElabM Json := do
  unless ← hasHypotheses info do
    return notApplicable "The statement has no hypotheses, so there is nothing to contradict."
  let found ← forallTelescope info.type fun xs _ => do
    let mut found : Finds := {}
    for tactic in probeTactics do
      let goal ← mkFreshExprMVar (mkConst ``False) (kind := .syntheticOpaque)
      if let some proof ← tryTactic goal.mvarId! tactic then
        let type ← mkForallFVars xs (mkConst ``False)
        let value ← mkLambdaFVars xs proof
        if let some axioms ← kernelAccepts (thm ++ `scry_probe_vacuity) info.levelParams type value then
          found := found.add tactic axioms
          if found.trusted.isSome then break
    return found
  return probeResult found
    "The tactics found no contradiction among the hypotheses. That does not show they are consistent."

/-- Triviality: does the conclusion follow from the non-Prop binders alone? -/
def trivialityProbe (thm : Name) (info : ConstantInfo) : TermElabM Json := do
  unless ← hasHypotheses info do
    return notApplicable "The statement has no hypotheses to leave out."
  let found ← forallTelescope info.type fun xs body => do
    let mut kept : Array Expr := #[]
    for x in xs do
      unless ← Meta.isProp (← x.fvarId!.getType) do kept := kept.push x
    let dropped := xs.filter fun x => !kept.contains x
    let mut found : Finds := {}
    if dropped.isEmpty || dropped.any fun x => body.containsFVar x.fvarId! then
      return found
    for tactic in probeTactics do
      let goal ← mkFreshExprMVar body (kind := .syntheticOpaque)
      -- Take the hypotheses out of the context, so the tactics can't use them.
      let cleared ← goal.mvarId!.tryClearMany (dropped.map (·.fvarId!))
      if (← tryTactic cleared tactic).isSome then
        let proof ← instantiateMVars goal
        let type ← mkForallFVars kept body
        let value ← mkLambdaFVars kept proof
        if let some axioms ← kernelAccepts (thm ++ `scry_probe_trivial) info.levelParams type value then
          found := found.add tactic axioms
          if found.trusted.isSome then break
    return found
  return probeResult found
    "The tactics could not prove the conclusion without the hypotheses (or it refers to them)."

def statementJson (thm : Name) (probes : Bool) : TermElabM Json := do
  let env ← getEnv
  let some info := env.find? thm | throwError "There is no theorem called '{thm}' in this file."
  let anatomy ← forallTelescope info.type fun xs body => do
    let binders ← xs.mapM fun x => do
      let decl ← x.fvarId!.getDecl
      return Json.mkObj [
        ("name", toString decl.userName), ("type", ← pp decl.type),
        ("binder", binderKind decl.binderInfo), ("is_prop", ← Meta.isProp decl.type)]
    return (binders, ← pp body)
  let (binders, conclusion) := anatomy
  let roots := info.type.getUsedConstants
  let (closure, total) := projectClosure env roots
  let defs ← closure.mapM fun (n, depth) => do
    let some c := env.find? n | return Json.null
    let value? : Option Expr := match c with
      | .defnInfo d => some d.value
      | _ => none
    let ranges ← findDeclarationRanges? n
    let valueJson ← match value? with
      | some v => pure (toJson (← pp v))
      | none => pure Json.null
    return Json.mkObj [
      ("name", toString n), ("kind", kindOf c), ("depth", depth),
      ("type", ← pp c.type),
      ("value", valueJson),
      ("module", toJson ((moduleOf? env n).map toString)),
      ("start", toJson (ranges.map (positionJson ·.range.pos))),
      ("end", toJson (ranges.map (positionJson ·.range.endPos)))]
  let axioms ← collectAxioms thm
  let probeJson ← if probes then
      pure (Json.mkObj [("vacuity", ← vacuityProbe thm info),
                        ("triviality", ← trivialityProbe thm info),
                        ("tactics", toJson probeTactics)])
    else pure Json.null
  return Json.mkObj [
    ("format", "hekswerk-scry/lean-statement"), ("version", 1),
    ("lean_version", Lean.versionString), ("theorem", toString thm),
    ("kind", kindOf info),
    ("module", toJson ((moduleOf? env thm).map toString)),
    ("statement", ← pp info.type),
    ("binders", toJson binders), ("conclusion", conclusion),
    ("definitions", toJson (defs.filter (· != Json.null))),
    ("definitions_total", total),
    ("axioms", toJson (axioms.map toString)),
    ("probes", probeJson), ("probe_heartbeats", probeHeartbeats)]

/-- Elaborate `path` and report what `thm` states. -/
unsafe def run (path : System.FilePath) (thm : Name) (probes : Bool)
    (loaded : Option ScryLoad.Loaded := none) : IO Json := do
  -- The statement needs only the finished environment, not Lean's record of how each
  -- command was elaborated, so that record is switched off (it is slow to build).
  let done ← ScryLoad.elaborate loaded path (info := false)
  ScryLoad.requireNoErrors done
  let (inputCtx, s, opts) := (done.inputCtx, done.state, ScryLoad.options)
  let env := s.commandState.env
  -- Print names as a reader of the theorem's own namespace would write them.
  let space := thm.getPrefix
  let coreCtx : Core.Context := { fileName := path.toString, fileMap := inputCtx.fileMap,
                                  options := opts, currNamespace := space,
                                  openDecls := [OpenDecl.simple space []] }
  let coreState : Core.State := { env }
  let (json, _) ← ((statementJson thm probes).run' {} |>.run' {} {}).toIO coreCtx coreState
  return json

end ScryStatement
