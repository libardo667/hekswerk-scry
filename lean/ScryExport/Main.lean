import ScryExport.Export

/-- `scry-export FILE THEOREM` prints the trace of THEOREM's proof in FILE as JSON. -/
unsafe def main (args : List String) : IO UInt32 := do
  match args with
  | [file, thm] =>
    try
      let json ← ScryExport.exportTheorem file thm.toName
      IO.println json.compress
      return 0
    catch e =>
      IO.eprintln s!"scry-export: {e}"
      return 1
  | _ =>
    IO.eprintln "Usage: scry-export FILE THEOREM"
    return 2
