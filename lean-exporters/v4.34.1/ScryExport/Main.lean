import ScryExport.Serve

open Lean

/-- `scry-export FILE THEOREM` prints the trace of THEOREM's proof in FILE as JSON.
`scry-export --statement FILE THEOREM` prints what THEOREM states.
`scry-export --statement-probes FILE THEOREM` also runs the Lean probes.
`scry-export --serve` keeps running and answers requests (see `ScryExport/Serve.lean`). -/
unsafe def main (args : List String) : IO UInt32 := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  try
    match args with
    | ["--serve"] => return (← ScryServe.serve)
    | [file, thm] =>
      IO.println (← ScryExport.exportTheorem file thm.toName).compress
    | ["--statement", file, thm] =>
      IO.println (← ScryStatement.run file thm.toName false).compress
    | ["--statement-probes", file, thm] =>
      IO.println (← ScryStatement.run file thm.toName true).compress
    | _ =>
      IO.eprintln "Usage: scry-export [--statement | --statement-probes] FILE THEOREM, or --serve"
      return (2 : UInt32)
    return (0 : UInt32)
  catch e =>
    IO.eprintln s!"scry-export: {e}"
    return (1 : UInt32)
