import { describe, expect, it } from 'vitest';
import { blockView } from '@/utils/traceBlocks';

describe('blockView', () => {
  it('keeps markup as plain text', () => {
    const v = blockView({ type: 'text', text: '<img src=x onerror=alert(1)>' });
    expect(v.text).toBe('<img src=x onerror=alert(1)>');
    expect(v.cls).toBe('');
  });

  it('maps tool_use with name, id and pretty input', () => {
    const v = blockView({ type: 'tool_use', name: 'search', id: 't1', input: { q: 'x' } });
    expect(v).toMatchObject({ tool: true, name: 'search', id: 't1', cls: 'tool-use-block' });
    expect(v.text).toBe('{\n  "q": "x"\n}');
  });

  it('flags tool_result errors', () => {
    expect(blockView({ type: 'tool_result', content: 'bad', is_error: true }).cls).toBe(
      'tool-result-block error-block',
    );
  });

  it('summarises images and unknown blocks', () => {
    expect(blockView({ type: 'image', source: { media_type: 'image/png' } }).text).toBe(
      '[image: image/png]',
    );
    expect(blockView({ type: 'weird' }).text).toBe('{"type":"weird"}');
  });
});

import { mount } from '@vue/test-utils';
import TraceBlock from '@/components/TraceBlock.vue';

describe('TraceBlock', () => {
  it('renders hostile text inertly', () => {
    const w = mount(TraceBlock, {
      props: { block: { type: 'text', text: '<img src=x onerror=alert(1)>' } },
    });
    expect(w.find('img').exists()).toBe(false);
    expect(w.text()).toBe('<img src=x onerror=alert(1)>');
    expect(w.html()).toContain('&lt;img');
  });

  it('renders tool_use with a space between name and id, no stray whitespace', () => {
    const w = mount(TraceBlock, {
      props: { block: { type: 'tool_use', name: 'search', id: 't1', input: 'q' } },
    });
    expect(w.classes()).toEqual(['block-text', 'tool-use-block']);
    expect(w.element.textContent).toBe('search t1q');
    expect(w.find('.tool-input').text()).toBe('q');
  });

  it('adds no whitespace around plain text', () => {
    const w = mount(TraceBlock, { props: { block: { type: 'text', text: 'hi' } } });
    expect(w.element.textContent).toBe('hi');
  });
});
