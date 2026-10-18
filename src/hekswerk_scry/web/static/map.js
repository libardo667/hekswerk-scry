// A proof map as a flat drawing: each step sits in a row below every step it takes a fact
// from, with arrows for "uses a fact from". Chokepoints (every route to the goal passes
// through them) are outlined, unused steps are faded, and each step shows the wiring
// check's status in Scry's own words. The wiring check follows arrows only; it never
// reads a step's math, so "Wiring checked" is not "proven".
//
// Lean maps come with blocks (web/blocks.py): what a `have ... := by` writes inside itself,
// with its "Why h holds" step. Blocks start folded, each drawn as one box; opening one shows
// its steps, with the blocks inside it still folded.

import { api, badge, fill, h, message } from './dom.js'

const NODE_W = 210
const NODE_H = 46
const GAP_X = 26
const GAP_Y = 54
const SVG = 'http://www.w3.org/2000/svg'
const NARROW = window.matchMedia('(max-width: 1000px)')

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag)
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, String(v))
  for (const c of children) el.append(c instanceof Node ? c : document.createTextNode(String(c)))
  return el
}

// Row of a node = one more than the deepest node it uses (nodes using nothing: row 0).
// `order` must list every node after the nodes it uses.
export function layers(uses, order) {
  const depth = {}
  for (const id of order) {
    const deps = (uses[id] || []).filter(d => d in depth)
    depth[id] = deps.length ? 1 + Math.max(...deps.map(d => depth[d])) : 0
  }
  const rows = []
  for (const id of order) (rows[depth[id]] ||= []).push(id)
  return rows
}

// Each node after the nodes it uses; ties keep the order nodes were first seen in.
function sorted(nodes, uses) {
  const waiting = Object.fromEntries(nodes.map(n => [n, new Set(uses[n])]))
  const users = Object.fromEntries(nodes.map(n => [n, []]))
  for (const n of nodes) for (const d of uses[n]) users[d].push(n)
  const out = []
  const ready = nodes.filter(n => waiting[n].size === 0)
  while (ready.length) {
    const n = ready.shift()
    out.push(n)
    for (const u of users[n]) {
      waiting[u].delete(n)
      if (waiting[u].size === 0) ready.push(u)
    }
  }
  if (out.length !== nodes.length) throw new Error('This map can’t be drawn with these blocks folded (its arrows would run in a circle). Please report it: it is a Scry bug.')
  return out
}

export async function mapView(token, container) {
  const data = await api('map', { file: token })
  const map = data.map
  const steps = Object.fromEntries(map.steps.map(s => [s.id, s]))
  const choke = new Set(data.scan.chokepoints.map(c => c.step_id))
  const unused = new Set(data.scan.unused_steps.map(u => u.step_id))
  const blocks = Object.fromEntries((data.blocks || []).map(b => [b.root, b]))
  // Blocks around each step, outermost first.
  const around = {}
  for (const b of Object.values(blocks).sort((x, y) => y.members.length - x.members.length)) {
    for (const m of b.members) (around[m] ||= []).push(b.root)
  }
  const open = new Set()
  let chosen = null

  const detail = h('aside', { class: 'map-detail' }, h('p', { class: 'hint' }, 'Choose a step to see what it assumes and proves.'))
  const scroll = h('div', { class: 'map-scroll' })
  const controls = h('div', { class: 'map-controls' })

  // What a step is drawn as: the outermost folded block around it, or the step itself.
  const drawnAs = id => {
    const folded = (around[id] || []).find(root => !open.has(root))
    return folded ? `block:${folded}` : id
  }

  function draw() {
    const nodes = []
    const uses = {}
    for (const id of data.order) {
      const n = drawnAs(id)
      if (!(n in uses)) { uses[n] = new Set(); nodes.push(n) }
    }
    for (const step of map.steps) {
      const to = drawnAs(step.id)
      for (const dep of step.depends_on || []) {
        const from = drawnAs(dep)
        if (from !== to && from in uses) uses[to].add(from)
      }
    }
    const order = sorted(nodes, uses)
    const rows = layers(Object.fromEntries(nodes.map(n => [n, [...uses[n]]])), order)
    const widest = Math.max(1, ...rows.map(r => r.length))
    const width = widest * (NODE_W + GAP_X) + GAP_X
    const height = rows.length * (NODE_H + GAP_Y) + GAP_Y
    const at = {}
    rows.forEach((row, y) => {
      const offset = (width - row.length * (NODE_W + GAP_X) + GAP_X) / 2
      row.forEach((id, x) => { at[id] = { x: offset + x * (NODE_W + GAP_X), y: GAP_Y / 2 + y * (NODE_H + GAP_Y) } })
    })
    const drawing = svg('svg', { class: 'map-svg', viewBox: `0 0 ${width} ${height}`, width, height, role: 'img',
      'aria-label': `Proof map of ${map.title}` },
    svg('defs', {}, svg('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
      svg('path', { d: 'M 0 0 L 10 5 L 0 10 z', class: 'arrow-head' }))))
    for (const to of nodes) {
      for (const from of uses[to]) {
        const a = at[from], b = at[to]
        const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H, x2 = b.x + NODE_W / 2, y2 = b.y
        drawing.append(svg('path', { class: 'edge', 'marker-end': 'url(#arrow)',
          d: `M ${x1} ${y1} C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2}, ${x2} ${y2}` }))
      }
    }
    for (const n of nodes) drawing.append(n.startsWith('block:') ? blockNode(blocks[n.slice(6)], at[n]) : stepNode(steps[n], at[n]))
    fill(scroll, drawing)
    fitToWidth(drawing, width, height)
    const count = Object.keys(blocks).length
    fill(controls, count ? [
      h('span', { class: 'hint' }, `${count} block${count === 1 ? '' : 's'} (what a \`have\` writes inside itself); ${open.size} open. `),
      h('button', { type: 'button', onclick: () => { Object.keys(blocks).forEach(r => open.add(r)); draw() } }, 'Open all'),
      ' ',
      h('button', { type: 'button', onclick: () => { open.clear(); draw() } }, 'Fold all')] : null)
  }

  function node(classes, p, label, title, tip, onChoose, key) {
    const g = svg('g', { class: classes.join(' '), tabindex: 0, role: 'button', transform: `translate(${p.x} ${p.y})` },
      svg('title', {}, tip),
      svg('rect', { width: NODE_W, height: NODE_H, rx: 7 }),
      svg('text', { x: 10, y: 18, class: 'node-id' }, label),
      svg('text', { x: 10, y: 35, class: 'node-title' }, title.length > 30 ? title.slice(0, 29) + '…' : title))
    if (key === chosen) g.classList.add('chosen')
    const choose = () => {
      chosen = key
      g.ownerSVGElement.querySelectorAll('.chosen').forEach(n => n.classList.remove('chosen'))
      g.classList.add('chosen')
      onChoose()
      if (NARROW.matches) detail.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    g.addEventListener('click', choose)
    g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose() } })
    return g
  }

  function stepNode(step, p) {
    const status = data.wiring.steps[step.id]
    const classes = ['node', `status-${(status?.status || 'not_checked').toLowerCase()}`]
    if (choke.has(step.id)) classes.push('chokepoint')
    if (unused.has(step.id)) classes.push('unused')
    if (step.id === map.goal_step_id) classes.push('goal')
    if (around[step.id]) classes.push('in-block')
    return node(classes, p, step.id, step.title, `${step.id}: ${step.title}`,
      () => showStep(step, status), step.id)
  }

  function blockNode(block, p) {
    const classes = ['node', 'block']
    if (block.members.some(m => choke.has(m))) classes.push('chokepoint')
    if (block.members.every(m => unused.has(m))) classes.push('unused')
    if (around[block.root]) classes.push('in-block')
    const name = blockName(block)
    return node(classes, p, `${block.root} · ${block.members.length} steps folded`, name,
      `${name}: ${block.members.length} steps folded. Choose it to see what it takes and gives.`,
      () => showBlock(block), `block:${block.root}`)
  }

  function blockName(block) {
    const whys = block.members.filter(m => steps[m].lean_introduced_by === block.root)
    return whys.map(w => steps[w].title.replace(/ \(from step [^)]*\)$/, '')).join('; ')
  }

  function showBlock(block) {
    const root = steps[block.root]
    fill(detail,
      h('h2', {}, blockName(block)),
      h('p', { class: 'meta' }, badge('control', 'folded block'), ` ${block.members.length} steps, written inside `,
        h('code', {}, root.views?.code?.split('\n')[0] || block.root), ` (step ${block.root}).`),
      h('p', {}, h('button', { type: 'button', onclick: () => { open.add(block.root); chosen = null; draw(); showStep(root, data.wiring.steps[root.id]) } },
        'Open this block')),
      h('h3', {}, 'Gives'), h('ul', {}, block.gives.map(f => h('li', {}, h('code', {}, f)))),
      h('h3', {}, 'Takes from outside'),
      block.takes.length ? h('ul', {}, block.takes.map(f => h('li', {}, h('code', {}, f)))) : h('p', { class: 'hint' }, 'nothing'),
      block.members.some(m => unused.has(m)) ? message(`${block.members.filter(m => unused.has(m)).length} of its steps are unused (they don't lead to the goal).`) : null)
  }

  function showStep(step, status) {
    const views = step.views || {}
    const inside = (around[step.id] || []).filter(r => open.has(r))
    const innermost = inside[inside.length - 1]
    fill(detail,
      h('h2', {}, step.title),
      h('p', { class: 'meta' }, h('code', {}, step.id), ' ', status ? badge(status.status === 'wiring_broken' ? 'stopped' : 'wiring', status.label) : null,
        choke.has(step.id) ? badge('control', 'chokepoint') : null, unused.has(step.id) ? badge('lookup', 'unused step') : null),
      innermost ? h('p', {}, h('button', { type: 'button', onclick: () => { open.delete(innermost); chosen = `block:${innermost}`; draw(); showBlock(blocks[innermost]) } },
        `Fold the block it's in (${blockName(blocks[innermost])})`)) : null,
      blocks[step.id] && !open.has(step.id) ? h('p', {}, h('button', { type: 'button', onclick: () => { open.add(step.id); draw() } },
        `Open the block this line writes (${blocks[step.id].members.length} steps)`)) : null,
      h('h3', {}, 'Assumes'),
      step.assumes.length ? h('ul', {}, step.assumes.map(a => h('li', {}, h('code', {}, a)))) : h('p', { class: 'hint' }, 'nothing'),
      h('h3', {}, 'Proves'), h('p', {}, h('code', {}, step.proves)),
      views.plain_english ? [h('h3', {}, 'In plain English'), h('p', {}, views.plain_english)] : null,
      views.math ? [h('h3', {}, 'Math'), h('pre', {}, views.math)] : null,
      views.code ? [h('h3', {}, 'Lean'), h('pre', {}, h('code', {}, views.code))] : null,
      status?.problems?.length ? status.problems.map(p => message(p, 'warning')) : null,
      status?.notes?.length ? status.notes.map(n => message(n)) : null)
  }

  fill(container,
    h('h1', { class: 'map-title' }, map.title),
    h('p', { class: 'meta' }, data.wiring.passed ? badge('wiring', 'Wiring checked (not proven)') : badge('stopped', 'Wiring broken'),
      ` ${data.wiring.summary}`),
    h('p', { class: 'hint' }, data.scan.overview),
    data.wiring.problems.map(p => message(p, 'warning')),
    h('div', { class: 'legend' },
      h('span', { class: 'legend-item legend-choke' }, 'chokepoint: every route to the goal passes through it'),
      h('span', { class: 'legend-item legend-unused' }, 'unused step: does not lead to the goal'),
      h('span', { class: 'legend-item legend-goal' }, 'the goal'),
      Object.keys(blocks).length ? h('span', { class: 'legend-item legend-block' }, 'folded block') : null),
    controls,
    h('div', { class: 'map-columns' }, scroll, detail),
    map.starting_facts?.length ? h('details', {}, h('summary', {}, 'Starting facts'),
      h('ul', {}, map.starting_facts.map(f => h('li', {}, h('code', {}, f))))) : null)
  draw()
}

// Shrink a drawing that is a little too wide to fit; keep a much wider one at full size
// (it scrolls), since shrinking it further would make the step titles unreadable.
const SMALLEST = 0.6

function fitToWidth(drawing, width, height) {
  const room = drawing.parentElement.clientWidth - 2
  if (room <= 0 || room >= width) return
  const scale = Math.max(SMALLEST, room / width)
  drawing.setAttribute('width', Math.round(width * scale))
  drawing.setAttribute('height', Math.round(height * scale))
}
