import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('in-memory access credential', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  it('removes a token an earlier build left in localStorage', async () => {
    localStorage.setItem('access_token', 'stale');
    await import('@/auth/credential');
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('never writes the token to storage', async () => {
    const { setAccessToken, getAccessToken } = await import('@/auth/credential');
    setAccessToken('t1');
    expect(getAccessToken()).toBe('t1');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('shares one refresh between concurrent restores', async () => {
    const { restoreSession, getAccessToken } = await import('@/auth/credential');
    const refresh = vi.fn().mockResolvedValue('fresh');
    const results = await Promise.all([restoreSession(refresh), restoreSession(refresh)]);
    expect(results).toEqual([true, true]);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe('fresh');
  });

  it('retries once when another tab rotated the cookie', async () => {
    const { restoreSession } = await import('@/auth/credential');
    const concurrent = { response: { data: { detail: 'Concurrent refresh detected, please retry' } } };
    const refresh = vi.fn().mockRejectedValueOnce(concurrent).mockResolvedValueOnce('fresh');
    await expect(restoreSession(refresh)).resolves.toBe(true);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it('does not retry when there is simply no session', async () => {
    const { restoreSession, getAccessToken } = await import('@/auth/credential');
    const refresh = vi.fn().mockRejectedValue({ response: { data: { detail: 'Missing refresh token' } } });
    await expect(restoreSession(refresh)).resolves.toBe(false);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });
});
