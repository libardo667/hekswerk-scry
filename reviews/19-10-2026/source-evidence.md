# Source evidence — exact reviewed snapshot

Line numbers below refer to the original repository files, not this combined document. Archive SHA-256: `0a648d2a9a0604a2ed883c91fa81269ba0d34fa76a841468ed117088ada0351a`. Files were read from the uploaded archive; these are not assertions about a later remote checkout.

## F1 — statement cache and import-build ordering

`src/hekswerk_scry/lean/statement.py`

```text
 118 | def read_statement(
 119 |     workspace: LeanWorkspace, path: Path, theorem: str, *, probes: bool = True,
 120 |     timeout: float = TIMEOUT_SECONDS,
 121 | ) -> StatementReport:
 122 |     """Ask Lean what `theorem` in `path` states, and optionally run the probes."""
 123 |     if not workspace.exporter.is_file():
 124 |         raise StatementError(f"Scry's exporter for {workspace.toolchain} isn't built. "
 125 |                              "Run `make lean-setup`.")
 126 |     stored = stored_result_path(workspace, path, theorem, probes=probes)
 127 |     if stored.is_file():
 128 |         record = json.loads(stored.read_text(encoding="utf-8"))
 129 |         saved = record["evidence"]
 130 |         evidence = LeanRunEvidence(**{**saved, "command": tuple(saved["command"])})
 131 |         report = report_from_json(record["report"], workspace.relative(path), evidence)
 132 |         return replace(report, reused_from=str(record["ran_at"]))
 133 |     workspace.build_imports(path)
 134 |     mode = "statement-probes" if probes else "statement"
 135 |     data, evidence = run_exporter(workspace, mode, path, theorem, timeout,
 136 |                                   STATEMENT_FORMAT, StatementError)
 137 |     report = report_from_json(data, workspace.relative(path), evidence)
 138 |     stored.parent.mkdir(parents=True, exist_ok=True)
 139 |     stored.write_text(json.dumps({
 140 |         "ran_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "report": data,
 141 |         "evidence": {**evidence.to_dict(), "seconds": evidence.seconds},
 142 |     }), encoding="utf-8")
 143 |     return report
```

```text
 189 | def stored_result_path(
 190 |     workspace: LeanWorkspace, path: Path, theorem: str, *, probes: bool
 191 | ) -> Path:
 192 |     """Where a statement result is stored. It changes when anything that could change
 193 |     Lean's answer changes: the file's contents, the theorem, the Lean version, the exporter
 194 |     build, or whether probes ran."""
 195 |     key = fingerprint_data({
 196 |         "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "theorem": theorem,
 197 |         "toolchain": workspace.toolchain, "probes": probes,
 198 |         "exporter_sha256": hashlib.sha256(workspace.exporter.read_bytes()).hexdigest(),
 199 |     }).split(":")[1]
 200 |     return workspace.root / STORE_FOLDER / f"{key}.json"
 201 | 
```

## F2 — fresh-run status and judgment

`src/hekswerk_scry/lean/runner.py`

```text
  92 |     """
  93 |     workspace.build_imports(path)
  94 |     text = source_text if source_text is not None else path.read_text(encoding="utf-8")
  95 |     digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
  96 |     run_dir = workspace.root / RUNS_FOLDER / digest[:16]
  97 |     run_dir.mkdir(parents=True, exist_ok=True)
  98 |     run_file = run_dir / "Check.lean"
  99 |     run_file.write_text(f"{text.rstrip()}\n\n#print axioms {theorem}\n", encoding="utf-8")
 100 | 
 101 |     worker = None if fresh else worker_for(workspace, run_file)
 102 |     command: list[str] = [str(workspace.lake), "env", "lean", "--json", *LEAN_OPTIONS,
 103 |                           str(run_file)]
 104 |     started = time.monotonic()
 105 |     if worker is not None:
 106 |         reply = worker.ask("check", run_file, theorem, timeout=timeout)
 107 |         command = list(reply.command)
 108 |         messages_json = (reply.result or {}).get("messages", [])
 109 |         stdout = "\n".join([*(json.dumps(m) for m in messages_json), *reply.printed])
 110 |         stderr, timed_out = "", reply.timed_out
 111 |         exit_code = None if reply.timed_out else 0
 112 |     else:
 113 |         stdout, stderr, timed_out, exit_code = _run_fresh(workspace, command, timeout)
 114 |     seconds = time.monotonic() - started
 115 |     evidence = LeanRunEvidence(
 116 |         command=tuple(command),
 117 |         exit_code=exit_code,
 118 |         timed_out=timed_out,
 119 |         output_sha256=hashlib.sha256((stdout + "\0" + stderr).encode("utf-8")).hexdigest(),
 120 |         seconds=seconds,
 121 |     )
 122 |     return _judged(workspace, path, theorem, digest, evidence, stdout, stderr, timeout)
 123 | 
 124 | 
 125 | def _run_fresh(
 126 |     workspace: LeanWorkspace, command: list[str], timeout: float
 127 | ) -> tuple[str, str, bool, int | None]:
 128 |     done = run_program(command, cwd=workspace.root, env=workspace.environment(),
 129 |                        timeout=timeout)
 130 |     return done.stdout, done.stderr, done.timed_out, done.exit_code
 131 | 
 132 | 
 133 | def _judged(
 134 |     workspace: LeanWorkspace, path: Path, theorem: str, digest: str, evidence: LeanRunEvidence,
 135 |     stdout: str, stderr: str, timeout: float,
 136 | ) -> LeanCheck:
 137 |     timed_out, seconds = evidence.timed_out, evidence.seconds
 138 |     messages, other = parse_output(stdout)
 139 |     other += tuple(line for line in stderr.splitlines() if line.strip())
 140 |     axioms = find_axioms(messages, theorem)
 141 |     problems = judge(messages, axioms, theorem, timed_out=timed_out, timeout=timeout)
 142 |     passed = not problems
 143 |     recorded = workspace.relative(path)
 144 |     summary = (
 145 |         f"Lean-checked: Lean accepts '{theorem}' with no errors, no sorry, and only the "
 146 |         "standard axioms."
 147 |         if passed
 148 |         else f"Not proven by Lean: {problems[0]}"
 149 |     )
 150 |     receipt = Receipt.from_lean_run(
 151 |         evidence,
 152 |         subject=f"theorem '{theorem}' in {recorded}",
 153 |         subject_fingerprint=fingerprint_data(
 154 |             {
 155 |                 "file_sha256": digest,
 156 |                 "theorem": theorem,
 157 |                 "toolchain": workspace.toolchain,
 158 |                 "mathlib": workspace.mathlib_revision,
 159 |                 "options": list(LEAN_OPTIONS),
 160 |             }
 161 |         ),
 162 |         passed=passed,
 163 |         summary=summary,
 164 |     )
 165 |     return LeanCheck(
 166 |         file=recorded,
 167 |         theorem=theorem,
 168 |         passed=passed,
 169 |         problems=problems,
 170 |         messages=messages,
 171 |         axioms=axioms,
 172 |         other_output=other,
 173 |         seconds=seconds,
 174 |         receipt=receipt,
 175 |     )
```

```text
 223 | def judge(
 224 |     messages: tuple[LeanMessage, ...],
 225 |     axioms: tuple[str, ...] | None,
 226 |     theorem: str,
 227 |     *,
 228 |     timed_out: bool = False,
 229 |     timeout: float = DEFAULT_TIMEOUT_SECONDS,
 230 | ) -> tuple[str, ...]:
 231 |     """Plain-English reasons the theorem is not proven. Empty means it is."""
 232 |     if timed_out:
 233 |         return (f"Lean took longer than {timeout:.0f} seconds and was stopped.",)
 234 |     problems: list[str] = []
 235 |     errors = [m for m in messages if m.is_error]
 236 |     if errors:
 237 |         first = errors[0]
 238 |         problems.append(
 239 |             f"Lean reported {len(errors)} error(s). The first, at line {first.line}: "
 240 |             f"{_first_line(first.text)}"
 241 |         )
 242 |     if any("declaration uses 'sorry'" in m.text for m in messages):
 243 |         problems.append("The proof uses `sorry`, Lean's placeholder for a missing proof.")
 244 |     if axioms is None:
 245 |         if not errors:
 246 |             problems.append(f"Lean did not report on a theorem called '{theorem}' in this file.")
 247 |     else:
 248 |         extra = sorted(set(axioms) - STANDARD_AXIOMS)
 249 |         # After an error, Lean patches the broken spot with `sorry` itself, so `sorryAx`
 250 |         # then shows up even though the author never wrote `sorry`.
 251 |         if "sorryAx" in extra and not errors and not any("sorry" in p for p in problems):
 252 |             problems.append("The proof uses `sorry`, Lean's placeholder for a missing proof.")
 253 |         extra = [a for a in extra if a != "sorryAx"]
 254 |         if extra:
 255 |             problems.append(
 256 |                 "The proof relies on axioms beyond Lean's standard three: " + ", ".join(extra) + "."
 257 |             )
 258 |     return tuple(problems)
```

## F3 — proof status supplied to the auditor

`src/hekswerk_scry/ai/audit.py`

```text
  70 | PROVED_CHALLENGE = ("This statement is a comparator challenge: Lean has checked a proof of it, "
  71 |                     "and that proof settles the formal statement and nothing more.")
```

```text
 152 | def audit_challenge(client: OpenRouterClient, name: str, log_folder: Path | None = None) -> Audit:
 153 |     item = openai_math.challenge(name)
 154 |     workspace = workspace_for_file(item.statement_file)
 155 |     papers, paper_files = paper_files_for(item)
 156 |     reports = {theorem: read_statement(workspace, item.statement_file, theorem)
 157 |                for theorem in item.theorem_names}
 158 |     toolbox = StatementToolbox(
 159 |         workspace=workspace, statement_file=item.statement_file,
 160 |         solution_module=item.solution_module, reports=reports, paper_files=paper_files,
 161 |     )
 162 |     prompt = audit_prompt(toolbox, item, papers, PROVED_CHALLENGE)
 163 |     log = None
 164 |     if log_folder is not None:
 165 |         stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
 166 |         log = RunLog(log_folder / f"{item.name}-{stamp}{LOG_SUFFIX}")
 167 |     return run_audit(client, toolbox, prompt, item.name, papers, log,
 168 |                      {"title": f"Statement audit of {item.name}", "copy": None})
```

## F3/F4/F5 — claim note, probe display, definition reader, paper IDs

`src/hekswerk_scry/ai/statement_tools.py`

```text
  80 |     def __post_init__(self) -> None:
  81 |         if not self.claim_preamble:
  82 |             self.claim_preamble = f"import {self.solution_module}"
  83 |             self.claim_note = (f"The proved result is imported from `{self.solution_module}`, "
  84 |                                "so you can use its theorems by name.")
  85 |         if self.claims_folder is None:
  86 |             self.claims_folder = self.workspace.root / ".scry-runs" / "claims"
  87 | 
  88 |     def definitions(self) -> list[dict[str, Any]]:
  89 |         theorem = {"theorem": {"type": "string", "description": "The theorem's full name."}}
  90 |         return [
  91 |             tool("read_statement", "What a theorem states, as Lean reads it: hypotheses, "
  92 |                  "conclusion, the project's own definitions it relies on, and Lean's probes "
  93 |                  "for contradictory or unneeded hypotheses.", theorem, ["theorem"]),
  94 |             tool("read_definition", "One of the project's definitions in full: its statement, "
  95 |                  "body, and source lines.",
  96 |                  {"name": {"type": "string", "description": "Full or last part of the name."}},
  97 |                  ["name"]),
  98 |             tool("read_lean_lines", "Lines of the Lean statement file (numbered from 1).",
  99 |                  {"first_line": {"type": "integer"}, "last_line": {"type": "integer"}},
 100 |                  ["first_line", "last_line"]),
 101 |             tool("list_paper_files", "The paper's LaTeX files, with their line counts.", {}, []),
 102 |             tool("search_paper", "Find lines of the paper's LaTeX containing a phrase (case "
 103 |                  "ignored). Returns file:line for each match.",
 104 |                  {"phrase": {"type": "string"}}, ["phrase"]),
 105 |             tool("read_paper", "Lines of one LaTeX file of the paper (numbered from 1).",
 106 |                  {"file": {"type": "string", "description": "As listed by list_paper_files."},
 107 |                   "first_line": {"type": "integer"}, "last_line": {"type": "integer"}},
```

```text
 155 |         name = str(arguments["theorem"])
 156 |         report = self.reports.get(name)
 157 |         if report is None:
 158 |             available = ", ".join(self.reports)
 159 |             raise ValueError(f"No statement read for '{name}'. Available: {available}.")
 160 |         lines = [f"Statement: {report.statement}", "Hypotheses and variables:"]
 161 |         lines += [f"- {b.name} : {b.type}  ({'hypothesis' if b.is_prop else b.binder})"
 162 |                   for b in report.binders] or ["- (none)"]
 163 |         lines += [f"Conclusion: {report.conclusion}",
 164 |                   f"Project definitions it relies on ({len(report.definitions)}):"]
 165 |         lines += [f"- [depth {d.depth}] {d.name} ({d.kind})" for d in report.definitions]
 166 |         lines += [f"Probe {p.kind}: {p.headline}" for p in report.probes]
 167 |         if report.proof_left_open:
 168 |             lines.append(self.proof_note)
 169 |         return Outcome(f"Lean's reading of the statement of {name.split('.')[-1]}",
 170 |                        "\n".join(lines), CheckKind.LEAN, report.receipt.receipt_id)
 171 | 
 172 |     def _read_definition(self, arguments: dict[str, Any]) -> Outcome:
 173 |         wanted = str(arguments["name"])
 174 |         for report in self.reports.values():
 175 |             for d in report.definitions:
 176 |                 if d.name == wanted or d.name.endswith("." + wanted):
 177 |                     where = (f"{d.module or self.workspace.relative(self.statement_file)}"
 178 |                              + (f", lines {d.start_line}-{d.end_line}" if d.start_line else ""))
 179 |                     body = f"\nBody: {d.value}" if d.value else ""
 180 |                     return Outcome(f"definition {d.name.split('.')[-1]}",
 181 |                                    f"{d.name} ({d.kind}; {where})\nType: {d.type}{body}",
 182 |                                    CheckKind.LEAN, report.receipt.receipt_id)
 183 |         raise ValueError(f"'{wanted}' isn't one of the project definitions the statement uses.")
```

```text
 193 |     def _list_paper_files(self, _: dict[str, Any]) -> Outcome:
 194 |         rows = [f"{self.label(p)} ({len(p.read_text(encoding='utf-8').splitlines())} lines)"
 195 |                 for p in self.paper_files]
 196 |         return Outcome("list of paper files", "\n".join(rows))
 197 | 
 198 |     def label(self, path: Path) -> str:
 199 |         """A short, stable name for a paper file: its path inside the paper's build folder."""
 200 |         for parent in path.parents:
 201 |             if parent.name == "build":
 202 |                 return path.relative_to(parent).as_posix()
 203 |         return path.name
 204 | 
 205 |     def _search_paper(self, arguments: dict[str, Any]) -> Outcome:
 206 |         phrase = str(arguments["phrase"]).strip().lower()
 207 |         if len(phrase) < 3:
 208 |             raise ValueError("Search for at least three characters.")
 209 |         hits: list[str] = []
 210 |         for path in self.paper_files:
 211 |             for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
 212 |                 if phrase in line.lower():
 213 |                     hits.append(f"{self.label(path)}:{n}: {line.strip()[:200]}")
 214 |         shown = hits[:40]
 215 |         more = f"\n(and {len(hits) - 40} more)" if len(hits) > 40 else ""
 216 |         return Outcome(f"paper search for '{phrase}'",
 217 |                        "\n".join(shown) + more if shown else "No matches.")
 218 | 
 219 |     def _read_paper(self, arguments: dict[str, Any]) -> Outcome:
 220 |         name = str(arguments["file"])
 221 |         path = next((p for p in self.paper_files if self.label(p) == name), None)
 222 |         if path is None:
 223 |             raise ValueError(f"No paper file '{name}'. Use list_paper_files.")
 224 |         lines = path.read_text(encoding="utf-8").splitlines()
 225 |         first, last = _span(arguments, len(lines))
 226 |         text = "\n".join(f"{n:4d} | {lines[n - 1]}" for n in range(first, last + 1))
 227 |         return Outcome(f"paper {name} lines {first}-{last}", text)
```

## F5 — Lean probe acceptance and axiom collection

`lean-exporters/v4.34.1/ScryExport/Statement.lean`

```text
 114 | def tryTactic (goal : MVarId) (text : String) : TermElabM (Option Expr) := do
 115 |   let env ← getEnv
 116 |   let .ok stx := Parser.runParserCategory env `tactic text | return none
 117 |   let saved ← saveState
 118 |   try
 119 |     let remaining ←
 120 |       withTheReader Core.Context (fun ctx => { ctx with maxHeartbeats := probeHeartbeats * 1000 }) <|
 121 |         withCurrHeartbeats <| Term.withoutErrToSorry <| Tactic.run goal (Tactic.evalTactic stx)
 122 |     let proof ← instantiateMVars (mkMVar goal)
 123 |     if remaining.isEmpty && !proof.hasSorry && !proof.hasExprMVar then
 124 |       return some proof
 125 |     saved.restore
 126 |     return none
 127 |   catch _ =>
 128 |     saved.restore
 129 |     return none
 130 | 
 131 | /-- Ask the kernel to accept `value : type` as a new theorem; report whether it did and
 132 | which axioms the result relies on. -/
 133 | def kernelAccepts (name : Name) (levels : List Name) (type value : Expr) :
 134 |     TermElabM (Option (Array Name)) := do
 135 |   let saved ← saveState
 136 |   try
 137 |     addDecl <| .thmDecl { name, levelParams := levels, type, value }
 138 |     let axioms ← collectAxioms name
 139 |     saved.restore
 140 |     return some axioms
 141 |   catch _ =>
 142 |     saved.restore
 143 |     return none
 144 | 
 145 | def probeResult (found : Option (String × Array Name)) (none_msg : String) : Json :=
 146 |   match found with
 147 |   | some (tactic, axioms) => Json.mkObj [
 148 |       ("found", true), ("tactic", tactic),
 149 |       ("axioms", toJson (axioms.map toString))]
 150 |   | none => Json.mkObj [("found", false), ("note", none_msg)]
 151 | 
 152 | def notApplicable (why : String) : Json :=
 153 |   Json.mkObj [("found", false), ("not_applicable", true), ("note", why)]
 154 | 
 155 | def hasHypotheses (info : ConstantInfo) : MetaM Bool :=
 156 |   forallTelescope info.type fun xs _ => xs.anyM fun x => do Meta.isProp (← x.fvarId!.getType)
 157 | 
 158 | /-- Vacuity: can the tactics derive `False` from all the hypotheses? -/
```

## F5 — Python probe labels and parsing

`src/hekswerk_scry/lean/statement.py`

```text
  81 |     def headline(self) -> str:
  82 |         if self.kind == "vacuity":
  83 |             if self.found:
  84 |                 return (f"Red flag: Lean derived False from the hypotheses (with `{self.tactic}`). "
  85 |                         "They contradict each other, so the theorem says nothing.")
  86 |             return self.note
  87 |         if self.found:
  88 |             return (f"Red flag: Lean proved the conclusion without the hypotheses (with "
  89 |                     f"`{self.tactic}`). They aren't needed, or the conclusion is weaker than it "
  90 |                     "looks.")
```

```text
 243 |         end_line=int(end["line"]) if end else None,
 244 |     )
 245 | 
 246 | 
 247 | def _probes(raw: Any) -> tuple[ProbeOutcome, ...]:
 248 |     if not isinstance(raw, dict):
 249 |         return ()
 250 |     out: list[ProbeOutcome] = []
 251 |     for kind in ("vacuity", "triviality"):
 252 |         probe = raw.get(kind)
 253 |         if not isinstance(probe, dict):
 254 |             continue
 255 |         out.append(ProbeOutcome(
 256 |             kind=kind, found=bool(probe.get("found")),
 257 |             applicable=not probe.get("not_applicable", False),
 258 |             tactic=probe.get("tactic"), axioms=tuple(probe.get("axioms", ())),
 259 |             note=str(probe.get("note", "")),
 260 |         ))
 261 |     return tuple(out)
```

## F6/F7 — benchmark scoring and reuse

`src/hekswerk_scry/ai/benchmark.py`

```text
 235 | def _overlaps(row: VerdictRow, lines: tuple[int, int]) -> bool:
 236 |     return row.lean_lines is not None and (
 237 |         row.lean_lines[0] <= lines[1] and lines[0] <= row.lean_lines[1])
 238 | 
 239 | 
 240 | def score_plant(rows: list[VerdictRow], planted_lines: tuple[int, int]) -> str:
 241 |     if any(r.verdict != MATCHES and _overlaps(r, planted_lines) for r in rows):
 242 |         return CAUGHT
 243 |     if any(r.verdict == MATCHES and _overlaps(r, planted_lines) for r in rows):
 244 |         return DANGEROUS_MISS
 245 |     return MISSED
 246 | 
 247 | 
 248 | def control_flagged(control_rows: list[VerdictRow], original_lines: tuple[int, int]) -> bool:
 249 |     """Whether the control audit already flagged the lines the plant replaced."""
 250 |     return any(r.verdict != MATCHES and _overlaps(r, original_lines) for r in control_rows)
```

```text
 314 | @dataclass(frozen=True)
 315 | class EarlierResult:
 316 |     copy_sha256: str
 317 |     rows: list[VerdictRow]
 318 |     cost_usd: float
 319 |     hit_round_limit: bool
 320 | 
 321 | 
 322 | def earlier_results(out: Path) -> dict[tuple[str, str], EarlierResult]:
 323 |     """Audits an earlier run saved in `out`, by (challenge, copy). Refuses a results file it
 324 |     can't read completely, rather than guessing at what it meant."""
 325 |     path = out / RESULTS_FILE
 326 |     if not path.is_file():
 327 |         return {}
 328 |     data = json.loads(path.read_text(encoding="utf-8"))
 329 |     found: dict[tuple[str, str], EarlierResult] = {}
 330 |     try:
 331 |         for challenge, entries in data.items():
 332 |             for entry in entries:
 333 |                 rows = [VerdictRow(
 334 |                     item=str(r["item"]), paper_says=str(r["paper_says"]),
 335 |                     lean_says=str(r["lean_says"]), verdict=str(r["verdict"]),
 336 |                     affects_main_result=bool(r["affects_main_result"]),
 337 |                     lean_lines=_saved_lines(r["lean_lines"]),
 338 |                     evidence=tuple(r["evidence"]),
 339 |                 ) for r in entry["rows"]]
 340 |                 if any(r.verdict not in VERDICTS for r in rows):
 341 |                     raise TypeError("a row has an unknown verdict")
 342 |                 found[(challenge, str(entry["variant"]))] = EarlierResult(
 343 |                     str(entry["copy_sha256"]), rows, float(entry["cost_usd"]),
 344 |                     bool(entry["hit_round_limit"]))
 345 |     except (KeyError, TypeError, ValueError, AttributeError) as exc:
 346 |         raise BenchmarkError(f"{path} isn't a complete results file ({exc!r}). Move it away "
 347 |                              "or choose another --out folder.") from exc
 348 |     return found
 349 | 
 350 | 
 351 | def reusable(before: EarlierResult, copy_sha256: str) -> bool:
 352 |     """An earlier audit stands only for exactly the copy it audited."""
 353 |     return before.copy_sha256 == copy_sha256
```

```text
 365 | def run_benchmark(client: OpenRouterClient, names: list[str], out: Path,
 366 |                   plants: dict[str, list[Plant]] | None = None,
 367 |                   budget_usd: float = DEFAULT_BUDGET_USD) -> Path:
 368 |     """Audit every copy, reusing any audit an earlier run in `out` saved for a byte-identical
 369 |     copy. `budget_usd` limits what this run spends; reused audits cost nothing again."""
 370 |     plants = plants if plants is not None else load_plants()
 371 |     prepared = prepare(names, plants)
 372 |     out.mkdir(parents=True, exist_ok=True)
 373 |     earlier = earlier_results(out)
 374 |     by_challenge: dict[str, list[VariantResult]] = {}
 375 |     spent: list[float] = []
 376 |     skipped: list[str] = []
 377 |     stopped: str | None = None
 378 |     for variant, paper_files, papers in prepared:
 379 |         if stopped is not None:
 380 |             skipped.append(f"{variant.item.name} ({variant.name})")
 381 |             continue
 382 |         sha = file_sha256(variant.statement_file)
 383 |         before = earlier.get((variant.item.name, variant.name))
 384 |         if before is not None and reusable(before, sha):
 385 |             result = VariantResult(variant, before.rows, before.cost_usd,
 386 |                                    before.hit_round_limit, sha, reused=True)
```

```text
 451 | def render_summary(by_challenge: dict[str, list[VariantResult]]) -> str:
 452 |     plants = [r for results in by_challenge.values() for r in results if r.score is not None]
 453 |     counts = {s: sum(r.score == s for r in plants) for s in (CAUGHT, DANGEROUS_MISS, MISSED)}
 454 |     cost = sum(r.cost_usd for results in by_challenge.values() for r in results)
 455 |     reused = sum(r.reused for results in by_challenge.values() for r in results)
 456 |     lines = [
 457 |         "# Statement audit benchmark", "",
 458 |         f"{len(plants)} planted differences in {len(by_challenge)} statements: "
 459 |         f"{counts[CAUGHT]} caught, {counts[DANGEROUS_MISS]} dangerous misses (a row said "
 460 |         f"\"matches\" over the planted lines), {counts[MISSED]} missed. Total cost "
 461 |         f"${cost:.2f}" + (f" ({reused} audits reused from an earlier run)" if reused else "")
 462 |         + ".", "",
 463 |         "Scored mechanically from the rows each audit recorded. The audits are the AI "
 464 |         "helper's reading; the scores only say whether a row pointed at the planted lines "
 465 |         "with a verdict other than \"matches\".", "",
 466 |         "| Statement | Plant | What was planted | Result | Row that flagged it |",
 467 |         "| --- | --- | --- | --- | --- |",
 468 |     ]
 469 |     for result in plants:
 470 |         assert result.variant.plant is not None
 471 |         flagged = "; ".join(f"{r.item} ({r.verdict})" for r in result.catching_rows) or "-"
 472 |         note = " (control flagged these lines too: check by hand)" if result.also_in_control else ""
 473 |         lines.append(f"| {result.variant.item.name} | {result.variant.plant.plant_id} | "
 474 |                      f"{result.variant.plant.what} | {result.score}{note} | {flagged} |")
 475 |     lines += ["", "## What the unchanged copies' audits flagged", "",
 476 |               "Differences the helper reported in the real statements, to compare with "
 477 |               "OpenAI's scope notes (which the helper never saw).", ""]
 478 |     for name, results in by_challenge.items():
 479 |         control = next((r for r in results if r.variant.plant is None), None)
 480 |         if control is None:
 481 |             continue
 482 |         scope = openai_math.scope_note(control.variant.item)
 483 |         lines.append(f"### {name} (scope note {scope.name if scope else 'none'})")
 484 |         differences = [r for r in control.rows if r.verdict != MATCHES]
 485 |         lines += [f"- {r.item}: {r.verdict}"
 486 |                   + (" (affects the main result)" if r.affects_main_result else "")
 487 |                   for r in differences] or ["- nothing flagged"]
 488 |         lines.append("")
 489 |     return "\n".join(lines)
```

## F8 — outline index cache and source-change list

`src/hekswerk_scry/web/server.py`

```text
 251 |     def _outline(self, path: Path) -> tuple[Outline, dict[str, Any]]:
 252 |         stat = path.stat()
 253 |         version = (stat.st_size, stat.st_mtime_ns)
 254 |         with self._outlines_lock:
 255 |             cached = self._outlines.get(path)
 256 |             if cached is not None and cached[0] == version:
 257 |                 return cached[1], cached[2]
 258 |         data = json.loads(path.read_text(encoding="utf-8"))
 259 |         outline = outline_from_dict(data, source=path.name)
 260 |         index = _outline_index(outline)
 261 |         with self._outlines_lock:
 262 |             self._outlines[path] = (version, outline, index)
 263 |         return outline, index
 264 | 
 265 | 
 266 | 
 267 | def _outline_index(outline: Outline) -> dict[str, Any]:
 268 |     """Everything the outline view needs up front. To keep this small enough for a phone,
 269 |     parts and files are referred to by their position in `ids` and `files`, a part's name is
 270 |     left out when it is the same as its ID, and "used by" is left for the page to work out.
 271 |     One part's text is fetched when it is chosen."""
 272 |     ids = list(outline.parts)
 273 |     number = {part_id: n for n, part_id in enumerate(ids)}
 274 |     files = sorted({p.file for p in outline.parts.values() if p.file is not None})
 275 |     file_number = {file: n for n, file in enumerate(files)}
 276 |     rests_on = outline.rests_on()
 277 |     parts = outline.parts
 278 |     return {
 279 |         "result": number[outline.result],
 280 |         "lean_version": outline.lean_version,
 281 |         "axioms": list(outline.axioms),
 282 |         "changed_files": changed_files(outline),
 283 |         "ids": ids,
 284 |         "files": files,
 285 |         "parts": [{
 286 |             "name": None if p.name == p.part_id else p.name,
 287 |             "kind": p.kind, "private": p.private,
 288 |             "file": None if p.file is None else file_number[p.file],
 289 |             "start_line": p.start_line, "lines": p.lines,
 290 |             "statement_uses": [number[u] for u in p.statement_uses],
 291 |             "body_uses": [number[u] for u in p.body_uses],
 292 |             "rests_on": len(rests_on[p.part_id]),
 293 |             "rests_on_lines": sum(parts[r].lines for r in rests_on[p.part_id]),
 294 |             "unused": [vars(h) for h in p.unused_hypotheses],
 295 |         } for p in parts.values()],
 296 |         "claim": [number[c] for c in outline.claim()],
 297 |         "meaning_kinds": sorted(MEANING_KINDS),
```

## Definition coverage limits

`lean-exporters/v4.34.1/ScryExport/Statement.lean`

```text
  65 | def clip (s : String) (limit : Nat := 3000) : String :=
  66 |   if s.length ≤ limit then s else (s.take limit).toString ++ " …(cut)"
  67 | 
  68 | /-- What a constant contributes to the meaning of a statement: its type, and for
  69 | definitions its body; for inductive types, the types of its constructors. -/
  70 | def meaningExprs (info : ConstantInfo) (env : Environment) : List Expr :=
  71 |   match info with
  72 |   | .defnInfo d => [d.type, d.value]
  73 |   | .opaqueInfo d => [d.type]
  74 |   | .inductInfo d => d.type :: d.ctors.filterMap fun c => (env.find? c).map (·.type)
  75 |   | other => [other.type]
  76 | 
  77 | /-- Project constants reachable from `roots` through types and definition bodies,
  78 | in the order found (breadth first), at most `limit` of them. -/
  79 | def projectClosure (env : Environment) (roots : Array Name) (limit : Nat := 80) :
  80 |     Array (Name × Nat) := Id.run do
  81 |   let mut seen : NameSet := {}
  82 |   let mut out : Array (Name × Nat) := #[]
  83 |   let mut queue : Array (Name × Nat) := roots.map (·, 1)
  84 |   let mut i := 0
  85 |   while i < queue.size && out.size < limit do
  86 |     let (n, depth) := queue[i]!
  87 |     i := i + 1
  88 |     if seen.contains n || !isProjectConstant env n then continue
  89 |     seen := seen.insert n
  90 |     let some info := env.find? n | continue
  91 |     out := out.push (n, depth)
  92 |     for e in meaningExprs info env do
  93 |       for c in e.getUsedConstants do
  94 |         if !seen.contains c then queue := queue.push (c, depth + 1)
  95 |   return out
```

## Markdown multiline-comment handling

`src/hekswerk_scry/web/static/markdown.js`

```text
  10 | export function renderMarkdown(text, onCite) {
  11 |   const root = h('div', { class: 'markdown' })
  12 |   const lines = text.replace(/\r\n/g, '\n').split('\n')
  13 |   let i = 0
  14 |   while (i < lines.length) {
  15 |     const line = lines[i]
  16 |     if (line.startsWith('```')) {
  17 |       const code = []
  18 |       i += 1
  19 |       while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++])
  20 |       i += 1
  21 |       root.append(h('pre', {}, h('code', {}, code.join('\n'))))
  22 |     } else if (/^#{1,6}\s/.test(line)) {
  23 |       const level = Math.min(6, line.match(/^#+/)[0].length + 1)
  24 |       root.append(h(`h${level}`, {}, inline(line.replace(/^#+\s*/, ''), onCite)))
  25 |       i += 1
  26 |     } else if (/^\s*>/.test(line)) {
  27 |       const quoted = []
  28 |       while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*>\s?/, ''))
  29 |       root.append(h('blockquote', {}, renderMarkdown(quoted.join('\n'), onCite)))
  30 |     } else if (/^\s*\|.*\|\s*$/.test(line)) {
  31 |       const rows = []
  32 |       while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++])
  33 |       root.append(table(rows, onCite))
  34 |     } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
  35 |       const ordered = /^\s*\d+\./.test(line)
  36 |       const list = h(ordered ? 'ol' : 'ul')
  37 |       while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
  38 |         let item = lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, '')
  39 |         while (i < lines.length && /^\s{2,}\S/.test(lines[i]) &&
  40 |                !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) item += ' ' + lines[i++].trim()
  41 |         list.append(h('li', {}, inline(item, onCite)))
  42 |       }
  43 |       root.append(list)
  44 |     } else if (line.trim() === '' || line.trim().startsWith('<!--')) {
  45 |       i += 1
  46 |     } else {
  47 |       const para = [line]
  48 |       i += 1
  49 |       while (i < lines.length && lines[i].trim() !== '' && !/^(#|```|\s*\||\s*>|\s*([-*]|\d+\.)\s)/.test(lines[i])) {
  50 |         para.push(lines[i++])
  51 |       }
  52 |       root.append(h('p', {}, inline(para.join(' '), onCite)))
  53 |     }
  54 |   }
  55 |   return root
```

## Outline meaning versus proof dependencies

`src/hekswerk_scry/models/outline.py`

```text
   1 | """An outline: a result, and every theorem and definition in its project that it rests on.
   2 | 
   3 | A proof map follows one proof tactic by tactic. That is the level Lean is persuaded at, not
   4 | the level a proof is understood at: the ideas usually live in how the theorems of a project
   5 | fit together, and in what its definitions say. An outline is that level. Each *part* is one
   6 | declaration a person wrote (a theorem, definition, structure, ...), with the parts its
   7 | statement mentions and the parts its body uses (a theorem's proof, a definition's value).
   8 | 
   9 | Outlines come from Lean's own record of the compiled project (`lean/outline.py`), never
  10 | from reading Lean text. The text of each part is kept only to show to people.
  11 | """
  12 | 
  13 | from collections.abc import Callable, Iterable, Mapping
  14 | from dataclasses import dataclass, field
  15 | 
  16 | # Kinds whose body is part of what they mean. A theorem's proof is not part of what it
  17 | # means: to read a statement you need the definitions it mentions, not the proofs of the
  18 | # theorems it mentions.
  19 | MEANING_KINDS = frozenset({"definition", "instance", "structure", "class", "inductive type",
  20 |                            "opaque definition", "axiom"})
  21 | 
  22 | 
  23 | @dataclass(frozen=True)
  24 | class UnusedHypothesis:
  25 |     """A hypothesis a theorem's statement gives its proof, which the proof never uses."""
  26 | 
  27 |     name: str | None  # as written, or None when Lean made the name up
  28 |     statement: str
  29 | 
  30 | 
  31 | @dataclass(frozen=True)
  32 | class OutlinePart:
  33 |     part_id: str  # Lean's full name for it, which is unique
  34 |     name: str  # the name as written (a private name without the prefix Lean adds)
  35 |     kind: str  # "theorem", "definition", "structure", ...
  36 |     private: bool
  37 |     module: str | None  # None for the file the outline was made from
  38 |     file: str | None  # relative to the project
  39 |     start_line: int | None
  40 |     end_line: int | None
  41 |     doc: str | None  # the author's doc string
  42 |     statement: str  # Lean's printing of what it states (its type)
  43 |     source: str | None  # the lines it is written on
  44 |     statement_uses: tuple[str, ...]
  45 |     body_uses: tuple[str, ...]
  46 |     unused_hypotheses: tuple[UnusedHypothesis, ...] = ()
  47 | 
  48 |     @property
  49 |     def uses(self) -> tuple[str, ...]:
  50 |         return tuple(dict.fromkeys(self.statement_uses + self.body_uses))
  51 | 
  52 |     @property
  53 |     def lines(self) -> int:
  54 |         if self.start_line is None or self.end_line is None:
  55 |             return 0
  56 |         return self.end_line - self.start_line + 1
  57 | 
  58 | 
  59 | class OutlineError(ValueError):
  60 |     """An outline that doesn't hang together. The message says what is wrong."""
  61 | 
  62 | 
  63 | @dataclass(frozen=True)
  64 | class Outline:
  65 |     result: str  # the part_id of the theorem outlined
  66 |     project: str  # the Lean project's folder
  67 |     lean_version: str
  68 |     file_sha256: dict[str, str]  # each file a part is written in, as it was
  69 |     axioms: tuple[str, ...]  # what Lean reported the result relies on
  70 |     parts: dict[str, OutlinePart] = field(default_factory=dict)  # the result first
  71 | 
  72 |     def __post_init__(self) -> None:
  73 |         if next(iter(self.parts), None) != self.result:
  74 |             raise OutlineError(f"An outline's first part must be its result, '{self.result}'.")
  75 |         for part_id, part in self.parts.items():
  76 |             if part.part_id != part_id:
  77 |                 raise OutlineError(f"Part '{part_id}' is filed under the wrong name.")
  78 |             for used in part.uses:
  79 |                 if used not in self.parts:
  80 |                     raise OutlineError(f"Part '{part_id}' uses '{used}', which isn't in the "
  81 |                                        "outline. Make the outline again with `scry lean-outline`.")
  82 |             if part.file is not None and part.file not in self.file_sha256:
  83 |                 raise OutlineError(f"Part '{part_id}' is written in '{part.file}', which has "
  84 |                                    "no fingerprint.")
  85 | 
  86 |     def used_by(self) -> dict[str, tuple[str, ...]]:
  87 |         """For each part, the parts that use it."""
  88 |         users: dict[str, list[str]] = {part_id: [] for part_id in self.parts}
  89 |         for part_id, part in self.parts.items():
  90 |             for used in part.uses:
  91 |                 users[used].append(part_id)
  92 |         return {part_id: tuple(u) for part_id, u in users.items()}
  93 | 
  94 |     def claim(self) -> tuple[str, ...]:
  95 |         """The parts a person needs to read the result's statement: the parts it mentions,
  96 |         and theirs in turn, following a definition's body (what it means) but not a
  97 |         theorem's proof. In the order found, nearest first; the result is not included."""
  98 |         return tuple(_reach(
  99 |             [self.result],
 100 |             lambda p: self.parts[p].statement_uses + (
 101 |                 self.parts[p].body_uses if self.parts[p].kind in MEANING_KINDS else ()),
 102 |         )[1:])
 103 | 
 104 |     def rests_on(self) -> dict[str, frozenset[str]]:
 105 |         """For each part, every other part it rests on, directly or not."""
 106 |         return _closures({p: part.uses for p, part in self.parts.items()})
 107 | 
 108 | 
 109 | def _reach(start: list[str], next_of: Callable[[str], Iterable[str]]) -> list[str]:
 110 |     seen = dict.fromkeys(start)
 111 |     queue = list(start)
 112 |     while queue:
 113 |         for nxt in next_of(queue.pop(0)):
 114 |             if nxt not in seen:
 115 |                 seen[nxt] = None
 116 |                 queue.append(nxt)
 117 |     return list(seen)
 118 | 
 119 | 
 120 | 
 121 | def _closures(edges: Mapping[str, Iterable[str]]) -> dict[str, frozenset[str]]:
 122 |     """Everything reachable from each node, not counting the node itself.
 123 | 
 124 |     Declarations can use each other in a loop (a `mutual` block), so this first groups
 125 |     nodes that reach each other (Tarjan's strongly connected components, without
 126 |     recursion), then combines the groups' reach in the order Tarjan finishes them, which
 127 |     puts every group after the groups it reaches."""
 128 |     graph = {n: list(dict.fromkeys(e)) for n, e in edges.items()}
 129 |     index: dict[str, int] = {}
 130 |     low: dict[str, int] = {}
 131 |     on_stack: set[str] = set()
 132 |     stack: list[str] = []
 133 |     group_of: dict[str, int] = {}
 134 |     groups: list[list[str]] = []
 135 |     for start in graph:
 136 |         if start in index:
 137 |             continue
 138 |         work = [(start, 0)]
 139 |         index[start] = low[start] = len(index)
 140 |         stack.append(start)
 141 |         on_stack.add(start)
 142 |         while work:
 143 |             node, i = work[-1]
 144 |             if i < len(graph[node]):
 145 |                 work[-1] = (node, i + 1)
 146 |                 nxt = graph[node][i]
 147 |                 if nxt not in index:
 148 |                     index[nxt] = low[nxt] = len(index)
 149 |                     stack.append(nxt)
 150 |                     on_stack.add(nxt)
 151 |                     work.append((nxt, 0))
 152 |                 elif nxt in on_stack:
 153 |                     low[node] = min(low[node], index[nxt])
 154 |                 continue
 155 |             work.pop()
 156 |             if work:
 157 |                 parent = work[-1][0]
 158 |                 low[parent] = min(low[parent], low[node])
 159 |             if low[node] == index[node]:
 160 |                 group: list[str] = []
 161 |                 while True:
 162 |                     member = stack.pop()
 163 |                     on_stack.discard(member)
 164 |                     group_of[member] = len(groups)
 165 |                     group.append(member)
 166 |                     if member == node:
 167 |                         break
 168 |                 groups.append(group)
 169 |     reach: list[frozenset[str]] = []
 170 |     for number, group in enumerate(groups):
 171 |         found: set[str] = set(group) if len(group) > 1 else set()
 172 |         for member in group:
 173 |             for nxt in graph[member]:
 174 |                 if group_of[nxt] != number:
 175 |                     found |= reach[group_of[nxt]] | {nxt}
 176 |         reach.append(frozenset(found))
 177 |     return {n: reach[group_of[n]] - {n} for n in graph}
```

## Truffet saved report

`docs/examples/truffet-statement-audit.md`

```text
   1 | <!-- The first live statement audit (2026-10-17), saved by `scry audit-statement TruffetCounterexample`.
   2 | Paper quotes and the scope note below come from OpenAI's mathematics repository
   3 | (https://github.com/openai/math), used under its Apache-2.0 license. -->
   4 | 
   5 | # Statement audit of TruffetCounterexample, next to OpenAI's scope note
   6 | 
   7 | ## Scry's audit (the AI helper's reading, except where it cites a Lean check)
   8 | 
   9 | 1. **The paper's claim** (source/sections/09-comparison.tex, lines 12–73 [E4]). The paper looks at the instance "min x₁ subject to max(x₁,x₂) ≥ 0, x₁ ≥ max(x₂+1, −2)" and argues: "The point (0,−1) is feasible… Thus the true minimum is exactly zero." After homogenizing to "max(x₁,x₂) ≥ h, x₁ ≥ max(x₂+1, h−2)", it says the dominating-variable set is exactly {x₂} and the "unique pair (1,2)" forces "x₂ = h. There is no tie-breaking choice in this step." Then "the second row requires x₁ ≥ h+1. The next eligible saturation consequently sets x₁ = h+1. The stopping test in Equation (39) fails before each of these two substitutions… the separate rule for an objective-independent switch to maximization does not apply. Normalizing to h=0 gives objective value 1, whereas the original minimum … is 0." It also claims: "The first substitution already removes every optimum." The scope is limited to Truffet's arXiv v4 rule [E4]; the introduction says the same [E5].
  10 | 
  11 | 2. **The formal statement.** The theorem has no hypotheses. It asserts a conjunction about fixed concrete objects [E1, E6]:
  12 |    - Encoding: coordinates 0, 1, 2 stand for x₁, x₂, h. Row 0 is max(x₁,x₂) ≥ h. Row 1 is x₁ ≥ max(x₂+1, h−2). The cost is x₁. Rows and variables are indexed from 0, so the paper's pair (1,2) is Lean's `(row 0, var 1)`.
  13 |    - The instance satisfies a cross-row non-domination condition (`crossRowRestriction`).
  14 |    - `initial → middle` is a `ForcedSingletonStep` on (row 0, x₂). `middle → finalState` is one on (row 1, x₁).
  15 |    - At `finalState` no variable remains and `stop` holds.
  16 |    - `output = (1,0,0)` and `better = (0,−1,0)` are both feasible for the original rows, and both have h = 0.
  17 |    - `output` is produced by back-substituting x₂ = h and then x₁ = h+1.
  18 |    - The original cost at `output` equals the final cost at `output`, and the original cost at `better` is strictly smaller than that.
  19 | 
  20 | 3. **Point by point**
  21 | 
  22 | | Item | Paper says | Lean says | Verdict |
  23 | |---|---|---|---|
  24 | | Instance and homogenization | max(x₁,x₂) ≥ h; x₁ ≥ max(x₂+1, h−2); objective x₁ [E4] | `initial` rows and cost encode exactly this, in max-plus over `WithBot ℝ` [E6, lines 93–97] | matches |
  25 | | Eq. (5b) cross-row condition | for both ordered row pairs, no domination by any finite additive constant [E4] | `crossRowRestriction`: for i≠r and every α there is a w with lhsᵢ(w) < α + rhsᵣ(w) [E6, lines 110–112] | matches the paper's prose. Whether it matches Truffet's Eq. (5b) cannot be checked here |
  26 | | Every variable has a lower or upper occurrence | required by Def. 4.2 / Eq. (34) [E4] | `bounded`, part of `ForcedSingletonStep` [E6] | matches |
  27 | | Search endpoints μ=0, λ=−4 and Eq. (23b) | claimed to hold [E4] | absent | not in the formalization |
  28 | | Lower/upper occurrence table, dominating set {x₂}, unique eligible pair | [E4] | `lower`, `upper`, `dominating`, `eligible`; the step requires eligible ⇔ (r,k)=(0,1) [E6, lines 39–51, 89]. My hand computation agrees with the paper's table | matches, within the formalizer's model of the rule |
  29 | | First substitution x₂ = h | [E4] | `lowerForm initial 0 1` = (⊥,⊥,0), i.e. x₂ = h; `advance` gives `middle`, whose row 1 is x₁ ≥ h+1 [E6] | matches |
  30 | | Stop test fails before each step; no switch; no failure | [E4] | `¬stop`, `¬switch`, `¬failure` are inside each `ForcedSingletonStep` [E6, line 88] | matches, within the model |
  31 | | Second substitution x₁ = h+1; final objective h+1 | [E4] | `finalState.cost` = (⊥,⊥,1); `stop finalState`; no variables remain [E1, E6] | matches |
  32 | | Output value 1 vs. a feasible point of value 0 | [E4] | `output` and `better` are feasible, with eval values 1 and 0 [E1]; I confirmed the values separately [E9] | matches |
  33 | | "True minimum is exactly zero" | every feasible point has x₁ ≥ 0 [E4] | the theorem only exhibits `better` with value 0 < 1 | Lean concludes less. I proved the lower bound separately [E7] |
  34 | | "First substitution already removes every optimum" | [E4] | not stated | Lean concludes less. I proved separately that x₁ ≥ 1 on `middle` when h = 0 [E10] |
  35 | | Fidelity to Truffet v4 itself | the paper cites specific equations (5b, 23b, 39, 47, 53a/b, Case 2.2.2) [E4] | the rule is the formalizer's own reconstruction: `ForcedSingletonStep`, `advance`, `cleanup`, `stop`, `switch` [E6] | unclear; cannot be checked against the source |
  36 | 
  37 | 4. **Definitions a person should read closely**
  38 |    - `lower` and `upper`: a strict comparison of the left-side and right-side coefficients of a column. These decide the dominating set.
  39 |    - `eligible`: restricts to dominating variables whenever one exists (Eq. 53b).
  40 |    - `lowerForm`, `substitute`, `cleanup`, `advance`: the saturation and substitution mechanics. `cleanup` replaces a row by a null row when it is trivially satisfied coefficient-wise.
  41 |    - `stop` (the h-coefficient test, Eq. 39) and `switch`.
  42 |    - `crossRowRestriction` (Eq. 5b).
  43 | 
  44 |    All of these are the formalizer's model of Truffet's procedure. The audited theorem is only as meaningful as the match between this model and the cited v4 text, which this audit cannot see.
  45 | 
  46 | 5. **Lean checks I ran**
  47 |    - [E7] accepted: every w feasible for `initial` with h = 0 has x₁ ≥ 0. This supports "the true minimum is exactly zero".
  48 |    - [E8] rejected: a combined attempt failed because of my tactics, not because the claim is false. I split it into the next two checks.
  49 |    - [E9] accepted: the original cost at `better` is 0 and the final cost at `output` is 1.
  50 |    - [E10] accepted: every w feasible for `middle` with h = 0 has x₁ ≥ 1. This supports "the first substitution already removes every optimum".
  51 | 
  52 | 6. **Overall.** The formal statement is proven. It faithfully encodes the paper's concrete instance, the forced two-step run, and the output of value 1 against a feasible point of value 0. My side checks [E7, E10] add the paper's "minimum is 0" and "first substitution removes every optimum" claims, which the theorem itself does not state. Two things are outside the formal result: the search-endpoint conditions (μ=0, λ=−4, Eq. 23b), and whether `ForcedSingletonStep` and the related definitions really match the rule printed in Truffet's arXiv v4.
  53 | 
  54 | ## Evidence
  55 | 
  56 | - E1: Lean's reading of the statement of finite_execution_not_optimal [Lean (checks the math itself)]
  57 | - E2: list of paper files [lookup (no check)]
  58 | - E3: paper search for 'truffet' [lookup (no check)]
  59 | - E4: paper source/sections/09-comparison.tex lines 1-82 [lookup (no check)]
  60 | - E5: paper source/sections/01-introduction.tex lines 175-200 [lookup (no check)]
  61 | - E6: Lean statement lines 1-134 [lookup (no check)]
  62 | - E7: Lean check of claim 1: accepted [Lean (checks the math itself)]
  63 | - E8: Lean check of claim 2: not accepted [Lean (checks the math itself)]
  64 | - E9: Lean check of claim 3: accepted [Lean (checks the math itself)]
  65 | - E10: Lean check of claim 4: accepted [Lean (checks the math itself)]
  66 | 
  67 | (Cost of this audit: $0.5050.)
  68 | 
  69 | ## OpenAI's scope note (104.md), not seen by the helper
  70 | 
  71 | # Quasipolynomial algorithms for mean-payoff, stochastic and parity games
  72 | 
  73 | The following describes the scope of the Lean formalization related to the following accompanying paper(s):
  74 | 
  75 | - [Deterministic quasipolynomial-time mean-payoff games](../../preprints/Deterministic-quasipolynomial-time-mean-payoff-games-September-25-2026/paper.pdf)
  76 | - [Randomized quasipolynomial-time mean-payoff games](../../preprints/Randomized-quasipolynomial-time-mean-payoff-games-September-25-2026/paper.pdf)
  77 | 
  78 | ## Scope
  79 | 
  80 | The formalization checks that a specified two-step execution of Truffet's elimination procedure terminates with a feasible but nonoptimal output. It is a finite counterexample to that proposed optimization step.
  81 | 
  82 | The formalized result gives one randomized algorithm for the complete zero-threshold winning set of every finite mean-payoff game with signed binary weights. It succeeds with probability at least $7/8$ and runs in quasipolynomial bit time on every random tape. Self-loops, parallel edges, and history-dependent strategies are allowed, and winning means a nonnegative liminf average payoff.
  83 | 
  84 | ## Comparator links
  85 | 
  86 | | Result | Comparator statement |
  87 | | --- | --- |
  88 | | Finite counterexample to Truffet's optimization procedure | [TruffetCounterexample.lean](../ComparatorChallenges/TruffetCounterexample.lean) |
  89 | | Randomized quasipolynomial mean-payoff algorithm | [RandomizedMeanPayoff.lean](../ComparatorChallenges/RandomizedMeanPayoff.lean) |
```

## Saved benchmark report

`docs/examples/statement-benchmark-1.md`

```text
   1 | <!-- First run of `scry statement-benchmark` (2026-10-18), commits 7d9c433..df69967, model anthropic/claude-opus-5.5 at effort high. Statements and paper material come from OpenAI's mathematics repository (https://github.com/openai/math), used under its Apache-2.0 license. -->
   2 | 
   3 | # Statement audit benchmark
   4 | 
   5 | 6 planted differences in 3 statements: 6 caught, 0 dangerous misses (a row said "matches" over the planted lines), 0 missed. Total cost $8.77 (6 audits reused from an earlier run).
   6 | 
   7 | Scored mechanically from the rows each audit recorded. The audits are the AI helper's reading; the scores only say whether a row pointed at the planted lines with a verdict other than "matches".
   8 | 
   9 | | Statement | Plant | What was planted | Result | Row that flagged it |
  10 | | --- | --- | --- | --- | --- |
  11 | | FiniteCongruenceGraph | one-direction | Only one direction of the paper's 'if and only if': a graph witness gives a representation, but not the converse. | caught | Direction of the conclusion (iff vs. one direction) (Lean concludes less) |
  12 | | FiniteCongruenceGraph | placement-reversed | Admissible placements must raise edge colours where the paper's lower them: d(p,q) ≤ d(f(p),f(q)) instead of d(f(p),f(q)) ≤ d(p,q). | caught | Admissible placement (direction of the inequality) (differs) |
  13 | | FourRowPermanent | exponent-two-allowed | Allows p₀ = 2, where the inequality was already known; the paper's point is an exponent strictly below two. | caught | Range of the exponent p₀ (Lean concludes less) |
  14 | | FourRowPermanent | unnormalized-norm | Row norms drop the paper's 1/4 normalization, which enlarges the right-hand side and weakens the inequality. The file's own comment still says the norms are normalized. | caught | Definition of the p-norm (normalization) (differs) |
  15 | | PlaneColoring | line-not-plane | Colours the real line, not the plane. | caught | Ambient space ("the Euclidean plane") (differs) |
  16 | | PlaneColoring | bounded-region | Only points within distance 100 of the origin need different colours at distance one. | caught | Domain of the coloring constraint (Lean covers a special case) |
  17 | 
  18 | ## What the unchanged copies' audits flagged
  19 | 
  20 | Differences the helper reported in the real statements, to compare with OpenAI's scope notes (which the helper never saw).
  21 | 
  22 | ### FiniteCongruenceGraph (scope note 206.md)
  23 | - Remark on finite checkability for fixed |A|: not in the formalization
  24 | 
  25 | ### FourRowPermanent (scope note 238.md)
  26 | - nothing flagged
  27 | 
  28 | ### PlaneColoring (scope note 158.md)
  29 | - Main claim: no proper five-coloring (χ(R^2) ≥ 6): Lean concludes less (affects the main result)
  30 | - Transfer theorem and weak measurable five-coloring obstruction (Thms 1.3, 1.4): not in the formalization (affects the main result)
```
