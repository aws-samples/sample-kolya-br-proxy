/**
 * The admin access token lives in memory only.
 *
 * Anything in localStorage is readable by any script that runs on the page,
 * so an XSS bug would hand over the session. The long-lived refresh token is
 * already an HttpOnly cookie the page can't read; the short-lived access
 * token now stays in this module, and a page load restores it from that
 * cookie via POST /admin/auth/refresh.
 */

let accessToken: string | null = null;

// Earlier builds kept the token in localStorage; never leave it behind.
try {
  localStorage.removeItem('access_token');
} catch {
  // storage unavailable (private mode) - nothing to clean up
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}

let restoring: Promise<boolean> | null = null;

function isConcurrentRefresh(error: unknown): boolean {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  return typeof detail === 'string' && detail.startsWith('Concurrent refresh');
}

/**
 * Get a fresh access token from the refresh cookie. Concurrent callers share
 * one request. The backend rejects a refresh token reused within its grace
 * window (another tab rotated it a moment ago) without revoking the session,
 * so one retry after a short pause picks up the rotated cookie.
 */
export function restoreSession(
  refresh: () => Promise<string>,
): Promise<boolean> {
  if (!restoring) {
    restoring = (async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          setAccessToken(await refresh());
          return true;
        } catch (error) {
          if (attempt > 0 || !isConcurrentRefresh(error)) break;
          await new Promise((r) => setTimeout(r, 600));
        }
      }
      clearAccessToken();
      return false;
    })().finally(() => {
      restoring = null;
    });
  }
  return restoring;
}
