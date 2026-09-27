export interface LifetimeBalanceToken {
  quota_usd: string | null;
  remaining_quota: string | null;
  is_active: boolean;
  is_expired: boolean;
  team_id?: string | null;
}

const INTERNAL_SCALE = 10_000n;
const UNITS_PER_CENT = 100n;

function parseUsdUnits(value: string): bigint {
  const match = /^([+-]?)(\d+)(?:\.(\d{0,4}))?$/.exec(value.trim());
  if (!match) {
    throw new Error(`Invalid USD amount: ${value}`);
  }

  const sign = match[1] === '-' ? -1n : 1n;
  const whole = BigInt(match[2] ?? '0');
  const fraction = BigInt((match[3] ?? '').padEnd(4, '0'));
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
