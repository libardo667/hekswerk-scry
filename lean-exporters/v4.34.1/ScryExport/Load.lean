import Lean

/-!
Loading a Lean file the way Scry runs it, optionally reusing imports already loaded.

Loading a file's imports (often all of Mathlib) is most of the time Lean takes. When Scry
keeps a Lean process running (`scry-export --serve`), the environment after loading a file's
imports is kept, and a later file whose import lines are exactly the same starts from it.
Each file still starts from the environment right after its imports: nothing one file
declares, and no option it sets, is visible to the next. This is the same reuse Lean's own
editor server does when a file is edited below its imports.

A process loads one set of imports and no other. Loading a second, different set into the
same process gives a broken environment on Lean v4.34.1 (even `Fin` is unknown), so a
file with other import lines is refused with `otherImports`, and Scry runs it in another
process.
-/

open Lean Elab

namespace ScryLoad

/-- The options Scry runs Lean with. `lean/runner.py` passes the same ones to `lean`. -/
def options : Options :=
  Options.empty |>.setBool `autoImplicit false |>.setBool `relaxedAutoImplicit false

/-- The import lines this process has loaded, and the environment right after them. -/
abbrev Loaded := IO.Ref (Option (String × Environment))

/-- The error for a file whose import lines differ from the ones this process loaded.
`lean/worker.py` recognises it by this exact text. -/
def otherImports : String := "scry: this Lean process has other imports loaded"

structure Elaborated where
  inputCtx : Parser.InputContext
  source : String
  state : Frontend.State

/-- The messages `lean` itself would print. On Lean v4.34 that is each log's unreported
messages, without silent ones (see `reportMessages` in Lean/Language/Basic.lean); the
reported ones are copies already shown elsewhere, and counting them repeats messages. -/
def allMessages (log : MessageLog) : List Message :=
  log.unreported.toList.filter (!·.isSilent)

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
    | some ref => match ← ref.get with
      | some (loadedKey, env) =>
        if loadedKey == key then pure (some env) else throw (IO.userError otherImports)
      | none => pure none
    | none => pure none
  let (env, messages) ← match reuse with
    | some env => pure (env, messages)
    | none =>
      let (env, messages) ← processHeader header options messages inputCtx (trustLevel := 1024)
      if let some ref := loaded then
        unless messages.hasErrors do
          ref.set (some (key, env))
      pure (env, messages)
  -- Lean v4.34's frontend assumes the record of how each command was elaborated is kept
  -- (it reads its first entry for every command), so it stays on whatever `info` says.
  let _ := info
  let cmdState := { Command.mkState env messages options with infoState := { enabled := true } }
  let state ← IO.processCommands inputCtx parserState cmdState
  return { inputCtx, source, state }

/-- Fail, naming Lean's first errors, if the file didn't elaborate cleanly. Reading a
statement or a proof from a file Lean rejected would describe something that isn't there. -/
def requireNoErrors (done : Elaborated) : IO Unit := do
  let errors := (allMessages done.state.commandState.messages).filter
    (·.severity == .error)
  unless errors.isEmpty do
    let shown ← (errors.take 3).mapM fun m => do
      return s!"line {m.pos.line}: {(← m.data.toString).trim}"
    throw <| IO.userError <| s!"Lean reported {errors.length} error(s) in the file, so Scry " ++
      s!"won't read it. The first: " ++ String.intercalate "; " shown

end ScryLoad
