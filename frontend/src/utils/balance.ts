export interface LifetimeBalanceToken {
  quota_usd: string | null;
  remaining_quota: string | null;
  is_active: boolean;
  is_expired: boolean;
  team_id?: string | null;
}

// Matches the backend usage_records.cost_usd Numeric(20, 10) scale, so
// remaining quotas derived from summed costs parse without loss.
const SCALE_DIGITS = 10;
const INTERNAL_SCALE = 10n ** BigInt(SCALE_DIGITS);
const UNITS_PER_CENT = INTERNAL_SCALE / 100n;

function parseUsdUnits(value: string): bigint {
  const match = /^([+-]?)(\d+)(?:\.(\d*))?$/.exec(value.trim());
  if (!match) {
    throw new Error(`Invalid USD amount: ${value}`);
  }

  const sign = match[1] === '-' ? -1n : 1n;
  const whole = BigInt(match[2] ?? '0');
  const digits = match[3] ?? '';
  let fraction = BigInt(digits.slice(0, SCALE_DIGITS).padEnd(SCALE_DIGITS, '0'));
  // Round half-up any digits beyond the internal scale.
  if ((digits[SCALE_DIGITS] ?? '0') >= '5') {
    fraction += 1n;
  }
  return sign * (whole * INTERNAL_SCALE + fraction);
}

function formatUsd(units: bigint): string {
  const nonNegativeUnits = units > 0n ? units : 0n;
  const cents = (nonNegativeUnits + UNITS_PER_CENT / 2n) / UNITS_PER_CENT;
  const dollars = cents / 100n;
  const remainder = (cents % 100n).toString().padStart(2, '0');
  return `${dollars}.${remainder}`;
}

/** Sum backend-clamped lifetime balances for usable standalone API keys. */
export function calculateRemainingLifetimeBalance(tokens: readonly LifetimeBalanceToken[]): string {
  const total = tokens.reduce((sum, token) => {
    if (
      !token.is_active ||
      token.is_expired ||
      token.team_id ||
      token.quota_usd === null ||
      token.remaining_quota === null
    ) {
      return sum;
    }

    const remaining = parseUsdUnits(token.remaining_quota);
    return sum + (remaining > 0n ? remaining : 0n);
  }, 0n);

  return formatUsd(total);
}

/**
 * Format a backend cost string (up to 10 decimals) for display, rounding
 * half-up to `fractionDigits` without floating-point error.
 */
export function formatCostUsd(value: string | null | undefined, fractionDigits = 4): string {
  let units: bigint;
  try {
    units = parseUsdUnits(value ?? '0');
  } catch {
    return String(value ?? '');
  }
  const step = 10n ** BigInt(SCALE_DIGITS - fractionDigits);
  const negative = units < 0n;
  const magnitude = negative ? -units : units;
  const rounded = (magnitude + step / 2n) / step;
  const divisor = 10n ** BigInt(fractionDigits);
  const whole = rounded / divisor;
  const fraction = (rounded % divisor).toString().padStart(fractionDigits, '0');
  const sign = negative && rounded > 0n ? '-' : '';
  return fractionDigits > 0 ? `${sign}${whole}.${fraction}` : `${sign}${whole}`;
}
