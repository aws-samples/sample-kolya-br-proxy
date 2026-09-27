import { describe, expect, it } from 'vitest';

import { calculateRemainingLifetimeBalance } from 'src/utils/balance';

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
});
