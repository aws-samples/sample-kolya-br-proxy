import { beforeEach, describe, expect, it, vi } from 'vitest';

import createAppRouter from '@/router';

describe('application router history', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/auth/cognito/callback?code=synthetic&state=synthetic');
    vi.stubEnv('QUASAR_SERVER', '');
    vi.stubEnv('QUASAR_VUE_ROUTER_MODE', 'history');
    vi.stubEnv('QUASAR_VUE_ROUTER_BASE', '/');
  });

  it('recognizes an OAuth callback URL without falling back to hash routing', async () => {
    const router = await createAppRouter({} as never);

    expect(router.options.history.location).toBe(
      '/auth/cognito/callback?code=synthetic&state=synthetic',
    );
    expect(router.resolve(router.options.history.location).matched[0]?.path).toBe(
      '/auth/cognito/callback',
    );
  });
});
