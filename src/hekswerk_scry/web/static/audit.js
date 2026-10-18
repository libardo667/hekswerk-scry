// One statement audit, followed live from its run log.
//
// Left: what happened, in order. The helper's words between tool calls are its reading;
// each tool result is numbered evidence, labelled with who produced it (Lean, or a plain
// lookup); each comparison row it recorded is shown with the Lean lines it points at.
// Right: the Lean statement it audited, with those lines highlighted. In a benchmark copy,
// the planted lines are marked too: the person can see them, the helper never could.

import { renderMarkdown } from './markdown.js'
import { ago, api, badge, checkerBadge, dollars, fill, h, message } from './dom.js'

const POLL_MS = 2000

const TOOL_NAMES = {
  read_statement: "Lean's reading of the statement",
  read_definition: 'Read a definition',
  read_lean_lines: 'Read lines of the Lean file',
  list_paper_files: 'Listed the paper files',
  search_paper: 'Searched the paper',
  read_paper: 'Read the paper',
  check_lean_claim: 'Asked Lean to check a claim',
  record_verdict: 'Recorded a comparison row',
}

export function auditView(token, container) {
  const state = { after: 0, events: [], evidence: new Map(), rows: [], ended: false, timer: null }
  const header = h('div', { class: 'audit-header' })
  const timeline = h('ol', { class: 'timeline' })
  const statement = h('div', { class: 'statement' })
  const rowsTable = h('div', { class: 'rows' })
  const report = h('div', { class: 'report' })
  fill(container, 
    header,
    h('div', { class: 'audit-columns' },
      h('section', { class: 'audit-story' }, h('h2', {}, 'What happened'), timeline, report),
      h('aside', { class: 'audit-side' },
        h('h2', {}, 'The Lean statement'), statement,
        h('h2', {}, 'Rows the helper recorded'),
        h('p', { class: 'hint' }, "The helper's reading, row by row. Point at a row to see its lines."),
        rowsTable)))

  const lineEls = []

  function showStatement(start) {
    const text = start.statement_text || ''
    const planted = start.plant && start.plant.lines
    fill(statement, h('div', { class: 'file-name' }, start.statement_file || ''),
      h('pre', { class: 'code-lines' }, text.split('\n').map((line, n) => {
        const number = n + 1
        const inPlant = planted && number >= planted[0] && number <= planted[1]
        const el = h('div', { class: `code-line${inPlant ? ' planted' : ''}`, 'data-line': number },
          h('span', { class: 'line-number' }, number), h('span', { class: 'line-text' }, line || ' '))
        lineEls[number] = el
        return el
      })))
  }

  function highlight(lines, on) {
    if (!lines) return
    for (let n = lines[0]; n <= lines[1]; n += 1) lineEls[n]?.classList.toggle('lit', on)
    if (on) lineEls[lines[0]]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  function showHeader() {
    const start = state.events[0] || {}
    const end = state.events.at(-1) || {}
    const finished = end.kind === 'finish'
    const stopped = end.kind === 'stopped'
    const cost = finished || stopped ? end.cost_usd
      : [...state.events].reverse().find(e => e.kind === 'model')?.cost_so_far_usd
    const status = finished ? badge('done', 'finished') : stopped ? badge('stopped', 'stopped')
      : badge('running', `running, or ended without saying so · last event ${ago(end.at)}`)
    fill(header, 
      h('h1', {}, start.title || 'Audit'),
      h('p', { class: 'meta' }, status, ' ', start.model || '', start.effort ? ` (effort ${start.effort})` : '',
        ` · ${dollars(cost)}${finished || stopped ? '' : ' so far'} · ${state.evidence.size} pieces of evidence · ${state.rows.length} rows`),
      start.plant ? h('p', { class: 'plant' }, badge('plant', 'planted difference'), ' ',
        start.plant.what, ` (lines ${start.plant.lines[0]}–${start.plant.lines[1]}). `,
        h('span', { class: 'hint' }, 'You can see this; the helper could not.')) : null,
      start.copy === 'control' ? h('p', { class: 'plant' }, badge('control', 'unchanged copy'),
        " The statement exactly as OpenAI wrote it, audited the same way as the planted copies.") : null,
      stopped ? message(`Stopped: ${end.reason}`, 'warning') : null)
  }

  function citeTo(id) {
    const card = state.evidence.get(id)?.card
    if (!card) return
    card.open = true
    card.scrollIntoView({ block: 'center', behavior: 'smooth' })
    card.classList.add('flash')
    setTimeout(() => card.classList.remove('flash'), 1600)
  }

  function add(event) {
    if (event.kind === 'start') {
      showStatement(event)
      return
    }
    if (event.kind === 'model') {
      if (event.text && event.text.trim()) {
        timeline.append(h('li', { class: 'step step-model' },
          h('div', { class: 'who' }, badge('ai', "AI's reading")),
          renderMarkdown(event.text, citeTo)))
      }
      return
    }
    if (event.kind === 'evidence') {
      // An accepted row shows as its own chip (the verdict event right after this one).
      // A refused row stays visible, so a person can see what the helper got wrong.
      if (event.tool === 'record_verdict') {
        if (!/^verdict \d+:/.test(event.summary)) {
          timeline.append(h('li', { class: 'step' }, message(`A row was refused: ${event.result}`, 'warning')))
        }
        return
      }
      const card = evidenceCard(event)
      state.evidence.set(event.id, { event, card })
      timeline.append(h('li', { class: 'step' }, card))
      return
    }
    if (event.kind === 'verdict') {
      const row = event
      state.rows.push(row)
      const lines = row.lean_lines
      const chip = h('div', {
        title: "The helper's reading of this item",
        class: `row-chip verdict-${row.verdict === 'matches' ? 'match' : 'flag'}`,
        onmouseenter: () => highlight(lines, true), onmouseleave: () => highlight(lines, false),
      }, h('strong', {}, `Row ${row.number}: `), row.item, ' — ', h('em', {}, row.verdict),
      row.affects_main_result ? ' (affects the main result)' : '',
      lines ? ` · lines ${lines[0]}–${lines[1]}` : ' · not in the Lean')
      timeline.append(h('li', { class: 'step step-verdict' }, chip))
      rowsTable.append(rowCard(row, highlight, citeTo))
      if (lines) for (let n = lines[0]; n <= lines[1]; n += 1) {
        lineEls[n]?.classList.add(row.verdict === 'matches' ? 'row-match' : 'row-flag')
      }
      return
    }
    if (event.kind === 'finish') {
      fill(report, h('h2', {}, "The helper's report"),
        h('p', { class: 'hint' }, badge('ai', "AI's reading"),
          ' Except where it cites a Lean check. Citations open the evidence.'),
        renderMarkdown(event.answer || '', citeTo),
        event.unknown_citations?.length
          ? message(`It cites evidence that doesn't exist: ${event.unknown_citations.join(', ')}.`, 'warning') : null,
        event.hit_round_limit ? message('It ran out of tool calls before finishing.', 'warning') : null)
    }
  }

  async function poll() {
    try {
      const { events } = await api('log', { file: token, after: state.after })
      for (const event of events) {
        state.events.push(event)
        state.after = event.seq
        add(event)
      }
      const last = state.events.at(-1)
      state.ended = last && (last.kind === 'finish' || last.kind === 'stopped')
      showHeader()
    } catch (error) {
      header.append(message(error.message, 'warning'))
      state.ended = true
    }
    if (!state.ended && container.isConnected) state.timer = setTimeout(poll, POLL_MS)
  }

  poll()
  return () => clearTimeout(state.timer)
}

function evidenceCard(event) {
  const args = event.arguments || {}
  const details = []
  if (args.lean_code) details.push(h('h4', {}, 'The claim, in Lean'), h('pre', {}, h('code', {}, args.lean_code)))
  const plainArgs = Object.entries(args).filter(([key]) => key !== 'lean_code')
  if (plainArgs.length && event.tool !== 'record_verdict') {
    details.push(h('p', { class: 'args' }, plainArgs.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(' · ')))
  }
  details.push(h('h4', {}, 'What came back'), h('pre', { class: 'result' }, event.result || ''))
  const accepted = event.tool === 'check_lean_claim' && /: accepted$/.test(event.summary)
  const rejected = event.tool === 'check_lean_claim' && /not accepted$/.test(event.summary)
  return h('details', { class: `evidence${accepted ? ' accepted' : ''}${rejected ? ' rejected' : ''}`, id: `ev-${event.id}` },
    h('summary', {},
      h('span', { class: 'ev-id' }, event.id), ' ',
      checkerBadge(event.checked_by, event.checked_by_label), ' ',
      h('span', { class: 'ev-tool' }, TOOL_NAMES[event.tool] || event.tool),
      repeats(TOOL_NAMES[event.tool], event.summary) ? '' : `: ${event.summary}`),
    details)
}

// A summary that only says again what the tool name says ("Lean's reading of the statement
// of X" under "Lean's reading of the statement") is left out.
function repeats(name, summary) {
  return Boolean(name) && summary.toLowerCase().startsWith(name.toLowerCase())
}

function rowCard(row, highlight, citeTo) {
  return h('div', {
    class: `row-card verdict-${row.verdict === 'matches' ? 'match' : 'flag'}`,
    onmouseenter: () => highlight(row.lean_lines, true),
    onmouseleave: () => highlight(row.lean_lines, false),
  },
  h('div', { class: 'row-title' }, h('strong', {}, row.item), ' ', h('span', { class: 'verdict' }, row.verdict),
    row.affects_main_result ? h('span', { class: 'affects' }, 'affects the main result') : null),
  h('dl', {},
    h('dt', {}, 'Paper says'), h('dd', {}, row.paper_says),
    h('dt', {}, 'Lean says'), h('dd', {}, row.lean_says),
    h('dt', {}, 'Rests on'), h('dd', {}, row.evidence.flatMap((id, n) => [n ? ', ' : '',
      h('button', { class: 'cite', type: 'button', onclick: () => citeTo(id) }, id)])),
    h('dt', {}, 'Lean lines'), h('dd', {}, row.lean_lines ? `${row.lean_lines[0]}–${row.lean_lines[1]}` : 'none (not in the formalization)')))
}
