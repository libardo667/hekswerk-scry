// The workbench shell: a sidebar of everything Scry has on disk, and one view at a time.
// Addresses look like #/audit/<token>, #/report/<token>, #/benchmark/<id>, #/map/<token>,
// so the browser's back button and bookmarks work.

import { auditView } from './audit.js'
import { benchmarkView, reportView } from './benchmark.js'
import { mapView } from './map.js'
import { ago, api, badge, dollars, fill, h, message } from './dom.js'

const sidebar = document.getElementById('sidebar')
const main = document.getElementById('main')
const REFRESH_MS = 5000
let overview = { runs: [], maps: [] }
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
  const here = decodeURIComponent(location.hash)
  fill(sidebar, 
    h('h2', {}, 'Audits'),
    overview.runs.length ? overview.runs.map(run => h('section', { class: 'run' },
      h('div', { class: 'run-name' },
        run.kind === 'benchmark'
          ? h('a', { href: `#/benchmark/${encodeURIComponent(run.id)}`, class: here === `#/benchmark/${run.id}` ? 'here' : null }, `${run.name} (benchmark)`)
          : run.name),
      h('ul', {}, run.audits.map(a => {
        const href = `#/${a.kind === 'log' ? 'audit' : 'report'}/${encodeURIComponent(a.token)}`
        return h('li', {}, h('a', { href, class: here === decodeURIComponent(href) ? 'here' : null },
          stateBadge(a), ' ', a.copy ? `${a.challenge} · ${a.copy}` : a.title.replace('--', ' · '),
          a.kind === 'log' ? h('span', { class: 'hint' }, ` ${dollars(a.cost_usd)} · ${ago(a.last_event_at)}`) : null))
      }))))
      : h('p', { class: 'hint' }, 'No audits yet. Run `scry audit-statement NAME` or `scry statement-benchmark`; they appear here as they run.'),
    h('h2', {}, 'Proof maps'),
    overview.maps.length ? h('ul', {}, overview.maps.map(m => h('li', {},
      h('a', { href: `#/map/${encodeURIComponent(m.token)}` }, m.title))))
      : h('p', { class: 'hint' }, 'No proof maps found.'))
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
    if (kind === 'audit') stopView = auditView(token, main)
    else if (kind === 'report') await reportView(token, main)
    else if (kind === 'map') await mapView(token, main)
    else if (kind === 'benchmark') {
      const run = overview.runs.find(r => r.id === token) || (await api('overview')).runs.find(r => r.id === token)
      if (!run) throw new Error('That benchmark is no longer on disk.')
      await benchmarkView(run, main)
    } else {
      fill(main, 
        h('h1', {}, 'Scry workbench'),
        h('p', {}, 'A read-only window onto what Scry is doing. Nothing here starts a run, ',
          'spends money or changes a file.'),
        h('ul', {},
          h('li', {}, h('strong', {}, 'Audits'), ': follow the AI helper as it lines a formal statement up against its paper. ',
            'Each tool result is numbered evidence, labelled with who produced it.'),
          h('li', {}, h('strong', {}, 'Benchmarks'), ': planted differences, and whether the audits caught them.'),
          h('li', {}, h('strong', {}, 'Proof maps'), ': a proof as steps and "uses a fact from" arrows.')),
        h('p', { class: 'hint' }, 'Only Lean may say "proven". Anything the helper says is labelled ',
          badge('ai', "AI's reading"), '.'))
    }
  } catch (error) {
    fill(main, message(error.message, 'warning'))
  }
  drawSidebar()
}

window.addEventListener('hashchange', route)
refresh().then(route)
