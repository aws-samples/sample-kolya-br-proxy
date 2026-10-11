import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  notifyCreate: vi.fn(),
}));

vi.mock('@/boot/axios', () => ({ api: { get: mocks.apiGet } }));
vi.mock('quasar', () => ({ Notify: { create: mocks.notifyCreate } }));

import { useTokensStore } from '@/stores/tokens';

const token = {
  id: 'token-1',
  name: 'one',
  description: null,
  key_prefix: 'kbp_',
  expires_at: null,
  quota_usd: '10.00',
  used_usd: '1.00',
  remaining_quota: '9.00',
  allowed_ips: [],
  notify_emails: [],
  allowed_models: [],
  is_active: true,
  is_expired: false,
  is_quota_exceeded: false,
  created_at: '2026-01-01T00:00:00Z',
  last_used_at: null,
};

describe('tokens store refresh state', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    mocks.apiGet.mockReset();
    mocks.notifyCreate.mockReset();
  });

  it('force-refreshes even when cached tokens exist', async () => {
    const store = useTokensStore();
    store.tokens = [token];
    mocks.apiGet.mockResolvedValue({ data: [{ ...token, remaining_quota: '8.00' }] });

    await expect(store.fetchTokens(false, true)).resolves.toBe(true);

    expect(mocks.apiGet).toHaveBeenCalledWith('/admin/tokens', {
      params: { include_inactive: false },
    });
    expect(store.tokens[0]?.remaining_quota).toBe('8.00');
    expect(store.lastFetchedAt).not.toBeNull();
    expect(store.error).toBeNull();
  });

  it('keeps a failed refresh distinct from a real zero balance', async () => {
    const store = useTokensStore();
    mocks.apiGet.mockRejectedValue({
      response: { status: 500, data: { detail: 'Quota unavailable' } },
    });

    await expect(store.fetchTokens(false, true)).resolves.toBe(false);

    expect(store.error).toBe('Quota unavailable');
    expect(store.lastFetchedAt).toBeNull();
    expect(mocks.notifyCreate).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'negative', message: 'Quota unavailable' }),
    );
  });
});
