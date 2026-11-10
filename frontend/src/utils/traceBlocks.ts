// Display model for trace content blocks. Rendered through text
// interpolation, never as HTML: trace content is caller-supplied text.

export interface ContentBlock {
  type?: string;
  text?: string;
  thinking?: string;
  name?: string;
  id?: string;
  input?: unknown;
  content?: unknown;
  is_error?: boolean;
  source?: { media_type?: string };
}

export interface BlockView {
  cls: string;
  text: string;
  tool?: boolean;
  name?: string;
  id?: string;
}

export function blockView(b: ContentBlock): BlockView {
  if (!b) return { cls: '', text: '' };
  const type = b.type || 'text';
  if (type === 'text') return { cls: '', text: b.text ?? '' };
  if (type === 'thinking') return { cls: 'thinking-block', text: b.thinking ?? '' };
  if (type === 'tool_use') {
    const inputStr =
      typeof b.input === 'string' ? b.input : JSON.stringify(b.input || {}, null, 2);
    return {
      cls: 'tool-use-block',
      tool: true,
      name: b.name ?? '',
      id: b.id ?? '',
      text: inputStr,
    };
  }
  if (type === 'tool_result') {
    const content =
      typeof b.content === 'string' ? b.content : JSON.stringify(b.content || '', null, 2);
    return { cls: 'tool-result-block' + (b.is_error ? ' error-block' : ''), text: content };
  }
  if (type === 'image') return { cls: '', text: `[image: ${b.source?.media_type ?? ''}]` };
  if (type === 'redacted_thinking') return { cls: 'thinking-block', text: '[redacted thinking]' };
  return { cls: '', text: JSON.stringify(b) };
}
