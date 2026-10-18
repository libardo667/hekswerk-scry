// A small Markdown renderer for audit reports: headings, paragraphs, lists, tables,
// code, bold, italics and inline code. It builds DOM nodes, never HTML, so a report can't
// inject anything into the page. Evidence citations such as [E7] or [E4, E5] become
// buttons that call `onCite(id)`.

import { h } from './dom.js'

const CITATION = /\[\s*(E\d+(?:\s*,\s*E\d+)*)\s*\]/g

export function renderMarkdown(text, onCite) {
  const root = h('div', { class: 'markdown' })
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const code = []
      i += 1
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++])
      i += 1
      root.append(h('pre', {}, h('code', {}, code.join('\n'))))
    } else if (/^#{1,6}\s/.test(line)) {
      const level = Math.min(6, line.match(/^#+/)[0].length + 1)
      root.append(h(`h${level}`, {}, inline(line.replace(/^#+\s*/, ''), onCite)))
      i += 1
    } else if (/^\s*>/.test(line)) {
      const quoted = []
      while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*>\s?/, ''))
      root.append(h('blockquote', {}, renderMarkdown(quoted.join('\n'), onCite)))
    } else if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows = []
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++])
      root.append(table(rows, onCite))
    } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const list = h(ordered ? 'ol' : 'ul')
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        let item = lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, '')
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) &&
               !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) item += ' ' + lines[i++].trim()
        list.append(h('li', {}, inline(item, onCite)))
      }
      root.append(list)
    } else if (line.trim() === '' || line.trim().startsWith('<!--')) {
      i += 1
    } else {
      const para = [line]
      i += 1
      while (i < lines.length && lines[i].trim() !== '' && !/^(#|```|\s*\||\s*>|\s*([-*]|\d+\.)\s)/.test(lines[i])) {
        para.push(lines[i++])
      }
      root.append(h('p', {}, inline(para.join(' '), onCite)))
    }
  }
  return root
}

function table(rows, onCite) {
  const cells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
  const body = rows.filter(r => !/^\s*\|[\s:|-]+\|\s*$/.test(r))
  const [head, ...rest] = body
  return h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, cells(head).map(c => h('th', {}, inline(c, onCite))))),
    h('tbody', {}, rest.map(r => h('tr', {}, cells(r).map(c => h('td', {}, inline(c, onCite))))))))
}

// Inline marks: `code`, **bold**, *italics*, and citations.
export function inline(text, onCite) {
  const out = []
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    out.push(...citations(text.slice(last, match.index), onCite))
    const token = match[0]
    if (token.startsWith('`')) out.push(h('code', {}, token.slice(1, -1)))
    else if (token.startsWith('**')) out.push(h('strong', {}, citations(token.slice(2, -2), onCite)))
    else out.push(h('em', {}, citations(token.slice(1, -1), onCite)))
    last = match.index + token.length
  }
  out.push(...citations(text.slice(last), onCite))
  return out
}

function citations(text, onCite) {
  if (!onCite) return [text]
  const out = []
  let last = 0
  for (const match of text.matchAll(CITATION)) {
    out.push(text.slice(last, match.index))
    const ids = match[1].split(',').map(s => s.trim())
    out.push('[', ...ids.flatMap((id, n) => [n ? ', ' : '',
      h('button', { class: 'cite', type: 'button', onclick: () => onCite(id) }, id)]), ']')
    last = match.index + match[0].length
  }
  out.push(text.slice(last))
  return out
}
