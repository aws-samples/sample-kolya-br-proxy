/**
 * Presentation helpers for the admin pricing table.
 *
 * GPT rows carry both context bands, cache write/read prices, the resolved
 * route, and an explicit prompt-cache capability that is independent of the
 * cache prices (a cache price never implies explicit-cache support).
 */

export interface PricingTier {
  label: string;
  max_input_tokens: number | null;
  input_price_per_1m: string | null;
  cache_write_price_per_1m: string | null;
  cache_read_price_per_1m: string | null;
  output_price_per_1m: string | null;
}

export interface PromptCacheInfo {
  implicit: boolean;
  explicit: boolean;
  explicit_content_types: string[];
  max_breakpoints: number | null;
  min_prefix_tokens: number | null;
  ttl: string | null;
}

export interface PricingDisplayRecord {
  input_price_per_1m: string;
  output_price_per_1m: string;
  cache_write_price_per_1m?: string | null;
  cache_read_price_per_1m?: string | null;
  context_tiers?: PricingTier[] | null;
  endpoint_family?: 'mantle' | 'runtime' | null;
  api?: string | null;
  scope?: 'in-region' | 'us' | 'global' | null;
  prompt_cache?: PromptCacheInfo | null;
}

export interface CacheBadge {
  label: string;
  color: string;
  tooltip: string;
}

/** Context bands to render; non-tiered rows become a single "All" band. */
export function pricingTiers(record: PricingDisplayRecord): PricingTier[] {
  if (record.context_tiers && record.context_tiers.length > 0) {
    return record.context_tiers;
  }
  return [
    {
      label: 'All',
      max_input_tokens: null,
      input_price_per_1m: record.input_price_per_1m,
      cache_write_price_per_1m: record.cache_write_price_per_1m ?? null,
      cache_read_price_per_1m: record.cache_read_price_per_1m ?? null,
      output_price_per_1m: record.output_price_per_1m,
    },
  ];
}

/** Format a per-1M price; "—" when AWS publishes no price for the dimension. */
export function formatPrice(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (n === 0) return '$0.00';
  const decimals = n < 0.1 ? 4 : 2;
  return '$' + n.toFixed(decimals);
}

const ENDPOINT_LABELS: Record<string, string> = {
  mantle: 'Mantle',
  runtime: 'Runtime',
};

const SCOPE_LABELS: Record<string, string> = {
  'in-region': 'In-Region',
  us: 'US CRIS',
  global: 'Global CRIS',
};

/** e.g. "Runtime · Responses · Global CRIS"; null for non-catalogued rows. */
export function routeLabel(record: PricingDisplayRecord): string | null {
  if (!record.endpoint_family) return null;
  const parts = [ENDPOINT_LABELS[record.endpoint_family] ?? record.endpoint_family];
  if (record.api) parts.push(record.api === 'responses' ? 'Responses' : record.api);
  if (record.scope) parts.push(SCOPE_LABELS[record.scope] ?? record.scope);
  return parts.join(' · ');
}

const CONTENT_LABELS: Record<string, string> = {
  input_text: 'Text',
  input_image: 'Image',
  input_file: 'File',
};

/** Capability badges; empty for rows without catalogued cache capability. */
export function promptCacheBadges(record: PricingDisplayRecord): CacheBadge[] {
  const cache = record.prompt_cache;
  if (!cache) return [];
  const badges: CacheBadge[] = [];
  if (cache.explicit) {
    const types = cache.explicit_content_types.map((t) => CONTENT_LABELS[t] ?? t).join('/');
    badges.push({
      label: `Explicit: ${types}`,
      color: 'positive',
      tooltip:
        `cache_control → prompt_cache_breakpoint on ${types}; ` +
        `max ${cache.max_breakpoints} breakpoints, ` +
        `≥${cache.min_prefix_tokens} token prefix, TTL ${cache.ttl}`,
    });
  } else {
    badges.push({
      label: 'Explicit: ✕',
      color: 'grey-7',
      tooltip: 'Explicit cache markers are rejected with a 4xx for this route',
    });
  }
  if (cache.implicit) {
    badges.push({
      label: 'Implicit',
      color: 'blue-grey-6',
      tooltip: 'Requests without markers use automatic prompt caching',
    });
  }
  return badges;
}
