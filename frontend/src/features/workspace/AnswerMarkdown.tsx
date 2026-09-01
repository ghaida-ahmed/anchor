import Markdown from 'react-markdown';

/**
 * Renders a tutor answer as Markdown.
 *
 * The model emits Markdown — `**bold**`, numbered steps, occasional inline code —
 * and the previous `whitespace-pre-wrap` paragraph printed the syntax literally,
 * so answers read as `**Encapsulate what varies**`.
 *
 * SAFETY. `react-markdown` does not render raw HTML: it parses to an AST and emits
 * React elements, so there is no `dangerouslySetInnerHTML` anywhere in the path. A
 * model answer containing `<script>` or `<img onerror=…>` is escaped and shown as
 * text. That property is why no sanitiser is paired with it — `rehype-raw` is the
 * plugin that would opt *into* raw HTML, and it is deliberately absent.
 *
 * Element styling is passed explicitly rather than through a typography plugin,
 * because the surrounding bubble already sets its own size and colour and a global
 * prose class would fight it.
 */
export function AnswerMarkdown({ children }: { children: string }) {
  return (
    <div className="text-[15px] leading-relaxed">
      <Markdown
        components={{
          p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-ink-900">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => (
            <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
          ),
          li: ({ children }) => <li className="pl-0.5">{children}</li>,
          code: ({ children, className }) =>
            // A fenced block arrives with a language class; inline code has none.
            className ? (
              <code className="block overflow-x-auto rounded bg-paper-100 p-3 font-mono text-[13px] text-ink-800">
                {children}
              </code>
            ) : (
              <code className="rounded bg-paper-100 px-1 py-0.5 font-mono text-[13px] text-ink-800">
                {children}
              </code>
            ),
          pre: ({ children }) => (
            <pre className="mb-3 overflow-x-auto last:mb-0">{children}</pre>
          ),
          h1: ({ children }) => (
            <p className="mb-2 font-semibold text-ink-900">{children}</p>
          ),
          h2: ({ children }) => (
            <p className="mb-2 font-semibold text-ink-900">{children}</p>
          ),
          h3: ({ children }) => (
            <p className="mb-2 font-semibold text-ink-900">{children}</p>
          ),
          blockquote: ({ children }) => (
            <blockquote className="mb-3 border-l-2 border-paper-400 pl-3 text-ink-600 last:mb-0">
              {children}
            </blockquote>
          ),
          // The tutor's own citations are rendered by CitationList underneath, from
          // stored database rows. A link inside the answer text came from the model,
          // so it opens with no referrer and cannot reach back into the app.
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="underline underline-offset-2"
            >
              {children}
            </a>
          ),
        }}
      >
        {children}
      </Markdown>
    </div>
  );
}
