import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AnswerMarkdown } from '@/features/workspace/AnswerMarkdown';

/**
 * The bug this file exists for: the tutor's answers are Markdown, and the previous
 * renderer printed them literally, so a student read `**Encapsulate what varies**`
 * with the asterisks showing.
 *
 * The safety cases matter as much as the formatting ones. A model answer is
 * untrusted text — it is generated from a student's own uploaded documents, which
 * anyone can put anything into — so it must never become live markup.
 */

describe('bold — the reported bug', () => {
  it('renders **bold text** as bold, not as literal asterisks', () => {
    render(<AnswerMarkdown>{'**Encapsulate what varies**'}</AnswerMarkdown>);

    const bold = screen.getByText('Encapsulate what varies');
    expect(bold.tagName).toBe('STRONG');
    // The exact symptom that was reported.
    expect(document.body.textContent).not.toContain('**');
  });

  it('renders bold inside a sentence', () => {
    render(
      <AnswerMarkdown>{'TCP halves the **congestion window** on loss.'}</AnswerMarkdown>,
    );
    expect(screen.getByText('congestion window').tagName).toBe('STRONG');
    expect(document.body.textContent).not.toContain('**');
  });
});

describe('other required formatting', () => {
  it('renders italics', () => {
    render(<AnswerMarkdown>{'Growth is *additive* per round trip.'}</AnswerMarkdown>);
    expect(screen.getByText('additive').tagName).toBe('EM');
    expect(document.body.textContent).not.toContain('*additive*');
  });

  it('renders an unordered list', () => {
    render(<AnswerMarkdown>{'- slow start\n- congestion avoidance'}</AnswerMarkdown>);
    const list = document.querySelector('ul');
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll('li')).toHaveLength(2);
    expect(screen.getByText('slow start').tagName).toBe('LI');
  });

  it('renders an ordered list', () => {
    render(<AnswerMarkdown>{'1. detect loss\n2. halve cwnd\n3. probe again'}</AnswerMarkdown>);
    const list = document.querySelector('ol');
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll('li')).toHaveLength(3);
    // The numbers come from the list element, not from literal text.
    expect(document.body.textContent).not.toContain('1.');
  });

  it('renders separate paragraphs', () => {
    render(<AnswerMarkdown>{'First paragraph.\n\nSecond paragraph.'}</AnswerMarkdown>);
    expect(document.querySelectorAll('p')).toHaveLength(2);
  });

  it('renders inline code', () => {
    render(<AnswerMarkdown>{'The variable is `cwnd` here.'}</AnswerMarkdown>);
    const code = screen.getByText('cwnd');
    expect(code.tagName).toBe('CODE');
    expect(document.body.textContent).not.toContain('`');
  });

  it('renders a fenced code block', () => {
    render(<AnswerMarkdown>{'```python\ncwnd = cwnd // 2\n```'}</AnswerMarkdown>);
    expect(document.querySelector('pre')).not.toBeNull();
    expect(document.querySelector('pre code')).not.toBeNull();
    expect(document.body.textContent).toContain('cwnd = cwnd // 2');
    expect(document.body.textContent).not.toContain('```');
  });
});

describe('raw HTML is never executed', () => {
  it('does not create a script element from model output', () => {
    render(
      <AnswerMarkdown>
        {'Answer text <script>window.__pwned = true</script> continues.'}
      </AnswerMarkdown>,
    );
    expect(document.querySelector('script')).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined();
  });

  it('does not create an img with an inline error handler', () => {
    render(<AnswerMarkdown>{'<img src=x onerror="window.__xss = true">'}</AnswerMarkdown>);
    expect(document.querySelector('img')).toBeNull();
    expect((window as unknown as Record<string, unknown>).__xss).toBeUndefined();
  });

  it('does not render an injected iframe', () => {
    render(<AnswerMarkdown>{'<iframe src="https://evil.example.com"></iframe>'}</AnswerMarkdown>);
    expect(document.querySelector('iframe')).toBeNull();
  });

  it('does not honour an inline event handler on a styled element', () => {
    render(<AnswerMarkdown>{'<div onclick="window.__click = true">text</div>'}</AnswerMarkdown>);
    const div = document.querySelector('div[onclick]');
    expect(div).toBeNull();
  });

  it('escapes rather than drops the markup, so nothing silently disappears', () => {
    // A student pasting HTML into their notes should still be able to read it back.
    render(<AnswerMarkdown>{'Use <strong> for emphasis.'}</AnswerMarkdown>);
    expect(document.body.textContent).toContain('<strong>');
    // …but as text, not as an element the model created.
    expect(document.querySelector('strong')).toBeNull();
  });
});

describe('links from model output are defanged', () => {
  it('opens in a new tab with no referrer or opener', () => {
    render(<AnswerMarkdown>{'See [the RFC](https://example.com/rfc).'}</AnswerMarkdown>);
    const link = screen.getByRole('link', { name: 'the RFC' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('rel')).toContain('noreferrer');
  });
});

describe('plain answers are unaffected', () => {
  it('renders text with no Markdown exactly as written', () => {
    const answer =
      'When loss is detected, the sender halves the congestion window to drain the queue.';
    render(<AnswerMarkdown>{answer}</AnswerMarkdown>);
    expect(screen.getByText(answer)).toBeInTheDocument();
  });

  it('renders an empty answer without crashing', () => {
    expect(() => render(<AnswerMarkdown>{''}</AnswerMarkdown>)).not.toThrow();
  });
});

describe('the citations UI is unaffected', () => {
  it('still renders sources beneath an answer', async () => {
    const { CitationList } = await import('@/features/workspace/CitationList');
    render(
      <div>
        <AnswerMarkdown>{'**Loss** halves the window.'}</AnswerMarkdown>
        <CitationList
          citations={[
            {
              chunkId: 'c1',
              documentId: 'd1',
              documentName: 'lecture-05.pdf',
              pageNumber: 17,
              excerpt: 'On detecting loss the sender halves the congestion window.',
            },
          ]}
        />
      </div>,
    );

    // Markdown rendered…
    expect(screen.getByText('Loss').tagName).toBe('STRONG');
    // …and the citation is still there, with its page.
    expect(screen.getByText('lecture-05.pdf')).toBeInTheDocument();
    expect(document.body.textContent).toContain('17');
  });

  it('omits the page for a source that has none', async () => {
    const { CitationList } = await import('@/features/workspace/CitationList');
    render(
      <CitationList
        citations={[
          {
            chunkId: 'c2',
            documentId: 'd2',
            documentName: 'notes.txt',
            pageNumber: null,
            excerpt: 'Plain text notes.',
          },
        ]}
      />,
    );
    expect(screen.getByText('notes.txt')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('page');
  });
});
