# Decision 0010: A public introduction in front of the signed-in workbench

**Status:** accepted, 2026-10-19.

## The problem

The repository became public so that mathematicians and funders could look at Scry. Its
public name, scry.hekswerk.com, still sent everyone to a Cloudflare sign-in, so a visitor
learned nothing about Scry without being on the owner's list first. The owner asked for the
name to be "publicly visitable with a clear introduction", with the workbench itself (Scry's
real runs) still behind the Access policy.

## Decisions

**The introduction is fixed files, and nothing else is open.** `web/public/` holds a page about
Scry and its stylesheet. The server answers the public name without a sign-in only for those
files: `/` is `index.html`, and each other file is served at `/` plus its plain name
(`server.public_file`). It names no folder Scry was given and reads nothing from a run, a proof
or a paper, so what it shows can't depend on what the workbench holds. It runs no scripts: it
is served with `default-src 'none'`, so a browser would refuse one.

**The workbench moved under `/workbench/`**, its API under `/workbench/api/`. Every other
address on the public name needs the Access token that `web/access.py` checks, exactly as
before, and the local address answers the same paths without one. One prefix is what lets
Cloudflare protect the workbench with one path rule.

**Three places agree, and each fails closed.**
- *Cloudflare's edge:* a Bypass application for the whole name, and the existing Access
  application (same audience tag) narrowed to the path `workbench`. Cloudflare applies the
  most specific path.
- *The tunnel* (`ops/cloudflare/hekswerk-scry.yml.example`): the first rule lets exactly the
  introduction's addresses through without a token (the same pattern the server uses). The next
  rule requires the Access token for everything else on the name.
- *Scry's server:* the introduction's files, or a token it checks itself.

If the edge's path rule ever stopped holding, a workbench request would arrive without a token,
and the tunnel and the server would both refuse it. If the tunnel's rule were too wide, the
server would still refuse anything but the introduction.

Tests run a real server under the public name and request, without a sign-in, every file of
the introduction (each served), and every workbench file, every API name, the old addresses
and paths that try to climb out of `web/public/` (each refused). The mutation check confirms
that they notice the exemption widening, the introduction serving the workbench's files, the
name check loosening, and the introduction being allowed scripts.

## Setting it up

In Cloudflare Zero Trust, Access, Applications:
1. Edit the existing Scry application. Change its public hostname to `scry.hekswerk.com`
   with path `workbench`, and keep its policy. Its audience tag stays the same, so Scry's
   settings don't change.
2. Add a self-hosted application for `scry.hekswerk.com` with no path, and give it one policy:
   action *Bypass*, include *Everyone*.

Then update `~/.cloudflared/hekswerk-scry.yml` from the template and restart both services.
Check from outside: `/` and `/intro.css` answer, and `/workbench/` goes to the sign-in.
