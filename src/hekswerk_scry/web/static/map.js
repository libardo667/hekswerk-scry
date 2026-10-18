// A proof map as a flat drawing: each step sits in a row below every step it takes a fact
// from, with arrows for "uses a fact from". Chokepoints (every route to the goal passes
// through them) are outlined, unused steps are faded, and each step shows the wiring
// check's status in Scry's own words. The wiring check follows arrows only; it never
// reads a step's math, so "Wiring checked" is not "proven".

import { api, badge, fill, h, message } from './dom.js'

const NODE_W = 210
const NODE_H = 46
const GAP_X = 26
const GAP_Y = 54
const SVG = 'http://www.w3.org/2000/svg'

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag)
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, String(v))
  for (const c of children) el.append(c instanceof Node ? c : document.createTextNode(String(c)))
  return el
}

// Row of a step = one more than the deepest step it uses (steps using nothing: row 0).
export function layers(steps, order) {
  const depth = {}
  for (const id of order) {
    const deps = (steps[id]?.depends_on || []).filter(d => d in steps)
    depth[id] = deps.length ? 1 + Math.max(...deps.map(d => depth[d] ?? 0)) : 0
  }
  const rows = []
  for (const id of order) (rows[depth[id]] ||= []).push(id)
  return rows
}

export async function mapView(token, container) {
  const data = await api('map', { file: token })
  const map = data.map
  const steps = Object.fromEntries(map.steps.map(s => [s.id, s]))
  const rows = layers(steps, data.order)
  const choke = new Set(data.scan.chokepoints.map(c => c.step_id))
  const unused = new Set(data.scan.unused_steps.map(u => u.step_id))
  const knotOf = {}
  data.scan.knots.forEach((k, n) => k.step_ids.forEach(id => { knotOf[id] = n }))

  const widest = Math.max(1, ...rows.map(r => r.length))
  const width = widest * (NODE_W + GAP_X) + GAP_X
  const height = rows.length * (NODE_H + GAP_Y) + GAP_Y
  const at = {}
  rows.forEach((row, y) => {
    const offset = (width - row.length * (NODE_W + GAP_X) + GAP_X) / 2
    row.forEach((id, x) => { at[id] = { x: offset + x * (NODE_W + GAP_X), y: GAP_Y / 2 + y * (NODE_H + GAP_Y) } })
  })

  const detail = h('aside', { class: 'map-detail' }, h('p', { class: 'hint' }, 'Choose a step to see what it assumes and proves.'))
  const drawing = svg('svg', { class: 'map-svg', viewBox: `0 0 ${width} ${height}`, width, height, role: 'img',
    'aria-label': `Proof map of ${map.title}` },
  svg('defs', {}, svg('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
    svg('path', { d: 'M 0 0 L 10 5 L 0 10 z', class: 'arrow-head' }))))
  for (const step of map.steps) {
    for (const dep of step.depends_on || []) {
      if (!at[dep] || !at[step.id]) continue
      const a = at[dep], b = at[step.id]
      const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H, x2 = b.x + NODE_W / 2, y2 = b.y
      drawing.append(svg('path', { class: 'edge', 'marker-end': 'url(#arrow)',
        d: `M ${x1} ${y1} C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2}, ${x2} ${y2}` }))
    }
  }
  const nodes = {}
  for (const step of map.steps) {
    const p = at[step.id]
    if (!p) continue
    const status = data.wiring.steps[step.id]
    const classes = ['node', `status-${(status?.status || 'not_checked').toLowerCase()}`]
    if (choke.has(step.id)) classes.push('chokepoint')
    if (unused.has(step.id)) classes.push('unused')
    if (step.id === map.goal_step_id) classes.push('goal')
    if (step.id in knotOf) classes.push(`knot knot-${knotOf[step.id] % 4}`)
    const title = step.title.length > 30 ? step.title.slice(0, 29) + '…' : step.title
    const node = svg('g', { class: classes.join(' '), tabindex: 0, role: 'button', transform: `translate(${p.x} ${p.y})` },
      svg('title', {}, `${step.id}: ${step.title}`),
      svg('rect', { width: NODE_W, height: NODE_H, rx: 7 }),
      svg('text', { x: 10, y: 18, class: 'node-id' }, step.id),
      svg('text', { x: 10, y: 35, class: 'node-title' }, title))
    const choose = () => {
      Object.values(nodes).forEach(n => n.classList.remove('chosen'))
      node.classList.add('chosen')
      showStep(step, status, choke.has(step.id), unused.has(step.id), detail)
    }
    node.addEventListener('click', choose)
    node.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose() } })
    nodes[step.id] = node
    drawing.append(node)
  }

  fill(container, 
    h('h1', {}, map.title),
    h('p', { class: 'meta' }, data.wiring.passed ? badge('wiring', 'Wiring checked (not proven)') : badge('stopped', 'Wiring broken'),
      ` ${data.wiring.summary}`),
    h('p', { class: 'hint' }, data.scan.overview),
    data.wiring.problems.map(p => message(p, 'warning')),
    h('div', { class: 'legend' },
      h('span', { class: 'legend-item legend-choke' }, 'chokepoint: every route to the goal passes through it'),
      h('span', { class: 'legend-item legend-unused' }, 'unused step: does not lead to the goal'),
      h('span', { class: 'legend-item legend-goal' }, 'the goal')),
    h('div', { class: 'map-columns' }, h('div', { class: 'map-scroll' }, drawing), detail),
    map.starting_facts?.length ? h('details', {}, h('summary', {}, 'Starting facts'),
      h('ul', {}, map.starting_facts.map(f => h('li', {}, h('code', {}, f))))) : null)
  fitToWidth(drawing, width, height)
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

function showStep(step, status, isChoke, isUnused, detail) {
  const views = step.views || {}
  fill(detail, 
    h('h2', {}, step.title),
    h('p', { class: 'meta' }, h('code', {}, step.id), ' ', status ? badge(status.status === 'wiring_broken' ? 'stopped' : 'wiring', status.label) : null,
      isChoke ? badge('control', 'chokepoint') : null, isUnused ? badge('lookup', 'unused step') : null),
    h('h3', {}, 'Assumes'),
    step.assumes.length ? h('ul', {}, step.assumes.map(a => h('li', {}, h('code', {}, a)))) : h('p', { class: 'hint' }, 'nothing'),
    h('h3', {}, 'Proves'), h('p', {}, h('code', {}, step.proves)),
    views.plain_english ? [h('h3', {}, 'In plain English'), h('p', {}, views.plain_english)] : null,
    views.math ? [h('h3', {}, 'Math'), h('pre', {}, views.math)] : null,
    views.code ? [h('h3', {}, 'Lean'), h('pre', {}, h('code', {}, views.code))] : null,
    status?.problems?.length ? status.problems.map(p => message(p, 'warning')) : null,
    status?.notes?.length ? status.notes.map(n => message(n)) : null)
}
