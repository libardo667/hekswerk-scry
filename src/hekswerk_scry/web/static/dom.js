// Small helpers shared by the workbench's views.
//
// Everything shown comes from run logs, papers and model replies, so none of it is ever
// treated as HTML: text goes in through textContent, and structure is built as DOM nodes.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue
    if (key === 'class') el.className = value
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value)
    else el.setAttribute(key, value === true ? '' : String(value))
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue
    el.append(child instanceof Node ? child : document.createTextNode(String(child)))
  }
  return el
}

// Replace an element's contents. Unlike replaceChildren, this flattens arrays and drops
// null, undefined and false, so a view can write `cond ? part : null` freely.
export function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false))
  return el
}

export async function api(name, params = {}) {
  const query = new URLSearchParams(params).toString()
  const response = await fetch(`/api/${name}${query ? '?' + query : ''}`)
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `The workbench answered ${response.status}.`)
  return data
}

export function dollars(value) {
  return typeof value === 'number' ? `$${value.toFixed(2)}` : '—'
}

export function ago(at) {
  if (!at) return ''
  const seconds = Math.max(0, (Date.now() - Date.parse(at)) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} days ago`
}

// Who made a claim, in the exact words Scry uses everywhere.
export function badge(kind, text) {
  return h('span', { class: `badge badge-${kind}` }, text)
}

export function checkerBadge(checkedBy, label) {
  return checkedBy === 'lean' ? badge('lean', label || 'Lean')
    : checkedBy ? badge('wiring', label) : badge('lookup', 'lookup (no check)')
}

export function message(text, kind = 'note') {
  return h('p', { class: `message message-${kind}` }, text)
}
