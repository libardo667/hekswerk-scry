// The workbench shell: a sidebar of everything Scry has on disk, and one view at a time.
// Addresses look like #/outline/<token>[/<part>], #/map/<token>, #/audit/<token>,
// #/report/<token>, #/benchmark/<id>, so the browser's back button and bookmarks work.

import { auditView } from './audit.js'
import { benchmarkView, reportView } from './benchmark.js'
import { mapView } from './map.js'
import { outlineView } from './outline.js'
import { ago, api, badge, dollars, fill, h, message } from './dom.js'

const sidebar = document.getElementById('sidebar')
const main = document.getElementById('main')
const REFRESH_MS = 5000
const menuToggle = document.getElementById('menu-toggle')
let overview = { runs: [], maps: [], outlines: [] }
let stopView = null

const STATE_BADGE = {
  finished: ['done', 'finished'],
  stopped: ['stopped', 'stopped'],
}

function stateBadge(audit) {
  if (audit.kind === 'report') return badge('lookup', 'report')
  const [kind, words] = STATE_BADGE[audit.state] || ['running', 'running?']
  return badge(kind, words)
}

function drawSidebar() {
  const here = location.hash.split('/').slice(0, 3).join('/')
  const link = (href, ...label) => h('a', { href, class: here === href ? 'here' : null }, ...label)
  fill(sidebar,
    h('h2', {}, 'Outlines'),
    overview.outlines.length ? h('ul', {}, overview.outlines.map(o => h('li', {},
      link(`#/outline/${encodeURIComponent(o.token)}`, o.title, h('span', { class: 'hint' }, ` · ${o.parts.toLocaleString('en-US')} parts`)))))
      : h('p', { class: 'hint' }, 'No outlines yet. `scry lean-outline FILE THEOREM -o NAME.outline.json` makes one.'),
    h('h2', {}, 'Step-by-step maps'),
    overview.maps.length ? h('ul', {}, overview.maps.map(m => h('li', {},
      link(`#/map/${encodeURIComponent(m.token)}`, m.title))))
      : h('p', { class: 'hint' }, 'No proof maps found.'),
    h('h2', {}, 'Audits'),
    overview.runs.length ? overview.runs.map(run => h('section', { class: 'run' },
      h('div', { class: 'run-name' },
        run.kind === 'benchmark'
          ? link(`#/benchmark/${encodeURIComponent(run.id)}`, `${run.name} (benchmark)`)
          : run.name),
      h('ul', {}, run.audits.map(a => h('li', {},
        link(`#/${a.kind === 'log' ? 'audit' : 'report'}/${encodeURIComponent(a.token)}`,
          stateBadge(a), ' ', a.copy ? `${a.challenge} · ${a.copy}` : a.title.replace('--', ' · '),
          a.kind === 'log' ? h('span', { class: 'hint' }, ` ${dollars(a.cost_usd)} · ${ago(a.last_event_at)}`) : null))))))
      : h('p', { class: 'hint' }, 'No audits yet. Run `scry audit-statement NAME` or `scry statement-benchmark`; they appear here as they run.'))
}

async function refresh() {
  try {
    overview = await api('overview')
    drawSidebar()
  } catch (error) {
    fill(sidebar, message(`The workbench can't be reached: ${error.message}`, 'warning'))
  }
  setTimeout(refresh, REFRESH_MS)
}

async function route() {
  if (stopView) { stopView(); stopView = null }
  const [, kind, ...rest] = location.hash.split('/')
  const token = decodeURIComponent(rest.join('/'))
  try {
    if (kind === 'outline') await outlineView(decodeURIComponent(rest[0]), main, rest[1] ? decodeURIComponent(rest[1]) : null)
    else if (kind === 'audit') stopView = auditView(token, main)
    else if (kind === 'report') await reportView(token, main)
    else if (kind === 'map') await mapView(token, main)
    else if (kind === 'benchmark') {
      const run = overview.runs.find(r => r.id === token) || (await api('overview')).runs.find(r => r.id === token)
      if (!run) throw new Error('That benchmark is no longer on disk.')
      await benchmarkView(run, main)
    } else home()
  } catch (error) {
    fill(main, message(error.message, 'warning'))
  }
  drawSidebar()
}

function home() {
  const level = (title, text, items) => h('section', { class: 'level' }, h('h2', {}, title), h('p', {}, text), items)
  fill(main,
    h('h1', {}, 'Scry'),
    h('p', { class: 'lead' }, 'Machine-written proofs are checked by Lean, but they are hard for people to follow. ',
      'Scry shows them at three levels, from the ideas down to the individual steps.'),
    h('div', { class: 'levels' },
      level('Outlines', 'What a result claims, the definitions you need to read that claim, and how its proof is built ' +
        'from the theorems of its project. Start here.',
      overview.outlines.length ? h('ul', {}, overview.outlines.map(o => h('li', {},
        h('a', { href: `#/outline/${encodeURIComponent(o.token)}` }, o.title)))) : h('p', { class: 'hint' }, 'None yet.')),
      level('Step-by-step maps', 'One proof, tactic by tactic, with “uses a fact from” arrows. This is the level Lean is ' +
        'persuaded at: useful for checking a step, not for seeing the idea.', null),
      level('Audits', 'The AI helper lines a formal statement up against its paper. Every claim it makes cites numbered ' +
        'evidence, labelled with who produced it.', null)),
    h('p', { class: 'hint' }, 'Read-only: nothing here starts a run, spends money or changes a file. Only Lean may say ',
      '“proven”. Anything the helper says is labelled ', badge('ai', "AI's reading"), '.'))
}

// On a phone the sidebar is a menu: the button shows it in place of the page, and choosing
// anything in it (or going back) shows the page again.
function showMenu(shown) {
  document.body.classList.toggle('menu-open', shown)
  menuToggle.setAttribute('aria-expanded', String(shown))
  menuToggle.textContent = shown ? 'Close' : 'Menu'
}
menuToggle.addEventListener('click', () => showMenu(!document.body.classList.contains('menu-open')))

window.addEventListener('hashchange', () => { showMenu(false); route() })
refresh().then(route)
