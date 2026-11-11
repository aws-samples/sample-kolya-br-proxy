import { defineBoot } from '#q-app';
import axios, { type AxiosInstance } from 'axios';
import { Notify } from 'quasar';
import { clearAccessToken, getAccessToken, setAccessToken } from '@/auth/credential';

declare module 'vue' {
  interface ComponentCustomProperties {
    $axios: AxiosInstance;
    $api: AxiosInstance;
  }
}

// Extend Axios config to include retry count and auth flags
declare module 'axios' {
  interface InternalAxiosRequestConfig {
    __retryCount?: number;
    _retry?: boolean;
    _skipAuthRefresh?: boolean;
  }
}

// Get API base URL from environment variable
const apiBaseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// Create axios instance with optimized settings
const api = axios.create({
  baseURL: apiBaseURL,
  timeout: 3600000, // 1 hour for long-running tasks
  withCredentials: true, // Send HttpOnly cookies for cross-origin auth requests
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest', // CSRF protection for browser requests
  },
});

// Add request interceptor to attach Authorization header
api.interceptors.request.use(
  (config) => {
    const token = getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: unknown) => {
    return Promise.reject(error instanceof Error ? error : new Error(String(error)));
  },
);

// Shared state for token refresh deduplication.
// When multiple requests get 401 at the same time, only one refresh
// request is sent; the others queue up and reuse its result.
let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];
let refreshRejectSubscribers: ((err: Error) => void)[] = [];

function onRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
  refreshRejectSubscribers = [];
}

function onRefreshFailed(err: Error) {
  refreshRejectSubscribers.forEach((cb) => cb(err));
  refreshSubscribers = [];
  refreshRejectSubscribers = [];
}

function waitForRefresh(): Promise<string> {
  return new Promise((resolve, reject) => {
    refreshSubscribers.push(resolve);
    refreshRejectSubscribers.push(reject);
  });
}

// Add response interceptor for retry logic and auth handling
// HTTP methods safe to retry automatically. Retrying a write on a 5xx can
// apply it twice if the server committed before failing.
const RETRYABLE_METHODS = new Set(['get', 'head', 'options']);

/**
 * The backend wraps errors as {"error": {"message": ...}}, but callers across
 * the app read `response.data.detail`. Mirror the message into `detail` so every
 * caller sees the real reason instead of a generic fallback.
 */
function normalizeErrorDetail(error: {
  response?: { data?: { detail?: unknown; error?: { message?: unknown } } };
}): void {
  const data = error.response?.data;
  if (data && typeof data === 'object' && data.detail === undefined) {
    const message = data.error?.message;
    if (typeof message === 'string' && message) {
      data.detail = message;
    }
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;
    normalizeErrorDetail(error);

    // Handle 401 Unauthorized - Token expired
    if (error.response?.status === 401) {
      // Skip refresh for refresh token requests to prevent infinite loop
      if (config._skipAuthRefresh) {
        // A silent session restore (page load) just reports "no session".
        if (config._silent) {
          return Promise.reject(error as Error);
        }
        Notify.create({
          type: 'warning',
          message: 'Session expired, please login again',
          position: 'top',
        });
        // Clear auth state and redirect
        clearAccessToken();
        if (typeof window !== 'undefined') {
          window.location.assign('/login');
        }
        return Promise.reject(new Error('Authentication failed'));
      }

      // If not already retried, try to refresh token
      if (!config._retry) {
        config._retry = true;

        // If another request is already refreshing, queue this one
        if (isRefreshing) {
          try {
            const newToken = await waitForRefresh();
            config.headers['Authorization'] = `Bearer ${newToken}`;
            return api(config);
          } catch {
            return Promise.reject(new Error('Token refresh failed'));
          }
        }

        isRefreshing = true;

        try {
          // Try to refresh the token (cookie sent automatically via withCredentials)
          const response = await api.post('/admin/auth/refresh', {}, {
            _skipAuthRefresh: true,
          } as Record<string, unknown>);

          const { access_token } = response.data;

          // Keep the new access token in memory only
          setAccessToken(access_token);

          // Update authorization header
          api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
          config.headers['Authorization'] = `Bearer ${access_token}`;

          // Notify queued requests
          onRefreshed(access_token);

          // Retry original request
          return api(config);
        } catch (refreshError) {
          const err =
            refreshError instanceof Error ? refreshError : new Error('Token refresh failed');
          onRefreshFailed(err);

          // Refresh failed, redirect to login
          Notify.create({
            type: 'warning',
            message: 'Session expired, please login again',
            position: 'top',
          });
          clearAccessToken();
          if (typeof window !== 'undefined') {
            window.location.assign('/login');
          }
          return Promise.reject(err);
        } finally {
          isRefreshing = false;
        }
      }
    }

    // Handle 403 Forbidden - only logout for inactive user, otherwise just reject
    if (error.response?.status === 403) {
      const detail = error.response?.data?.detail || '';
      if (detail === 'Inactive user') {
        clearAccessToken();
        if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
          window.location.assign('/login');
        }
      }
      return Promise.reject(error as Error);
    }

    // Handle 5xx errors and network errors with retry logic
    if (!config.__retryCount) {
      config.__retryCount = 0;
    }

    const maxRetries = 2;
    const isServerError = error.response?.status >= 500;
    const isNetworkError = !error.response; // No response = server unreachable
    const isRetryableMethod = RETRYABLE_METHODS.has((config.method || 'get').toLowerCase());
    const shouldRetry =
      isRetryableMethod && config.__retryCount < maxRetries && (isServerError || isNetworkError);

    if (shouldRetry) {
      config.__retryCount += 1;
      const delay = Math.pow(2, config.__retryCount - 1) * 1000;
      await new Promise((resolve) => setTimeout(resolve, delay));
      return api(config);
    }

    // Reject with the original AxiosError (an Error subclass) so callers keep
    // access to `response` and can show the server's message.
    return Promise.reject(error as Error);
  },
);

export default defineBoot(({ app }) => {
  // Make axios available globally
  app.config.globalProperties.$axios = axios;
  app.config.globalProperties.$api = api;
});

export { api };
