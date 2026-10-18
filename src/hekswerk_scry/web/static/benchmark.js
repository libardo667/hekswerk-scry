// A statement-audit benchmark: how each planted difference was scored, with links into
// the audits themselves, and the run's own summary below.

import { renderMarkdown } from './markdown.js'
import { api, badge, dollars, fill, h, message } from './dom.js'

const SCORE_WORDS = {
  caught: ['done', 'caught'],
  'dangerous miss': ['stopped', 'dangerous miss'],
  missed: ['stopped', 'missed'],
}

export async function benchmarkView(run, container) {
  fill(container, h('h1', {}, `Benchmark: ${run.name}`), h('p', { class: 'hint' }, 'Loading…'))
  const [results, summary] = await Promise.all([
    run.results ? api('results', { file: run.results }) : null,
    run.summary ? api('text', { file: run.summary }) : null,
  ])
  const byName = new Map(run.audits.map(a => [a.challenge && a.copy ? `${a.challenge}--${a.copy}` : a.name, a]))
  const tables = []
  for (const [challenge, variants] of Object.entries(results || {})) {
    tables.push(h('h2', {}, challenge), h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Copy', 'Result', 'Rows', 'Cost', ''].map(t => h('th', {}, t)))),
      h('tbody', {}, variants.map(v => {
        const audit = byName.get(`${challenge}--${v.variant}`)
        const [kind, words] = v.score ? SCORE_WORDS[v.score] || ['lookup', v.score] : ['control', 'unchanged copy']
        return h('tr', {},
          h('td', {}, v.variant, v.planted_lines ? h('span', { class: 'hint' }, ` (lines ${v.planted_lines[0]}–${v.planted_lines[1]})`) : null),
          h('td', {}, badge(kind, words), v.also_in_control ? ' control flagged these lines too: check by hand' : ''),
          h('td', {}, `${v.rows.length} (${v.rows.filter(r => r.verdict !== 'matches').length} flagged)`),
          h('td', {}, dollars(v.cost_usd)),
          h('td', {}, audit ? h('a', { href: `#/${audit.kind === 'log' ? 'audit' : 'report'}/${encodeURIComponent(audit.token)}` },
            audit.kind === 'log' ? 'follow the audit' : 'read the report') : ''))
      })))))
  }
  fill(container, 
    h('h1', {}, `Benchmark: ${run.name}`),
    h('p', { class: 'hint' }, 'Scores are mechanical: a plant is caught when a recorded row other than "matches" points at its lines. ',
      'The audits themselves are the helper\'s reading.'),
    tables.length ? tables : message('No results yet.'),
    summary ? h('details', { class: 'summary-text' }, h('summary', {}, 'The run\'s written summary'),
      renderMarkdown(summary.text)) : null)
}

export async function reportView(token, container) {
  const { name, text } = await api('text', { file: token })
  fill(container, 
    h('h1', {}, name),
    message('This audit ran before Scry kept run logs, so only its written report is here. ' +
            'Citations name evidence, but its full results were not saved.'),
    h('div', { class: 'report' }, renderMarkdown(text)))
}
