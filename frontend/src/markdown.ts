// Small, dependency-free Markdown subset for assistant replies.
//
// Everything is HTML-escaped before any tag is emitted, and links are limited
// to http(s), so the result is safe to pass to v-html.

const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, char => HTML_ESCAPES[char] ?? char)
}

function renderInline(source: string): string {
  const code: string[] = []
  let text = escapeHtml(source)

  // Inline code first: its content must not be parsed as emphasis or links.
  text = text.replace(/`([^`\n]+)`/g, (_match, body: string) => {
    code.push(`<code>${body}</code>`)
    return `\u0000${code.length - 1}\u0000`
  })

  text = text.replace(
    /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_match, label: string, url: string) =>
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`,
  )
  text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
  text = text.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:!?)]|$)/g, '$1<em>$2</em>')
  text = text.replace(/(^|[\s(])_([^_\n]+)_(?=[\s.,;:!?)]|$)/g, '$1<em>$2</em>')
  text = text.replace(/~~([^~\n]+)~~/g, '<del>$1</del>')

  return text.replace(/\u0000(\d+)\u0000/g, (_match, index: string) => code[Number(index)] ?? '')
}

type ListState = { ordered: boolean; items: string[] }

export function renderMarkdown(source: string): string {
  if (!source) return ''

  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const blocks: string[] = []
  let paragraph: string[] = []
  let list: ListState | null = null
  let fence: { lang: string; lines: string[] } | null = null

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(`<p>${paragraph.map(line => renderInline(line)).join('<br>')}</p>`)
    paragraph = []
  }
  const flushList = () => {
    if (!list) return
    const tag = list.ordered ? 'ol' : 'ul'
    blocks.push(
      `<${tag}>${list.items.map(item => `<li>${renderInline(item)}</li>`).join('')}</${tag}>`,
    )
    list = null
  }
  const flushFence = () => {
    if (!fence) return
    const language = fence.lang ? ` class="language-${fence.lang}"` : ''
    blocks.push(`<pre><code${language}>${escapeHtml(fence.lines.join('\n'))}</code></pre>`)
    fence = null
  }
  const flush = () => {
    flushParagraph()
    flushList()
    flushFence()
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    const fenceMarker = line.match(/^\s*```([\w+-]*)\s*$/)

    if (fence) {
      if (fenceMarker) flushFence()
      else fence.lines.push(raw)
      continue
    }
    if (fenceMarker) {
      flushParagraph()
      flushList()
      fence = { lang: fenceMarker[1] ?? '', lines: [] }
      continue
    }
    if (!line.trim()) {
      flush()
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      flush()
      const level = heading[1]?.length ?? 1
      blocks.push(`<h${level}>${renderInline(heading[2] ?? '')}</h${level}>`)
      continue
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flush()
      blocks.push('<hr>')
      continue
    }
    const quote = line.match(/^\s*>\s?(.*)$/)
    if (quote) {
      flushParagraph()
      flushList()
      flushFence()
      blocks.push(`<blockquote>${renderInline(quote[1] ?? '')}</blockquote>`)
      continue
    }

    const bullet = line.match(/^\s*[-*+•]\s+(.*)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (bullet || ordered) {
      flushParagraph()
      flushFence()
      const orderedNow = Boolean(ordered)
      if (!list || list.ordered !== orderedNow) {
        flushList()
        list = { ordered: orderedNow, items: [] }
      }
      ;(list as ListState).items.push((bullet ?? ordered)?.[1] ?? '')
      continue
    }

    flushList()
    flushFence()
    paragraph.push(line.trim())
  }

  flush()
  return blocks.join('\n')
}
