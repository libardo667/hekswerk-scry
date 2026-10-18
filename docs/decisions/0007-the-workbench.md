# Decision 0007: The browser workbench, read-only first

**Status:** accepted for Checkpoint 6.

## The problem

Everything Scry did happened in a terminal, so only the person running it could follow an
audit, and only by reading its final report. The owner asked for a way to "actually sort of
follow along with what's being done".

## Decisions

**Watch first; act later.** `scry serve` shows audits as they run, benchmark results,
audit reports and proof maps. It starts nothing, spends nothing and writes nothing. Running
audits, drafting cards and applying them from the browser can come once watching is solid.

**Every audit keeps an append-only run log** (`ai/run_log.py`, `*.events.jsonl`): what it is
about (`start`, including the statement it audits), what the model said between tool calls,
each piece of evidence in full, each comparison row, and how it ended (`finish` or
`stopped`). Each event is one line, written whole and flushed at once, so the page can follow
a run while it happens and a crash or restart loses at most the event being written.
Watching changes nothing the model sees; a test sends the same scripted run with and without
a log and requires identical requests.

**Who said what, on screen.** Evidence is labelled with who produced it ("Lean (checks the
math itself)", "lookup (no check)"). The helper's words and rows are labelled "AI's
reading". Citations such as `[E9]` open the evidence they name. Lean's accepted and rejected
claims are marked, and each row lights up the Lean lines it is about. In a benchmark copy the
planted lines are marked for the person, who can see them; the helper never could.

**Built the way Parallax is**, the owner's research workspace: plain JavaScript modules with
no build step, and a small local server (here, Python's standard library). Nothing from a run
log, paper or model reply is ever treated as HTML: text goes in through `textContent`, and a
small Markdown renderer builds DOM nodes. Parallax's 3D map doesn't carry over; a proof map is
drawn flat, each step below the steps it takes facts from.

**Big Lean maps fold their `have` blocks.** Drawn in rows, a 79-step Navier–Stokes proof put
about thirty leaf steps in its top row and was unreadable. Machine-written Lean proofs are
mostly chains of `have`s, so a *block* is what one `have` writes inside itself (the tactics of
its `by` block, nested `by` blocks in its term) together with its "Why h holds" step
(`web/blocks.py`). Blocks start folded, each drawn as one box that takes facts in from outside
and gives `h` to the steps that use it; that proof becomes 31 boxes that read like its outline
(`hd`, then `hediv` and `hePDE`, then `he`, `hvel`, ...). Opening a block shows its steps with
the blocks inside it still folded. The `have` line itself is never folded: the main line of
the proof runs from each tactic to the next, so folding it in would draw arrows in a circle.
Folding any set of blocks can't draw a circle either (a block takes in only facts from before
it in the source and gives out only its own); tests fold 300 random sets of blocks in two real
maps and check, and a block that a route could leave and re-enter is not offered.

**On a phone** the sidebar becomes a Menu button, the views stack in one column, and choosing a
step scrolls to its details. Wide drawings and tables scroll inside their own box; the page
itself stays the width of the screen.

**Safety.** The server listens on 127.0.0.1 only and refuses requests whose `Host` header
names any other site (so a web page elsewhere can't reach it through DNS rebinding). Files
are named by tokens that must resolve, inside a folder it was given, to a file of the kind the
request asks for. Pages are served with a Content-Security-Policy that allows only the
workbench's own scripts and styles. Tests run a real server and check each refusal, and the
mutation check confirms they would notice each safeguard going missing.

**From a phone: one public name, behind Cloudflare Access.** The owner wanted to follow along
away from the computer. The server still listens on 127.0.0.1 only. A Cloudflare Tunnel run
by `cloudflared` on the same machine carries requests for `scry.hekswerk.com` to it, after
Cloudflare Access has signed the person in with Google; one Allow policy names the owner's
email. That is the same arrangement as the owner's grimoire workbench, with a tunnel of its
own. Scry answers that one name only when the request carries exactly one Access token that
it has checked itself (`web/access.py`): an RS256 signature against the team's published
keys (fetched from Cloudflare, again when an unknown key appears, at most once a minute), this
application's audience tag, this team as issuer, type `app`, and a current validity window
with 30 seconds of clock skew. The tunnel is also told to require the token
(`originRequest.access`), so a mistake in either place alone doesn't open the door. The
signature check is held to OpenSSL: a test key and signature made by `openssl` are accepted,
and the test signer reproduces OpenSSL's signature byte for byte. Templates for the tunnel
and the two user services are in `ops/cloudflare/`.

Setting it up: create the Access application (self-hosted, `scry.hekswerk.com`, Google,
one Allow policy for one email); `cloudflared tunnel create hekswerk-scry`;
`cloudflared tunnel route dns hekswerk-scry scry.hekswerk.com`; fill in the templates; then
`systemctl --user enable --now hekswerk-scry-serve hekswerk-scry-cloudflared`. Cloudflare
sees the traffic in transit; the workbench shows proofs, audits and reports, never keys.

## Not yet

- Starting work from the browser (audits, benchmarks, Lean checks, cards).
- Showing the exact passage the helper quoted from a paper lookup, next to its citation.
- Audits from before run logs existed (the first benchmark) show their written report only.
