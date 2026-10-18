import Lean
import ScryExport.Load
import Std.Data.HashMap

/-!
# Scry's Lean exporter (Lean v4.34.1)

Elaborates one Lean file and writes out a *trace* of one theorem's tactic proof as JSON.
Python (`hekswerk_scry.lean.importer`) turns the trace into a Scry proof map.

The trace records, for every tactic step:

* the goal(s) the step works on;
* the *holes* it leaves: goals that later steps (or nested `by` blocks) must prove;
* which hypotheses its own piece of the final proof actually uses;
* which hypotheses it introduces with a justification (as `have`, `suffices`, `obtain := ...`
  do), and which holes that justification relies on.

All of this is read from Lean's own record of the finished proof (the metavariable
assignments it made), not from the tactic text, so it reflects what Lean actually did.

How "its own piece" is found: in Lean's final record of the proof, every goal is filled in by
some term. For a step, we take that record, temporarily forget how every *other* step's goal
was filled in, and read back this step's goal. What comes back is exactly this step's
contribution, with the other steps' goals left as holes.
-/

open Lean Elab Meta

namespace ScryExport

/-- Syntax kinds that only arrange other tactics. They are never steps themselves. -/
def layoutKinds : List Name :=
  [ `Lean.Parser.Tactic.tacticSeq, `Lean.Parser.Tactic.tacticSeq1Indented,
    `Lean.Parser.Tactic.tacticSeqBracketed, `Lean.Parser.Term.byTactic,
    `Lean.Parser.Term.byTactic', `by, `Lean.cdot, `Lean.cdotTk,
    `Lean.Parser.Tactic.paren, `Lean.Parser.Tactic.focus, `«;», nullKind ]

/-- A `by` block written inside a term. Tactics inside one are steps of their own. -/
def isByBlock (stx : Syntax) : Bool :=
  stx.getKind == `Lean.Parser.Term.byTactic || stx.getKind == `Lean.Parser.Term.byTactic'

structure Found where
  ctx : ContextInfo
  info : TacticInfo
  parent? : Option Nat

structure Collected where
  steps : Array Found := #[]
  /-- The outermost `by` block of the theorem: its record holds the finished proof. -/
  top? : Option (ContextInfo × TacticInfo) := none
  /-- The goals of `by` blocks nested inside terms, such as `pow_pos (by linarith) 3`,
  with the step they are written in. -/
  nestedBlocks : Array (MVarId × Option Nat) := #[]

def belongsTo (thm : Name) (ctx : ContextInfo) : Bool :=
  match ctx.parentDecl? with
  | some n => thm.isPrefixOf n
  | none => false

/-- Source ranges of the `by` blocks written inside a step, such as the one in
`have h : T := by tac`. Tactics inside them are steps of their own. -/
partial def byBlockRanges (stx : Syntax) : Array (String.Pos.Raw × String.Pos.Raw) :=
  let here := if isByBlock stx then
      match stx.getPos? (canonicalOnly := true), stx.getTailPos? (canonicalOnly := true) with
      | some a, some b => #[(a, b)]
      | _, _ => #[]
    else #[]
  here ++ stx.getArgs.foldl (fun acc arg => acc ++ byBlockRanges arg) #[]

/-- Walk the info tree, collecting the theorem's steps.
`insideStep` is true while we are inside a step: tactics there belong to that step
(for example the inner tactic of `t₁ <;> t₂`), unless they are written inside one of the
step's own `by` blocks (`byRanges`). -/
partial def collect (thm : Name) (ctx? : Option ContextInfo) (parent? : Option Nat)
    (insideStep : Bool) (byRanges : Array (String.Pos.Raw × String.Pos.Raw)) :
    InfoTree → StateT Collected IO Unit
  | .context pci t => collect thm (pci.mergeIntoOuter? ctx?) parent? insideStep byRanges t
  | .hole _ => pure ()
  | .node info children => do
    let descend := fun (parent? : Option Nat) (insideStep : Bool) byRanges => do
      for c in children do collect thm ctx? parent? insideStep byRanges c
    let (some ctx, .ofTacticInfo ti) := (ctx?, info) | descend parent? insideStep byRanges
    if !belongsTo thm ctx then
      descend parent? insideStep byRanges
      return
    if isByBlock ti.stx then
      if (← get).top?.isNone then
        modify fun s => { s with top? := some (ctx, ti) }
      else if let some g := ti.goalsBefore.head? then
        -- Only blocks written in the source have steps inside them. Blocks that tactics
        -- generate for themselves (as `use` does to tidy up) stay part of their step.
        if (ti.stx.getPos? (canonicalOnly := true)).isSome then
          modify fun s => { s with nestedBlocks := s.nestedBlocks.push (g, parent?) }
      descend parent? insideStep byRanges
      return
    let start? := ti.stx.getPos? (canonicalOnly := true)
    let stop? := ti.stx.getTailPos? (canonicalOnly := true)
    let inOwnBlock := match start?, stop? with
      | some a, some b => byRanges.any fun (x, y) => x ≤ a && b ≤ y
      | _, _ => false
    if start?.isNone || layoutKinds.contains ti.stx.getKind || (insideStep && !inOwnBlock) then
      descend parent? insideStep byRanges
      return
    let index := (← get).steps.size
    modify fun s => { s with steps := s.steps.push { ctx, info := ti, parent? } }
    descend (some index) true (byBlockRanges ti.stx)

/-- Unassigned holes reachable from `e`: boundary goals, looking through delayed assignments. -/
partial def holesIn (boundary : MVarIdSet) (e : Expr) : MetaM (Array MVarId) := do
  let mut out := #[]
  for m in (e.collectMVars {}).result do
    if boundary.contains m then
      out := out.push m
    else if let some d ← getDelayedMVarAssignment? m then
      if boundary.contains d.mvarIdPending then
        out := out.push d.mvarIdPending
      else
        out := out ++ (← holesIn boundary (← instantiateMVars (mkMVar d.mvarIdPending)))
  return out

/-- A hypothesis introduced by a step, with the term that justifies it (if any). -/
structure Introduced where
  fvar : FVarId
  value? : Option Expr

/-- When `?m` is an internal placeholder (not another step's goal), fill in the hypotheses
it binds and hand the remaining arguments to the term inside it. -/
def stepThroughPending? (boundary : MVarIdSet) (m : MVarId) (args : Array Expr) :
    MetaM (Option Expr) := do
  let some d ← getDelayedMVarAssignment? m | return none
  if boundary.contains d.mvarIdPending || args.size < d.fvars.size then return none
  let pending ← instantiateMVars (mkMVar d.mvarIdPending)
  let filled := pending.replaceFVars d.fvars args[:d.fvars.size]
  return some (mkAppN filled args[d.fvars.size:]).headBeta

/-- Find hypotheses introduced inside `e`: each delayed-assigned hole `?d a₁ … aₙ` stands for a
goal with new hypotheses. If the argument for a hypothesis is bound by a `have`-style binder
(`letFun v (fun h => …)`, `let h := v; …`, or `(fun h => …) v`), then `v` justifies it.
A plain `fun h => …` (as from `intro`) gives no justification. -/
partial def introduced (boundary : MVarIdSet) (e : Expr) (stack : List (Option Expr)) :
    MetaM (Array Introduced) := do
  match e with
  | .app (.lam _ t b _) v => do
    return (← introduced boundary t stack) ++ (← introduced boundary v stack) ++ (← introduced boundary b (some v :: stack))
  | .letE _ t v b _ => do
    return (← introduced boundary t stack) ++ (← introduced boundary v stack) ++ (← introduced boundary b (some v :: stack))
  | .lam _ t b _ | .forallE _ t b _ => do
    return (← introduced boundary t stack) ++ (← introduced boundary b (none :: stack))
  | .mdata _ b | .proj _ _ b => introduced boundary b stack
  | .app .. => do
    let fn := e.getAppFn
    let args := e.getAppArgs
    if e.isAppOfArity ``letFun 4 then
      if let .lam _ t b _ := args[3]! then
        return (← introduced boundary args[2]! stack) ++ (← introduced boundary t stack) ++
          (← introduced boundary b (some args[2]! :: stack))
    let mut out := #[]
    -- `(fun h₁ … hₖ => body) v₁ … vₖ`: each vᵢ justifies the matching hᵢ.
    if fn.isLambda then
      let mut body := fn
      let mut inner := stack
      let mut used := 0
      for a in args do
        if let .lam _ t b _ := body then
          out := out ++ (← introduced boundary t inner) ++ (← introduced boundary a stack)
          inner := some a :: inner
          body := b
          used := used + 1
      out := out ++ (← introduced boundary body inner)
      for a in args[used:] do out := out ++ (← introduced boundary a stack)
      return out
    if let .mvar m := fn then
      if let some d ← getDelayedMVarAssignment? m then
        for i in [0:d.fvars.size] do
          if h : i < args.size then
            let value? := match args[i] with
              | .bvar k => (stack[k]?).join
              | other => some other
            out := out.push { fvar := d.fvars[i]!.fvarId!, value? }
        -- An internal placeholder (not another step's goal) can hide more of the step, for
        -- example when `rcases` or `rw ... at h` sets hypotheses aside and brings them back.
        if let some rest ← stepThroughPending? boundary m args then
          out := out ++ (← introduced boundary rest stack)
    else
      out := out ++ (← introduced boundary fn stack)
    for a in args do out := out ++ (← introduced boundary a stack)
    return out
  | _ => return #[]

/-- Free hypotheses used by `e`, not counting the parts inside `skip` (justification terms,
which are accounted for separately). Arguments handed to a boundary hole (`?d h₁ … hₙ`) only
pass the context along to a later goal, so they are not uses either; internal placeholders are
stepped through so uses inside `rcases`, `obtain`, and `rw ... at` are still seen. -/
partial def usesOutside (boundary : MVarIdSet) (skip : Array Expr) (e : Expr) :
    MetaM (Array FVarId) := do
  if skip.any (· == e) then return #[]
  if e.isApp && e.getAppFn.isMVar then
    if let .mvar m := e.getAppFn then
      if let some rest ← stepThroughPending? boundary m e.getAppArgs then
        return ← usesOutside boundary skip rest
    return #[]
  match e with
  | .fvar f => return #[f]
  | .app f a => return (← usesOutside boundary skip f) ++ (← usesOutside boundary skip a)
  | .lam _ t b _ | .forallE _ t b _ =>
    return (← usesOutside boundary skip t) ++ (← usesOutside boundary skip b)
  | .letE _ t v b _ =>
    return (← usesOutside boundary skip t) ++ (← usesOutside boundary skip v) ++
      (← usesOutside boundary skip b)
  | .mdata _ b | .proj _ _ b => usesOutside boundary skip b
  | _ => return #[]

/-- When Lean finishes a term such as `pow_pos (by linarith) 3`, it copies the finished `by`
block into the surrounding proof, so no hole is left behind. Put the holes back: replace each
copy of a nested block's finished proof with that block's goal. When several blocks have
identical proofs (as in `⟨by left, by left⟩`), each copy is matched to a different block. -/
partial def restoreNestedHoles (blocks : Array (MVarId × Expr)) (e : Expr) : Expr :=
  if blocks.isEmpty then e else (go e).run' #[]
where
  go (sub : Expr) : StateM (Array MVarId) Expr := do
    if !(sub.hasMVar || sub.isFVar || sub.isConst || sub.isSort || sub.isLit) then
      let used ← get
      if let some (m, _) := blocks.find? fun (m, v) =>
          !used.contains m && sub.hash == v.hash && sub == v then
        modify (·.push m)
        return mkMVar m
    match sub with
    | .app f a => return .app (← go f) (← go a)
    | .lam n t b bi => return .lam n (← go t) (← go b) bi
    | .forallE n t b bi => return .forallE n (← go t) (← go b) bi
    | .letE n t v b nd => return .letE n (← go t) (← go v) (← go b) nd
    | .mdata d b => return .mdata d (← go b)
    | .proj n i b => return .proj n i (← go b)
    | other => return other

/-- The term after `:=` in a step such as `have h : T := v` or `obtain ⟨a, b⟩ := v`.
A Simplification card that re-proves `h` replaces exactly this part of the source. -/
partial def valueAfterAssign? (stx : Syntax) : Option Syntax :=
  match stx with
  | .node _ _ args => Id.run do
    for i in [0:args.size] do
      let a := args[i]!
      if a.isAtom && a.getAtomVal == ":=" && i + 1 < args.size then
        return some args[i + 1]!
    for a in args do
      if let some v := valueAfterAssign? a then return some v
    return none
  | _ => none

def dedup {α : Type} [BEq α] (xs : Array α) : Array α :=
  xs.foldl (fun acc x => if acc.contains x then acc else acc.push x) #[]

def pp (e : Expr) : MetaM String := do
  return toString ((← ppExpr e).pretty 100000)

def posJson (fileMap : FileMap) (pos : String.Pos.Raw) : Json :=
  let p := fileMap.toPosition pos
  Json.mkObj [("line", p.line), ("column", p.column)]

def mvarKey (m : MVarId) : String := toString m.name
def fvarKey (f : FVarId) : String := toString f.name

structure Seen where
  goals : Std.HashMap MVarId Json := {}
  hyps : Std.HashMap FVarId Json := {}

def recordGoal (m : MVarId) : StateT Seen MetaM Unit := do
  if (← get).goals.contains m then return
  if !(← getMCtx).decls.contains m then return
  let decl ← m.getDecl
  let target ← withLCtx decl.lctx decl.localInstances (pp (← instantiateMVars decl.type))
  modify fun s => { s with goals := s.goals.insert m (Json.mkObj [("target", target)]) }

def recordHyp (owner : MVarId) (f : FVarId) (fromStatement : Bool) : StateT Seen MetaM Unit := do
  if (← get).hyps.contains f then return
  if !(← getMCtx).decls.contains owner then return
  let decl ← owner.getDecl
  let some ldecl := decl.lctx.find? f | return
  let (type, isProp) ← withLCtx decl.lctx decl.localInstances do
    let ty ← instantiateMVars ldecl.type
    return (← pp ty, ← Meta.isProp ty)
  modify fun s => { s with hyps := s.hyps.insert f (Json.mkObj [
    ("name", toString ldecl.userName), ("type", type), ("is_prop", isProp),
    ("from_statement", fromStatement), ("is_auxiliary", ldecl.isImplementationDetail)]) }

/-- Build the trace for theorem `thm` from the collected steps. -/
def buildTrace (thm : Name) (fileMap : FileMap) (source : String) (c : Collected) :
    MetaM Json := do
  let some (_, top) := c.top? | throwError "found no tactic proof (`by ...`) for {thm}"
  let some root := top.goalsBefore.head? | throwError "the proof of {thm} has no goal"
  let final := top.mctxAfter
  -- Tactics that try something and back out (as `use` and `first` can) leave records of
  -- the abandoned attempt, whose goals are not part of the finished proof. Ignore those.
  let inProof := fun (m : MVarId) => final.decls.contains m
  -- Which goals does each step work on? Those it found open and Lean filled in during it,
  -- and which are still filled in in the finished proof.
  let consumed : Array (List MVarId) := c.steps.map fun s =>
    s.info.goalsBefore.filter fun g =>
      s.info.mctxAfter.eAssignment.contains g && inProof g && final.eAssignment.contains g
  let nested := c.nestedBlocks.filter fun (m, _) => inProof m
  let everyConsumed : MVarIdSet := consumed.foldl (fun acc gs => gs.foldl (·.insert ·) acc)
    (nested.foldl (fun acc (m, _) => acc.insert m) {})
  -- Goals a step leaves behind that no step ever works on, but which are filled in in the
  -- finished proof: Lean closed them itself (by unification, instance search, or a tactic's
  -- own clean-up). They count as part of the step that left them, not as holes.
  let closedByLean : MVarIdSet := c.steps.foldl (init := {}) fun acc s =>
    s.info.goalsAfter.foldl (init := acc) fun acc g =>
      if inProof g && final.eAssignment.contains g && !everyConsumed.contains g then
        acc.insert g
      else acc
  setMCtx final
  let blockValues ← nested.mapM fun (m, owner) => do
    return (m, owner, ← instantiateMVars (mkMVar m))
  let rootLocals := (final.getDecl root).lctx
  let mut seen : Seen := {}
  let mut stepsJson := #[]
  for i in [0:c.steps.size] do
    let some s := c.steps[i]? | continue
    let own := consumed[i]!
    let after := s.info.goalsAfter.filter fun g => inProof g && !closedByLean.contains g
    let boundary := after.foldl (·.insert ·)
      (own.foldl (fun acc g => acc.erase g) everyConsumed)
    -- Forget how the other steps filled their goals, then read back this step's own piece.
    let erased := Std.TreeSet.foldl (fun m b =>
      { m with eAssignment := m.eAssignment.erase b, dAssignment := m.dAssignment.erase b })
      final boundary
    let mut parts := #[]
    let mut introsJson := #[]
    for g in own do
      setMCtx erased
      -- Only blocks written inside this very step: identical proofs elsewhere don't count.
      let others := blockValues.filterMap fun (m, owner, v) =>
        if owner == some i && m != g then some (m, v) else none
      let term := restoreNestedHoles others (← instantiateMVars (mkMVar g))
      let found ← introduced boundary term []
      let allHoles := dedup (← holesIn boundary term)
      let mut values : Array Expr := #[]
      let mut valueHoles : Array MVarId := #[]
      for item in found do
        -- A hypothesis passed along unchanged (its "value" is itself) is not a new fact.
        if item.value? == some (.fvar item.fvar) then continue
        -- The hypothesis lives in the context of the goal(s) that follow. Temporary
        -- bindings that vanish before the step ends, and local value definitions (`let n : ℤ`),
        -- belong to the step itself rather than introducing a separate fact.
        let some owner := after.find? fun a => (final.getDecl a).lctx.contains item.fvar
          | continue
        if let some v := item.value? then
          let ownerDecl := final.getDecl owner
          let some ldecl := ownerDecl.lctx.find? item.fvar | continue
          setMCtx final
          let isProp ← withLCtx ownerDecl.lctx ownerDecl.localInstances do
            Meta.isProp (← instantiateMVars ldecl.type)
          setMCtx erased
          if !isProp then continue
          values := values.push v
          let vh := dedup (← holesIn boundary v)
          valueHoles := valueHoles ++ vh
          let vUses := dedup (← usesOutside boundary #[] v)
          setMCtx final
          let (_, s') ← (do
              for h in vh do recordGoal h
              for f in vUses do recordHyp g f (rootLocals.contains f)
              recordHyp owner item.fvar false).run seen
          seen := s'
          -- A hypothesis passed along unchanged under a new identity is the same fact.
          let aliasOf := match v with
            | .fvar f => toJson (fvarKey f)
            | _ => Json.null
          introsJson := introsJson.push <| Json.mkObj [
            ("hypothesis", fvarKey item.fvar),
            ("alias_of", aliasOf),
            ("value_holes", toJson (vh.map mvarKey)),
            ("uses", toJson (vUses.map fvarKey))]
          setMCtx erased
      let bodyHoles := allHoles.filter fun h => !valueHoles.contains h
      let uses := dedup (← usesOutside boundary values term)
      setMCtx final
      let (_, s') ← (do
          recordGoal g
          for h in bodyHoles do recordGoal h
          for f in uses do recordHyp g f (rootLocals.contains f)).run seen
      seen := s'
      parts := parts.push <| Json.mkObj [
        ("goal", mvarKey g),
        ("holes", toJson (bodyHoles.map mvarKey)),
        ("uses", toJson (uses.map fvarKey))]
    setMCtx final
    let stx := s.info.stx
    let start := stx.getPos?.getD 0
    let stop := stx.getTailPos?.getD start
    let valueRange := match valueAfterAssign? stx with
      | some v => match v.getPos? (canonicalOnly := true), v.getTailPos? (canonicalOnly := true) with
        | some a, some b => Json.mkObj [("start", posJson fileMap a), ("end", posJson fileMap b)]
        | _, _ => Json.null
      | none => Json.null
    stepsJson := stepsJson.push <| Json.mkObj [
      ("index", i),
      ("parent", toJson s.parent?),
      ("kind", toString stx.getKind),
      ("code", (Substring.Raw.mk source start stop).toString),
      ("start", posJson fileMap start),
      ("end", posJson fileMap stop),
      ("parts", toJson parts),
      ("introduces", toJson introsJson),
      ("leaves", toJson (after.map mvarKey)),
      ("value_range", valueRange)]
  setMCtx final
  let (_, s') ← (recordGoal root).run seen
  seen := s'
  let rootDecl := final.getDecl root
  let startingFacts ← withLCtx rootDecl.lctx rootDecl.localInstances do
    let mut out := #[]
    for ldecl in rootLocals do
      if ldecl.isImplementationDetail then continue
      let ty ← instantiateMVars ldecl.type
      if ← Meta.isProp ty then
        out := out.push <| Json.mkObj [
          ("hypothesis", fvarKey ldecl.fvarId), ("name", toString ldecl.userName),
          ("type", ← pp ty)]
    return out
  let goalsJson := Json.mkObj (seen.goals.toList.map fun (m, j) => (mvarKey m, j))
  let hypsJson := Json.mkObj (seen.hyps.toList.map fun (f, j) => (fvarKey f, j))
  return Json.mkObj [
    ("format", "hekswerk-scry/lean-trace"),
    ("version", 1),
    ("lean_version", Lean.versionString),
    ("theorem", toString thm),
    ("root_goal", mvarKey root),
    ("starting_facts", toJson startingFacts),
    ("goals", goalsJson),
    ("hypotheses", hypsJson),
    ("steps", toJson stepsJson)]

/-- Elaborate `path` and return the trace of theorem `thm` as JSON. -/
unsafe def exportTheorem (path : System.FilePath) (thm : Name)
    (loaded : Option ScryLoad.Loaded := none) : IO Json := do
  let done ← ScryLoad.elaborate loaded path (info := true)
  ScryLoad.requireNoErrors done
  let (inputCtx, source, s) := (done.inputCtx, done.source, done.state)
  let (_, collected) ← (s.commandState.infoState.trees.toList.forM
    (collect thm none none false #[])).run {}
  let some (ctx, _) := collected.top?
    | throw <| IO.userError s!"No tactic proof of '{thm}' was found in {path}."
  ctx.runMetaM {} (buildTrace thm inputCtx.fileMap source collected)

end ScryExport
