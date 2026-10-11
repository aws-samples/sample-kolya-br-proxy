import { describe, expect, it } from 'vitest';

import { calculateRemainingLifetimeBalance, formatCostUsd } from '@/utils/balance';

describe('calculateRemainingLifetimeBalance', () => {
  it('sums active standalone lifetime remaining quota', () => {
    const tokens = [
      {
        quota_usd: '5500.00',
        remaining_quota: '842.38',
        is_active: true,
        is_expired: false,
        team_id: null,
      },
      {
        quota_usd: '25.00',
        remaining_quota: '12.00',
        is_active: true,
        is_expired: false,
        team_id: null,
      },
      {
        quota_usd: null,
        remaining_quota: null,
        is_active: true,
        is_expired: false,
        team_id: 'team-1',
      },
    ];

    expect(calculateRemainingLifetimeBalance(tokens)).toBe('854.38');
  });

  it('uses per-key clamped remaining values instead of cross-key subtraction', () => {
    const tokens = [
      {
        quota_usd: '10.00',
        remaining_quota: '0.00',
        is_active: true,
        is_expired: false,
        team_id: null,
      },
      {
        quota_usd: '10.00',
        remaining_quota: '10.00',
        is_active: true,
        is_expired: false,
        team_id: null,
      },
    ];

    expect(calculateRemainingLifetimeBalance(tokens)).toBe('10.00');
  });

  it('excludes inactive, expired, team, and non-lifetime tokens', () => {
    const tokens = [
      {
        quota_usd: '10.00',
        remaining_quota: '10.00',
        is_active: false,
        is_expired: false,
        team_id: null,
      },
      {
        quota_usd: '10.00',
        remaining_quota: '10.00',
        is_active: true,
        is_expired: true,
        team_id: null,
      },
      {
        quota_usd: '10.00',
        remaining_quota: '10.00',
        is_active: true,
        is_expired: false,
        team_id: 'team-1',
      },
      {
        quota_usd: null,
        remaining_quota: null,
        is_active: true,
        is_expired: false,
        team_id: null,
      },
    ];

    expect(calculateRemainingLifetimeBalance(tokens)).toBe('0.00');
  });

  it('rounds backend four-decimal amounts without floating-point loss', () => {
    const tokens = [
      {
        quota_usd: '1.00',
        remaining_quota: '0.1050',
        is_active: true,
        is_expired: false,
        team_id: null,
      },
    ];

    expect(calculateRemainingLifetimeBalance(tokens)).toBe('0.11');
  });

  it('accepts ten-decimal amounts from numeric(20, 10) usage costs', () => {
    const tokens = [
      {
        quota_usd: '25.00',
        remaining_quota: '24.9999986500',
        is_active: true,
        is_expired: false,
        team_id: null,
      },
      {
        quota_usd: '1.00',
        remaining_quota: '0.0049999999',
        is_active: true,
        is_expired: false,
        team_id: null,
      },
    ];

    // 24.99999865 + 0.0049999999 = 25.0049986499 -> rounds to 25.00
    expect(calculateRemainingLifetimeBalance(tokens)).toBe('25.00');
  });

  it('sums sub-cent amounts exactly before rounding to cents', () => {
    const tokens = Array.from({ length: 3 }, () => ({
      quota_usd: '1.00',
      remaining_quota: '0.0016666667',
      is_active: true,
      is_expired: false,
      team_id: null,
    }));

    // 3 x 0.0016666667 = 0.0050000001 -> rounds half-up to 0.01
    expect(calculateRemainingLifetimeBalance(tokens)).toBe('0.01');
  });
});

describe('formatCostUsd', () => {
  it('rounds ten-decimal backend costs to four decimals for display', () => {
    expect(formatCostUsd('12.3456789012')).toBe('12.3457');
    expect(formatCostUsd('0.0000013500')).toBe('0.0000');
    expect(formatCostUsd('0.00005')).toBe('0.0001');
  });

  it('keeps legacy four-decimal strings and supports other precisions', () => {
    expect(formatCostUsd('1.2345')).toBe('1.2345');
    expect(formatCostUsd('1.005', 2)).toBe('1.01');
    expect(formatCostUsd('-0.00004')).toBe('0.0000');
    expect(formatCostUsd('-2.5')).toBe('-2.5000');
  });

  it('falls back to the raw value when it is not a decimal string', () => {
    expect(formatCostUsd(null)).toBe('0.0000');
    expect(formatCostUsd('n/a')).toBe('n/a');
  });
});
