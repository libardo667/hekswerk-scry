import Lake
open Lake DSL

/-
Scry's exporter, built for Lean v4.34.1 (the version openai/math uses). It imports only
Lean itself, so this project needs no Mathlib: the proofs it reads are loaded from the
project they live in, at run time.
-/
package "scry-exporter" where
  leanOptions := #[⟨`autoImplicit, false⟩, ⟨`relaxedAutoImplicit, false⟩]

lean_lib ScryExport

@[default_target]
lean_exe «scry-export» where
  root := `ScryExport.Main
  supportInterpreter := true
