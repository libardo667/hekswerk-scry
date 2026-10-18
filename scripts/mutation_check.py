"""Break the code on purpose and confirm the tests notice.

Each mutation below is a small, plausible mistake in code that tests are meant to guard.
The script applies one mutation at a time, runs the unit tests, and restores the file.
A mutation that leaves the tests green is a gap in the tests. Run with `make
mutation-check`; it exits non-zero if any mutation is missed.

Add a mutation here whenever you add a test that guards a specific piece of behaviour.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (file, original text, mutated text, what the mistake is)
MUTATIONS = [
    ("src/hekswerk_scry/checker/regions.py",
     "if users and all(user in group for user in users):",
     "if users and any(user in group for user in users):",
     "a fact's proof takes in steps that are also used elsewhere"),
    ("src/hekswerk_scry/checker/regions.py",
     "users = [child for child in children[candidate] if child in live]",
     "users = list(children[candidate])",
     "dead ends keep their inputs out of a fact's proof"),
    ("src/hekswerk_scry/lean/cards.py",
     '        new = "by\\n" + "\\n".join(pad + line if line.strip() else "" for line in lines)',
     '        new = "by\\n" + "\\n".join(line for line in lines)',
     "new tactics are not indented inside the proof"),
    ("src/hekswerk_scry/lean/cards.py",
     "    return line_start, min(line_end + 1, len(text))",
     "    return start, end",
     "removed code leaves empty lines behind"),
    ("src/hekswerk_scry/lean/cards.py",
     "        removed.add(introducer)",
     "        pass",
     "dead `have` lines are kept"),
    ("src/hekswerk_scry/lean/cards.py",
     "            if inside_cut or (span is None and step.lean_introduced_by in removed):",
     "            if span is None and step.lean_introduced_by in removed:",
     "dead code inside the cut is kept"),
    ("src/hekswerk_scry/lean/cards.py",
     "            if inside_cut or (span is None and step.lean_introduced_by in removed):",
     "            if inside_cut:",
     "unused lemmas of removed steps are kept"),
    ("src/hekswerk_scry/models/receipts.py",
     "        if checked_by is CheckKind.LEAN:",
     "        if False:",
     "a receipt can claim to come from Lean without a Lean run"),
    ("src/hekswerk_scry/lean/importer.py",
     "    if not report.passed:\n        first = next(",
     "    if False:\n        first = next(",
     "an import that lost part of Lean's record is accepted"),
    ("src/hekswerk_scry/ai/session.py",
     "            self.messages.append(reply.message)",
     "            self.messages.append({\"role\": \"assistant\", \"content\": reply.text})",
     "the model's messages are rewritten instead of kept exactly"),
    ("src/hekswerk_scry/ai/session.py",
     "            for evidence_id in group.split(\",\")",
     "            for evidence_id in group.split(\",\")[:1]",
     "only the first ID in a citation like [E4, E5] counts"),
    ("src/hekswerk_scry/ai/session.py",
     "            unknown_citations=[i for i in cited_ids if i not in by_id],",
     "            unknown_citations=[],",
     "citations to evidence that never existed go unflagged"),
    ("src/hekswerk_scry/ai/openrouter.py",
     '                "tool_choice": "auto",',
     '                "tool_choice": "required",',
     "the model is forced to call a tool"),
    ("src/hekswerk_scry/ai/tools.py",
     "        handler = self.handlers().get(name) if name in offered else None",
     "        handler = self.handlers().get(name)",
     "Lean tools run even when they were not offered"),
    ("src/hekswerk_scry/text_reports.py",
     "    if not turn.checks_run:",
     "    if False:",
     "an answer with no checks behind it is not flagged"),
    ("src/hekswerk_scry/lean/statement.py",
     '        "exporter_sha256": hashlib.sha256(workspace.exporter.read_bytes()).hexdigest(),',
     '        "exporter_sha256": "",',
     "a stored statement result is reused after the exporter is rebuilt"),
    ("src/hekswerk_scry/lean/statement.py",
     "        return tuple(probe for probe in self.probes if probe.found)",
     "        return tuple(probe for probe in self.probes if probe.applicable)",
     "a probe that found nothing is reported as a red flag"),
    ("src/hekswerk_scry/lean/statement.py",
     '        return "sorryAx" in self.axioms',
     "        return False",
     "a statement whose proof is sorry is presented as a proof"),
    ("src/hekswerk_scry/lean/openai_math.py",
     '    link = f"ComparatorChallenges/{item.name}.lean"',
     '    link = f"{item.name}"',
     "a scope note is matched to the wrong challenge"),
    ("src/hekswerk_scry/ai/statement_tools.py",
     '        return Outcome(f"paper search for \'{phrase}\'",',
     '        return Outcome(f"paper search for \'{phrase}\'", checked_by=CheckKind.LEAN, result=',
     "a lookup in the paper is presented as a Lean check"),
    ("src/hekswerk_scry/ai/statement_tools.py",
     "        if not _THEOREM_LINE.search(code):",
     "        if False:",
     "the helper's Lean claim is run without the theorem Lean must judge"),
    ("src/hekswerk_scry/lean/worker.py",
     '        return (_stat(self.workspace.exporter), _stat(root / "lake-manifest.json"), newest)',
     '        return (_stat(root / "lake-manifest.json"), newest)',
     "the kept-running Lean keeps going after the exporter is rebuilt"),
    ("src/hekswerk_scry/lean/worker.py",
     '        return (_stat(self.workspace.exporter), _stat(root / "lake-manifest.json"), newest)',
     '        return (_stat(self.workspace.exporter), _stat(root / "lake-manifest.json"), 0)',
     "the kept-running Lean keeps imports loaded after they are rebuilt"),
    ("src/hekswerk_scry/lean/worker.py",
     "            if line is None:\n                self._kill()",
     "            if line is None:\n                pass",
     "a check that ran out of time leaves Lean running it"),
    ("src/hekswerk_scry/lean/worker.py",
     "            if not line.startswith(REPLY_PREFIX):\n"
     "                stray.append(line)\n                continue",
     '            if not line.startswith(REPLY_PREFIX):\n                continue',
     "output a file printed is silently dropped"),
    ("src/hekswerk_scry/lean/workspace.py",
     "        if built.get(key) == stamp:",
     "        if key in built:",
     "imports are not rebuilt after a source changes"),
    ("src/hekswerk_scry/lean/workspace.py",
     '            subfolders[:] = sorted(s for s in subfolders if s not in {".lake", '
     '".scry-runs"})',
     '            subfolders[:] = sorted(s for s in subfolders if s not in {".lake"})',
     "every check rebuilds imports because Scry's own scratch files changed"),
    ("src/hekswerk_scry/lean/processes.py",
     "    with contextlib.suppress(ProcessLookupError):\n"
     "        os.killpg(process.pid, signal.SIGKILL)",
     "    with contextlib.suppress(ProcessLookupError):\n        process.kill()",
     "a timeout stops lake but leaves the Lean it started running"),
    ("src/hekswerk_scry/lean/openai_math.py",
     "    if len(targets) != text.count(_PREPRINT_MENTION):",
     "    if False:",
     "a paper link Scry can't read is silently skipped"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "    if any(r.verdict != MATCHES and _overlaps(r, planted_lines) for r in rows):",
     "    if any(_overlaps(r, planted_lines) for r in rows):",
     "an audit that said \"matches\" over a planted error is scored as catching it"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "        row.lean_lines[0] <= lines[1] and lines[0] <= row.lean_lines[1])",
     "        row.lean_lines[0] < lines[1] and lines[0] < row.lean_lines[1])",
     "a row on exactly the planted line doesn't count"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "    if count != 1:",
     "    if count < 1:",
     "a plant whose text occurs twice is applied anyway"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "            start = doc\n",
     "            pass\n",
     "a theorem's doc comment is left behind, dangling"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "    return workspace.root / COPIES_FOLDER / digest[:16]",
     "    return workspace.root / COPIES_FOLDER / variant",
     "a copy's folder name tells the helper which plant it holds"),
    ("src/hekswerk_scry/ai/statement_tools.py",
     '        known = {e.evidence_id for e in self.evidence if e.tool != "record_verdict"}',
     "        known = {e.evidence_id for e in self.evidence}",
     "a verdict row can cite another verdict row as its evidence"),
    ("src/hekswerk_scry/ai/statement_tools.py",
     "            if lines[1] - lines[0] + 1 > MAX_VERDICT_LINES:",
     "            if False:",
     "a verdict row can point at a whole file and catch every plant"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "    return not spent or sum(spent) + max(spent) <= budget_usd",
     "    return not spent or sum(spent) <= budget_usd",
     "the benchmark starts an audit that can take it past its budget"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "    return before.copy_sha256 == copy_sha256",
     "    return True",
     "an earlier audit is reused for a copy that has since changed"),
    ("src/hekswerk_scry/ai/benchmark.py",
     "        if stopped is not None:\n            skipped.append",
     "        if False:\n            skipped.append",
     "the benchmark keeps spending after the provider has refused an audit"),
    ("src/hekswerk_scry/web/server.py",
     '            if not _HOST.match(self.headers.get("Host", "")):',
     "            if False:",
     "the workbench answers a web page from another site (DNS rebinding)"),
    ("src/hekswerk_scry/web/server.py",
     "        if not path.is_relative_to(root) or not path.is_file():",
     "        if not path.is_file():",
     "the workbench serves files outside the folders it was given"),
    ("src/hekswerk_scry/web/server.py",
     "        if not path.name.endswith(suffixes):",
     "        if False:",
     "the workbench serves any kind of file a token names"),
    ("src/hekswerk_scry/web/server.py",
     '    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(library))',
     '    return ThreadingHTTPServer(("0.0.0.0", port), make_handler(library))',
     "the workbench listens to the whole network"),
    ("src/hekswerk_scry/web/server.py",
     '        elif end.get("kind") == "stopped":\n            state = "stopped"',
     '        elif end.get("kind") == "stopped":\n            state = "finished"',
     "a stopped audit is shown as finished"),
    ("src/hekswerk_scry/ai/run_log.py",
     '            if not line.endswith("\\n"):\n                break  # still being written',
     '            if False:\n                break  # still being written',
     "a half-written log line breaks the live view"),
    ("src/hekswerk_scry/ai/session.py",
     "                    if self.on_evidence is not None:",
     "                    if False:",
     "evidence is missing from an audit's log"),
    ("src/hekswerk_scry/lean/runner.py",
     '        if "sorryAx" in extra and not errors and not any("sorry" in p for p in problems):',
     '        if False:',
     "a proof relying on sorry counts as proven"),
]


def clear_bytecode() -> None:
    # Python's bytecode cache notices source changes only by modification time (to the
    # second) and size, so a same-length mutation undone quickly would keep running.
    for cache in (ROOT / "src").rglob("__pycache__"):
        shutil.rmtree(cache)


def main() -> int:
    python = ROOT / ".venv" / "bin" / "python"
    interpreter = str(python if python.is_file() else sys.executable)
    missed = 0
    for relative, original, mutated, mistake in MUTATIONS:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        if source.count(original) != 1:
            print(f"SETUP   {mistake}: the original text was not found exactly once in {relative}")
            missed += 1
            continue
        path.write_text(source.replace(original, mutated), encoding="utf-8")
        clear_bytecode()
        try:
            run = subprocess.run(
                [interpreter, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                cwd=ROOT, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, check=False,
            )
        finally:
            path.write_text(source, encoding="utf-8")
            clear_bytecode()
        caught = run.returncode != 0
        missed += not caught
        print(f"{'caught ' if caught else 'MISSED '} {mistake}")
    print(f"\n{len(MUTATIONS) - missed} of {len(MUTATIONS)} mutations caught.")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
