import Lake
open Lake DSL

/-
Scry's Lean workspace. The Lean and Mathlib versions match the public AlphaProof
release (Lean v4.10.0-rc2), so its proofs compile exactly as published.
-/
package "scry" where
  leanOptions := #[
    ⟨`autoImplicit, false⟩,
    ⟨`relaxedAutoImplicit, false⟩
  ]

require "leanprover-community" / "mathlib" @ "git#v4.10.0-rc2"

lean_lib ScryExport

@[default_target]
lean_exe «scry-export» where
  root := `ScryExport.Main
  supportInterpreter := true
