import Lean

/-!
Loading a Lean file the way Scry runs it, optionally reusing imports already loaded.

Loading a file's imports (often all of Mathlib) is most of the time Lean takes. When Scry
keeps one Lean process running (`scry-export --serve`), the environment after loading a
file's imports is kept, and a later file whose import lines are exactly the same starts from
it. Each file still starts from the environment right after its imports: nothing one file
declares, and no option it sets, is visible to the next. This is the same reuse Lean's own
editor server does when a file is edited below its imports.
-/

open Lean Elab

namespace ScryLoad

/-- The options Scry runs Lean with. `lean/runner.py` passes the same ones to `lean`. -/
def options : Options :=
  Options.empty |>.setBool `autoImplicit false |>.setBool `relaxedAutoImplicit false

/-- Environments after loading some import lines, newest first. -/
abbrev Loaded := IO.Ref (List (String × Environment))

/-- How many sets of imports are kept loaded at once. -/
def keepAtMost : Nat := 4

structure Elaborated where
  inputCtx : Parser.InputContext
  source : String
  state : Frontend.State

/-- Every message Lean produced (this Lean version's message log). -/
def allMessages (log : MessageLog) : List Message := log.reportedPlusUnreported.toList

/-- Elaborate the file at `path`. `info` turns on Lean's record of how each command was
elaborated (needed for proof maps, and by some linters). -/
unsafe def elaborate (loaded : Option Loaded) (path : System.FilePath) (info : Bool) :
    IO Elaborated := do
  let source ← IO.FS.readFile path
  let inputCtx := Parser.mkInputContext source path.toString
  let (header, parserState, messages) ← Parser.parseHeader inputCtx
  -- The import lines exactly as written; any difference at all means loading again.
  let key := String.fromUTF8! (source.toUTF8.extract 0 parserState.pos.byteIdx)
  let reuse ← match loaded with
    | some ref => pure ((← ref.get).lookup key)
    | none => pure none
  let (env, messages) ← match reuse with
    | some env => pure (env, messages)
    | none =>
      let (env, messages) ← processHeader header options messages inputCtx (trustLevel := 1024)
      if let some ref := loaded then
        unless messages.hasErrors do
          ref.modify fun kept => ((key, env) :: kept.filter (·.1 != key)).take keepAtMost
      pure (env, messages)
  let cmdState := { Command.mkState env messages options with infoState := { enabled := info } }
  let state ← IO.processCommands inputCtx parserState cmdState
  return { inputCtx, source, state }

end ScryLoad
