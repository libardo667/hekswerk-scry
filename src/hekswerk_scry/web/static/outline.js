// An outline: a result, and every theorem and definition in its project that it rests on,
// read from Lean's record of the compiled project (src/hekswerk_scry/lean/outline.py).
//
// A proof map shows one proof tactic by tactic, which is the level Lean is persuaded at.
// This shows the level a proof is understood at:
//   - what the result claims, and the definitions you need to read that claim;
//   - what Lean found worth a look: hypotheses a proof never uses, and the objects the
//     proof constructs;
//   - how the proof is built: the theorems it uses, and theirs, as a tree you open as you go,
//     heaviest first.
// Every arrow here comes from Lean. Nothing on this page is the AI's reading.

import { api, badge, fill, h, message } from './dom.js'

const NARROW = window.matchMedia('(max-width: 1000px)')
const STANDARD_AXIOMS = ['propext', 'Classical.choice', 'Quot.sound']
const LIST_LIMIT = 40

const number = n => n.toLocaleString('en-US')
const plural = (n, word, words = word + 's') => `${number(n)} ${n === 1 ? word : words}`

export async function outlineView(token, container, initialPart) {
  const data = await api('outline', { file: token })
  const ids = data.ids
  // The index leaves out what the page can work out: names equal to IDs, file names, and
  // "used by" (the reverse of "uses").
  const parts = data.parts.map((p, n) => ({ ...p, name: p.name ?? ids[n], file: p.file === null ? null : data.files[p.file], used_by: [] }))
  parts.forEach((p, n) => new Set([...p.statement_uses, ...p.body_uses]).forEach(u => parts[u].used_by.push(n)))
  const result = data.result
  // Kinds whose body is part of what they mean (definitions, structures, ...), as Scry decides it.
  const MEANING_KINDS = new Set(data.meaning_kinds)
  const claim = new Set(data.claim)
  const where = Object.fromEntries(ids.map((id, n) => [id, n]))
  const space = parts[result].name.includes('.') ? parts[result].name.slice(0, parts[result].name.lastIndexOf('.') + 1) : ''
  const short = n => (space && parts[n].name.startsWith(space) ? parts[n].name.slice(space.length) : parts[n].name)
  const totalLines = parts.reduce((sum, p) => sum + p.lines, 0)
  const uses = n => [...new Set([...parts[n].statement_uses, ...parts[n].body_uses])]
  const isTheorem = n => parts[n].kind === 'theorem'
  const heaviest = (a, b) => parts[b].rests_on_lines - parts[a].rests_on_lines || short(a).localeCompare(short(b))
  let chosen = null

  const detail = h('aside', { class: 'outline-detail' }, h('p', { class: 'hint' }, 'Choose a theorem or definition to read it here.'))

  // --- shared pieces ------------------------------------------------------------------

  function partButton(n, label = short(n)) {
    return h('button', { type: 'button', class: 'part-link', title: parts[n].name, onclick: () => choose(n) }, breakable(label))
  }

  // A long Lean name may wrap after a dot or an underscore rather than mid-word.
  function breakable(name) {
    return name.split(/(?<=[._])/).flatMap((piece, i) => (i ? [h('wbr'), piece] : [piece]))
  }

  function kindBadge(n) {
    const kind = parts[n].kind
    return badge(kind === 'theorem' ? 'theorem' : MEANING_KINDS.has(kind) ? 'definition' : 'lookup', kind)
  }

  function place(n) {
    const p = parts[n]
    if (!p.file) return 'file not found'
    const file = p.file.split('/').pop()
    return p.start_line ? `${file}, line ${p.start_line}` : file
  }

  function chips(list, empty) {
    if (!list.length) return h('p', { class: 'hint' }, empty)
    const sorted = [...list].sort(heaviest)
    const shown = h('div', { class: 'chips' })
    const show = all => fill(shown, (all ? sorted : sorted.slice(0, LIST_LIMIT)).map(n => partButton(n)),
      !all && sorted.length > LIST_LIMIT ? h('button', { type: 'button', class: 'more', onclick: () => show(true) }, `all ${number(sorted.length)}`) : null)
    show(false)
    return shown
  }

  function weight(n) {
    const share = totalLines ? parts[n].rests_on_lines / totalLines : 0
    const fill = h('span')
    // Through the style object: the page's Content-Security-Policy refuses style attributes.
    fill.style.width = `${Math.max(share * 100, parts[n].rests_on ? 1 : 0).toFixed(1)}%`
    return h('span', { class: 'weight', title: `rests on ${plural(parts[n].rests_on, 'declaration')}, ${number(parts[n].rests_on_lines)} lines of Lean` },
      h('span', { class: 'weight-bar' }, fill),
      parts[n].rests_on ? `${number(parts[n].rests_on_lines)} lines beneath` : 'nothing beneath')
  }

  // --- choosing a part ----------------------------------------------------------------

  async function choose(n, scroll = true) {
    chosen = n
    container.querySelectorAll('.is-chosen').forEach(el => el.classList.remove('is-chosen'))
    container.querySelectorAll(`[data-part="${n}"]`).forEach(el => el.classList.add('is-chosen'))
    history.replaceState(null, '', `#/outline/${encodeURIComponent(token)}/${encodeURIComponent(ids[n])}`)
    fill(detail, h('p', { class: 'hint' }, 'Reading…'))
    if (scroll && NARROW.matches) detail.scrollIntoView({ behavior: 'smooth', block: 'start' })
    let full
    try {
      full = await api('outline-part', { file: token, part: ids[n] })
    } catch (error) {
      fill(detail, message(error.message, 'warning'))
      return
    }
    if (chosen !== n) return
    showPart(n, full)
  }

  function showPart(n, full) {
    const p = parts[n]
    const lines = full.source ? full.source.split('\n').length : 0
    const proofWord = isTheorem(n) ? 'Its proof uses' : MEANING_KINDS.has(p.kind) ? 'Its definition uses' : 'It uses'
    const map = data.maps[ids[n]]
    fill(detail,
      h('h2', { class: 'part-title' }, short(n)),
      space ? h('p', { class: 'full-name' }, p.name) : null,
      h('p', { class: 'meta' }, kindBadge(n), p.private ? [' ', badge('lookup', 'private')] : null,
        ` ${place(n)}${p.lines ? ` · ${plural(p.lines, 'line')}` : ''}`),
      full.route.length > 1 ? h('nav', { class: 'route', 'aria-label': 'How the result reaches it' },
        h('span', { class: 'hint' }, 'From the result: '),
        full.route.map((id, i) => [i ? h('span', { class: 'route-sep' }, ' › ') : null,
          id === ids[n] ? h('strong', {}, short(where[id])) : partButton(where[id])])) : null,
      full.doc ? [h('h3', {}, 'The author’s note'), h('blockquote', { class: 'doc' }, full.doc)] : null,
      full.unused_hypotheses.length ? h('div', { class: 'callout' },
        h('strong', {}, 'Its proof never uses ', full.unused_hypotheses.length === 1 ? 'this hypothesis' : 'these hypotheses', ':'),
        h('ul', {}, full.unused_hypotheses.map(x => h('li', {}, hypothesis(x)))),
        h('p', { class: 'hint' }, 'Read from Lean’s record of the proof. The theorem holds without ',
          full.unused_hypotheses.length === 1 ? 'it' : 'them', '.')) : null,
      h('h3', {}, isTheorem(n) ? 'What it states' : 'Its type'),
      h('pre', { class: 'lean-text' }, full.statement),
      full.source ? h('details', { class: 'source', open: lines <= 30 },
        h('summary', {}, `As written in ${p.file.split('/').pop()} (${plural(lines, 'line')})`),
        h('pre', { class: 'lean-text' }, full.source)) : null,
      isTheorem(n) ? h('p', {}, map ? h('a', { href: `#/map/${encodeURIComponent(map)}` }, 'Its proof step by step (Lean’s tactics) →')
        : h('span', { class: 'hint' }, 'No step-by-step map of this proof yet. ',
          h('code', {}, `scry lean-import ${p.file} ${p.name} -o MAP.json`), ' makes one.')) : null,
      h('h3', {}, `Its statement mentions (${p.statement_uses.length})`), chips(p.statement_uses, 'nothing else from the project'),
      h('h3', {}, `${proofWord} (${p.body_uses.length})`), chips(p.body_uses, 'nothing else from the project'),
      h('h3', {}, `Used by (${p.used_by.length})`), chips(p.used_by, n === result ? 'nothing: this is the result' : 'nothing in this outline'))
  }

  function hypothesis(x) {
    return [x.name ? [h('code', {}, x.name), ' : '] : null, h('code', {}, x.statement),
      x.name?.startsWith('_') ? h('span', { class: 'hint' }, ' (the leading _ in its name is the author’s own sign that it isn’t needed)') : null]
  }

  // --- what it claims -----------------------------------------------------------------

  const claimed = data.claim
  const direct = new Set(parts[result].statement_uses)
  const claimItem = n => h('li', { 'data-part': n }, partButton(n), ' ', kindBadge(n), h('span', { class: 'hint' }, ` ${place(n)}`))
  const named = claimed.filter(n => direct.has(n))
  const beneath = claimed.filter(n => !direct.has(n))
  const claimSection = h('section', { id: 'claims', class: 'outline-section' },
    h('h2', {}, 'What it claims'),
    h('pre', { class: 'lean-text statement' }, 'Reading…'),
    claimed.length ? [
      h('p', {}, `To read the claim you need ${plural(claimed.length, 'definition')} from the project. `,
        'Definitions are where a formal statement can quietly say something other than a paper does, so these are the part to read.'),
      h('h3', {}, `Named in the statement (${named.length})`),
      h('ul', { class: 'part-list' }, named.map(claimItem)),
      beneath.length ? h('details', {}, h('summary', {}, `and ${plural(beneath.length, 'more definition')} that those are built from, nearest first`),
        h('ol', { class: 'part-list' }, beneath.map(claimItem))) : null]
      : h('p', {}, 'The claim uses nothing from the project beyond Lean and Mathlib.'))

  // --- worth a look -------------------------------------------------------------------

  const unusedIn = parts.map((p, n) => n).filter(n => parts[n].unused.length)
  const others = unusedIn.filter(n => n !== result)
  const built = parts[result].body_uses.filter(n => MEANING_KINDS.has(parts[n].kind) && !claim.has(n)).sort(heaviest)
  const lookSection = h('section', { id: 'look', class: 'outline-section' },
    h('h2', {}, 'Worth a look'),
    parts[result].unused.length ? h('div', { class: 'callout' },
      h('p', {}, h('strong', {}, `The proof of ${short(result)} never uses ${parts[result].unused.length === 1 ? 'this hypothesis' : 'these hypotheses'}:`)),
      h('ul', {}, parts[result].unused.map(x => h('li', {}, hypothesis(x)))),
      h('p', {}, 'So what Lean checked covers the result without ', parts[result].unused.length === 1 ? 'it' : 'them',
        '. That can be deliberate: a statement can keep a hypothesis to match a paper, or to say what the result is for. ',
        'It can also mean the formal statement differs from what the paper needs. Either way, it’s worth knowing why it’s there.'))
      : h('p', {}, `The proof of ${short(result)} uses every hypothesis its statement gives it.`),
    built.length ? [
      h('h3', {}, `What the proof constructs (${built.length})`),
      h('p', { class: 'hint' }, 'Definitions the proof uses that the claim doesn’t mention: objects it builds to prove the claim. ',
        'In an existence proof these are usually the heart of the argument.'),
      h('ul', { class: 'part-list' }, built.map(n => h('li', { 'data-part': n }, partButton(n), ' ', kindBadge(n), ' ', weight(n))))] : null,
    others.length ? [
      h('h3', {}, `Other theorems with hypotheses their proofs never use (${others.length})`),
      h('ul', { class: 'part-list' }, others.map(n => h('li', { 'data-part': n }, partButton(n), ': ',
        parts[n].unused.map((x, i) => [i ? ', ' : null, h('code', {}, x.name || x.statement)]))))] : null)

  // --- how the proof is built ---------------------------------------------------------

  function treeRow(n, depth, path) {
    const kids = uses(n)
    const theorems = kids.filter(isTheorem).sort(heaviest)
    const made = kids.filter(k => !isTheorem(k) && !claim.has(k)).sort(heaviest)
    const words = kids.filter(k => !isTheorem(k) && claim.has(k)).sort(heaviest)
    const open = h('ul', { class: 'tree', hidden: true })
    let filled = false
    const twist = h('button', { type: 'button', class: 'twist', 'aria-expanded': 'false',
      'aria-label': `Show what ${short(n)} uses`, disabled: !kids.length || null }, kids.length ? '▸' : '·')
    twist.addEventListener('click', () => {
      const showing = open.hidden
      if (showing && !filled) {
        filled = true
        const here = new Set([...path, n])
        fill(open,
          theorems.map(k => here.has(k) ? null : treeRow(k, depth + 1, here)),
          made.map(k => here.has(k) ? null : treeRow(k, depth + 1, here)),
          words.length ? h('li', { class: 'tree-words' }, h('details', {},
            h('summary', {}, `and ${plural(words.length, 'definition')} from the claim`),
            h('div', { class: 'chips' }, words.map(k => partButton(k))))) : null)
      }
      open.hidden = !showing
      twist.textContent = showing ? '▾' : '▸'
      twist.setAttribute('aria-expanded', String(showing))
    })
    const counts = [theorems.length ? plural(theorems.length, 'theorem') : null,
      made.length ? plural(made.length, 'construction') : null].filter(Boolean).join(', ')
    return h('li', { 'data-part': n },
      h('div', { class: 'tree-row' }, twist,
        h('div', { class: 'tree-body' },
          h('span', { class: 'tree-name' }, partButton(n), isTheorem(n) ? null : [' ', kindBadge(n)],
            parts[n].unused.length ? [' ', badge('plant', 'unused hypothesis')] : null),
          h('span', { class: 'tree-facts' }, weight(n), counts ? h('span', { class: 'hint' }, `uses ${counts}`) : null))),
      open)
  }

  const treeSection = h('section', { id: 'built', class: 'outline-section' },
    h('h2', {}, 'How the proof is built'),
    h('p', { class: 'hint' }, 'Each theorem with the theorems and constructions its proof uses, heaviest first (the bar is the share of the project’s Lean beneath it). Open ▸ to go a level down.'),
    h('ul', { class: 'tree tree-top' }, treeRow(result, 0, new Set())))
  treeSection.querySelector('.twist')?.click()

  // --- finding a part -----------------------------------------------------------------

  const found = h('ul', { class: 'part-list found' })
  const search = h('input', { type: 'search', class: 'find', placeholder: `Find among ${number(parts.length)} theorems and definitions`,
    'aria-label': 'Find a theorem or definition' })
  search.addEventListener('input', () => {
    const words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
    if (!words.length) { fill(found); return }
    const hits = parts.map((p, n) => n).filter(n => words.every(w => parts[n].name.toLowerCase().includes(w))).sort(heaviest)
    fill(found, hits.slice(0, LIST_LIMIT).map(n => h('li', { 'data-part': n }, partButton(n), ' ', kindBadge(n), h('span', { class: 'hint' }, ` ${place(n)}`))),
      hits.length > LIST_LIMIT ? h('li', { class: 'hint' }, `and ${number(hits.length - LIST_LIMIT)} more; type more to narrow it`) : null,
      hits.length ? null : h('li', { class: 'hint' }, 'Nothing by that name.'))
  })

  // --- the page -----------------------------------------------------------------------

  const counts = {}
  for (const p of parts) counts[p.kind] = (counts[p.kind] || 0) + 1
  const extra = data.axioms.filter(a => !STANDARD_AXIOMS.includes(a))
  const r = parts[result]
  fill(container,
    h('header', { class: 'outline-head' },
      h('p', { class: 'eyebrow' }, 'Outline', space ? ` · ${space.slice(0, -1)}` : ''),
      h('h1', { class: 'map-title' }, short(result)),
      h('p', { class: 'meta' }, kindBadge(result), ` ${place(result)} · Lean ${data.lean_version}`),
      h('div', { class: 'facts' },
        h('p', {}, `Rests on ${plural(r.rests_on, 'declaration')} from its project: `,
          Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => plural(n, k)).join(', '),
          ` (counting itself), about ${number(totalLines)} lines of Lean.`),
        extra.includes('sorryAx') ? message('Lean reports it relies on `sorry`: something beneath it was never proven.', 'warning')
          : extra.length ? message(`Lean reports it relies on axioms beyond the standard three: ${extra.join(', ')}.`, 'warning')
            : h('p', {}, 'Lean reports it relies on the three standard axioms only (', STANDARD_AXIOMS.join(', '), '), so nothing beneath it is left unproven with ', h('code', {}, 'sorry'), '.'),
        h('p', { class: 'hint' }, 'All of this page is read from Lean’s record of the compiled project when the outline was made. It is not a fresh check.')),
      data.changed_files.length ? message(`${plural(data.changed_files.length, 'file has', 'files have')} changed since this outline was made (${data.changed_files.slice(0, 3).join(', ')}${data.changed_files.length > 3 ? ', …' : ''}). Make it again with scry lean-outline before relying on it.`, 'warning') : null,
      h('nav', { class: 'jump' },
        h('a', { href: '#claims', onclick: jump('claims') }, `What it claims (${claimed.length})`),
        h('a', { href: '#look', onclick: jump('look') }, `Worth a look (${unusedIn.length + built.length})`),
        h('a', { href: '#built', onclick: jump('built') }, 'How the proof is built'),
        h('a', { href: '#find', onclick: jump('find') }, 'Find'))),
    h('div', { class: 'outline-columns' },
      h('div', { class: 'outline-main' }, claimSection, lookSection, treeSection,
        h('section', { id: 'find', class: 'outline-section' }, h('h2', {}, 'Find'), search, found)),
      detail))

  function jump(id) {
    return event => { event.preventDefault(); container.querySelector(`#${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
  }

  api('outline-part', { file: token, part: ids[result] })
    .then(full => fill(claimSection.querySelector('.statement'), full.statement))
    .catch(error => fill(claimSection.querySelector('.statement'), error.message))
  const start = initialPart in where ? where[initialPart] : result
  choose(start, false)
}
