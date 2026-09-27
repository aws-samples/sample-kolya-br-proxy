import { config, flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

config.global.renderStubDefaultSlot = true;

const stores = vi.hoisted(() => ({
  canManageApiKeys: false,
  tokens: {
    tokens: [],
    loading: false,
    loaded: true,
    error: null as string | null,
    lastFetchedAt: null as string | null,
    fetchTokens: vi.fn().mockResolvedValue(true),
  },
  dashboard: {
    usageByToken: [],
    usageByModel: [],
    loading: false,
    fetchUsageByToken: vi.fn(),
    fetchUsageByModel: vi.fn(),
  },
  auth: {
    user: {},
    isSuperAdmin: false,
    initializeAuth: vi.fn(),
    hasPermission: vi.fn((permission: string) =>
      permission === 'manage_api_keys' ? stores.canManageApiKeys : false,
    ),
  },
}));

vi.mock('src/stores/tokens', () => ({ useTokensStore: () => stores.tokens }));
vi.mock('src/stores/dashboard', () => ({ useDashboardStore: () => stores.dashboard }));
vi.mock('src/stores/auth', () => ({ useAuthStore: () => stores.auth }));
vi.mock('src/boot/axios', () => ({ api: { get: vi.fn() } }));
vi.mock('src/utils/api', () => ({ getApiBaseUrl: () => 'http://localhost' }));

import DashboardPage from 'src/pages/DashboardPage.vue';

describe('Dashboard lifetime balance card', () => {
  beforeEach(() => {
    stores.canManageApiKeys = false;
    stores.tokens.error = null;
    stores.tokens.fetchTokens.mockClear();
    stores.auth.hasPermission.mockClear();
  });

  it('hides the card when the user cannot manage API keys', async () => {
    const wrapper = shallowMount(DashboardPage);
    await flushPromises();

    expect(wrapper.text()).not.toContain('Remaining Lifetime Quota');
    expect(stores.tokens.fetchTokens).not.toHaveBeenCalled();
  });

  it('force-refreshes on entry and renders failure instead of $0.00', async () => {
    stores.canManageApiKeys = true;
    stores.tokens.error = 'Quota unavailable';

    const wrapper = shallowMount(DashboardPage);
    await flushPromises();

    expect(stores.tokens.fetchTokens).toHaveBeenCalledWith(false, true);
    expect(wrapper.text()).toContain('Remaining Lifetime Quota');
    expect(wrapper.text()).toContain('Quota unavailable. Refresh to try again.');
    expect(wrapper.text()).not.toContain('$0.00');
  });
});
