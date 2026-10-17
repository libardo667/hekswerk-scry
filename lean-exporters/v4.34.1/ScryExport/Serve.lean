import ScryExport.Load
import ScryExport.Export
import ScryExport.Statement

/-!
`scry-export --serve`: one Lean process that answers many requests, keeping imports loaded.

Each request is one line of JSON on standard input:
`{"id": ..., "mode": "check" | "export" | "statement" | "statement-probes", "file": ..., "theorem": ...}`.
Each reply is one line on standard output starting with `scry-reply `, then JSON with the
same `id` and either `"result"` or `"error"`. Anything the file itself prints while Lean
elaborates it is captured and returned in `"printed"`, never mixed into the replies.

`check` returns Lean's messages exactly as `lean --json` prints them; Scry judges them with
the same code it uses for a fresh `lean` run.
-/

open Lean Elab

namespace ScryServe

unsafe def checkJson (loaded : ScryLoad.Loaded) (file : String) : IO Json := do
  let done ← ScryLoad.elaborate (some loaded) file (info := true)
  let messages ← (ScryLoad.allMessages done.state.commandState.messages).mapM (·.toJson)
  return Json.mkObj [("messages", Json.arr messages.toArray)]

unsafe def handle (loaded : ScryLoad.Loaded) (request : Json) : IO Json := do
  let mode ← IO.ofExcept (request.getObjValAs? String "mode")
  let file ← IO.ofExcept (request.getObjValAs? String "file")
  let thm ← IO.ofExcept (request.getObjValAs? String "theorem")
  match mode with
  | "check" => checkJson loaded file
  | "export" => ScryExport.exportTheorem file thm.toName (some loaded)
  | "statement" => ScryStatement.run file thm.toName false (some loaded)
  | "statement-probes" => ScryStatement.run file thm.toName true (some loaded)
  | other => throw <| IO.userError s!"unknown mode '{other}'"

unsafe def serve : IO UInt32 := do
  let loaded : ScryLoad.Loaded ← IO.mkRef []
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  repeat
    let line ← stdin.getLine
    if line.trim.isEmpty then break
    let id := (Json.parse line |>.toOption).bind (·.getObjVal? "id" |>.toOption) |>.getD Json.null
    let (printed, reply) ← IO.FS.withIsolatedStreams do
      try
        let request ← IO.ofExcept (Json.parse line)
        pure (Json.mkObj [("id", id), ("result", ← handle loaded request)])
      catch e =>
        pure (Json.mkObj [("id", id), ("error", toString e)])
    let reply := reply.setObjVal! "printed" (Json.str printed)
    stdout.putStrLn s!"scry-reply {reply.compress}"
    stdout.flush
  return (0 : UInt32)

end ScryServe
