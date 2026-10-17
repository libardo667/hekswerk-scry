# Decision 0006: A Lean process kept running, so checks cost seconds

**Status:** accepted for Checkpoint 5.

## The problem

Every Lean check started a new `lean` process, and loading a file's imports (often all of
Mathlib) took one to four minutes before Lean read a single line of the proof. The first
statement audit spent most of its 28 minutes waiting for Mathlib to load, once per check.
A check that costs minutes is one the AI helper, or a person, avoids running. The owner's
goal: either of them should be able to reach for a Lean check as often as they like
without it being a burden.

## Decisions

**`scry-export --serve`.** The exporter has a mode that stays running and answers requests,
one line of JSON each (`lean/ScryExport/Serve.lean`): a proof check, a statement read, or a
proof-map export. It loads a file's imports once and keeps the environment right after them.
A later file with exactly the same import lines starts from that environment, not from the
end of the previous file, so nothing one file declares and no option it sets is visible to
the next. Lean's own editor server reuses imports in the same way. A check on a file whose
imports are already loaded takes well under a second, plus the proof itself.

**The same judge.** A check's reply carries Lean's messages exactly as `lean --json` prints
them, and `lean/runner.py` judges them with the same code it uses for a fresh run. A
real-Lean test runs a set of files both ways and requires identical verdicts, problems and
messages. Some of those files only make sense in order: one declares a helper and turns on
an option, and the next two must not see either. Breaking that isolation on purpose turned
the test red.

**One set of imports per process.** Loading a second, different set of imports into the
same Lean v4.34.1 process gave a broken environment: in the next file even `Fin` and
`WithBot` were unknown. (Lean v4.10 tolerated it, but nothing promises that.) So each
process holds exactly one set of imports, and Lean itself refuses a file whose imports
differ from what its process loaded. Scry keeps a small pool of processes (two, since each
can hold all of Mathlib, about 5 GB), one per set of import lines, and stops the least
recently used. When Lean refuses a file, its process is restarted with the file's own
imports. That's a routing correction, not a retry: a new process has nothing loaded and
can't refuse.

**Read nothing from a file Lean rejects.** That broken environment went unnoticed at first
because statement mode ignored the file's errors and only reported that the theorem wasn't
there. Statement mode and proof-map export now refuse a file with errors and name the first
few. Check mode always reported them.

**The swap's check is always fresh.** Trying a card uses the kept-running process. The
check that allows `apply_lean_card` to change anything runs a new `lean` process, every
time. It's the moment of the swap, and it's rare enough that the wait is fine.

**Restarted when anything it loaded could be out of date:** when the exporter is rebuilt,
when any of the project's own build output (`.lake/build/lib`) changes, when its package
list (`lake-manifest.json`) changes, and after a check runs out of time.

**No needless builds.** Scry runs `lake build` on a file's project imports before checking
it, and on `openai/math` that takes about 30 seconds even when nothing needs building. Scry
now records what it built along with a fingerprint of every `.lean` file in the project
(outside `.lake` and Scry's own scratch folder, `.scry-runs`), and skips the build while
the fingerprint is unchanged. Reading the fingerprint takes about 0.4 seconds for
`openai/math`'s 120,000 files.

**Stopping a program stops everything it started.** `lake env lean ...` doesn't run Lean
itself; it starts Lean as a child process. On a timeout, Scry used to stop only `lake`, and
the Lean underneath kept running. Three such processes were found still running an endless
loop from a timeout test, five hours later, holding three CPU cores. Every program Scry
runs now goes through `lean/processes.py`, which gives it its own process group and stops
the whole group on a timeout or interruption. A test runs each place Scry calls `lake`
with a stand-in that starts a child, and checks the child is gone afterwards.

**A Lean v4.34.1 difference.** Lean v4.10 let statement mode switch off Lean's record of
how each command was elaborated, which halved its time. Lean v4.34.1's frontend reads that
record for every command and reported an "index out of bounds" panic for each one when it
was off, so on v4.34.1 it stays on.

Set `SCRY_LEAN_WORKER=off` to run a fresh `lean` for every check.

Lean files are programs, and in the kept-running process they all run in one process. The
rule from `AGENTS.md` still holds: only run Scry's Lean features on files you trust.
