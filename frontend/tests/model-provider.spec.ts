import { describe, expect, it } from 'vitest';

import { getModelProvider } from '@/utils/model-provider';

describe('getModelProvider', () => {
  it('recognizes OpenAI behind a cross-region inference profile', () => {
    expect(getModelProvider('global.openai.gpt-6-sol')).toBe('OpenAI');
    expect(getModelProvider('us.openai.gpt-6-astra')).toBe('OpenAI');
  });

  it('recognizes other supported cross-region prefixes without consuming provider text', () => {
    expect(getModelProvider('apac.anthropic.claude-sonnet-4-6')).toBe('Anthropic');
    expect(getModelProvider('eu.amazon.nova-pro-v1:0')).toBe('Amazon');
  });
});
