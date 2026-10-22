import { describe, expect, it } from 'vitest';

import {
  formatPrice,
  modelCardCheckBadge,
  pricingTiers,
  promptCacheBadges,
  routeLabel,
  type PricingDisplayRecord,
} from '@/utils/pricing';

const gptRow: PricingDisplayRecord = {
  input_price_per_1m: '4.4',
  output_price_per_1m: '22',
  cache_write_price_per_1m: '5.5',
  cache_read_price_per_1m: '0.44',
  context_tiers: [
    {
      label: '≤272K',
      max_input_tokens: 272000,
      input_price_per_1m: '4.4',
      cache_write_price_per_1m: '5.5',
      cache_read_price_per_1m: '0.44',
      output_price_per_1m: '22',
    },
    {
      label: '>272K',
      max_input_tokens: null,
      input_price_per_1m: '8.8',
      cache_write_price_per_1m: '11',
      cache_read_price_per_1m: '0.88',
      output_price_per_1m: '33',
    },
  ],
  endpoint_family: 'runtime',
  api: 'responses',
  scope: 'global',
  prompt_cache: {
    implicit: true,
    explicit: true,
    explicit_content_types: ['input_image', 'input_text'],
    max_breakpoints: 4,
    min_prefix_tokens: 1024,
    ttl: '30m',
  },
};

describe('pricing display', () => {
  it('renders both context bands for catalogued GPT rows', () => {
    const tiers = pricingTiers(gptRow);
    expect(tiers.map((t) => t.label)).toEqual(['≤272K', '>272K']);
    expect(formatPrice(tiers[1]!.output_price_per_1m)).toBe('$33.00');
  });

  it('falls back to one band for database rows and dashes missing prices', () => {
    const tiers = pricingTiers({ input_price_per_1m: '3', output_price_per_1m: '15' });
    expect(tiers).toHaveLength(1);
    expect(tiers[0]!.label).toBe('All');
    expect(formatPrice(tiers[0]!.cache_write_price_per_1m)).toBe('—');
    expect(formatPrice('0.022')).toBe('$0.0220');
  });

  it('labels the resolved route', () => {
    expect(routeLabel(gptRow)).toBe('Runtime · Responses · Global CRIS');
    expect(routeLabel({ input_price_per_1m: '1', output_price_per_1m: '1' })).toBeNull();
  });

  it('shows explicit cache capability independently of cache prices', () => {
    expect(promptCacheBadges(gptRow).map((b) => b.label)).toEqual([
      'Explicit: Image/Text',
      'Implicit',
    ]);

    const astraRuntime: PricingDisplayRecord = {
      ...gptRow,
      prompt_cache: {
        implicit: true,
        explicit: false,
        explicit_content_types: [],
        max_breakpoints: null,
        min_prefix_tokens: null,
        ttl: null,
      },
    };
    // Cache prices are present, but explicit caching is still unsupported.
    expect(astraRuntime.cache_write_price_per_1m).toBe('5.5');
    expect(promptCacheBadges(astraRuntime)[0]!.label).toBe('Explicit: ✕');
  });
});

describe('modelCardCheckBadge', () => {
  const base = { input_price_per_1m: '1', output_price_per_1m: '2' };

  it('shows nothing when the card matches or was never checked', () => {
    expect(modelCardCheckBadge(base)).toBeNull();
    expect(
      modelCardCheckBadge({
        ...base,
        model_card_check: { status: 'ok', issues: [], checked_at: '2026-10-22T02:15:00' },
      }),
    ).toBeNull();
  });

  it('flags drift with the differences in the tooltip', () => {
    const badge = modelCardCheckBadge({
      ...base,
      model_card_check: {
        status: 'mismatch',
        issues: ['standard short-context global input: catalog $2, card $2.2'],
        checked_at: '2026-10-22T02:15:00',
      },
    });
    expect(badge?.label).toBe('Card drift');
    expect(badge?.color).toBe('negative');
    expect(badge?.tooltip).toContain('checked 2026-10-22');
    expect(badge?.tooltip).toContain('catalog $2, card $2.2');
  });

  it('flags an unreadable card as a warning', () => {
    const badge = modelCardCheckBadge({
      ...base,
      model_card_check: { status: 'parse_error', issues: ['x'], checked_at: null },
    });
    expect(badge?.label).toBe('Card unreadable');
    expect(badge?.color).toBe('warning');
  });
});
