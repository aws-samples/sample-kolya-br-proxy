import { boot } from 'quasar/wrappers';
import axios, { type AxiosInstance } from 'axios';
import { Notify } from 'quasar';

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
  timeout: 900000, // 15 minutes for long-running tasks
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest', // CSRF protection for browser requests
  },
});

// Add request interceptor to attach Authorization header
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: unknown) => {
    return Promise.reject(error instanceof Error ? error : new Error(String(error)));
  }
);

// Add response interceptor for retry logic and auth handling
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;

    // Handle 401 Unauthorized - Token expired
    if (error.response?.status === 401) {
      // Skip refresh for refresh token requests to prevent infinite loop
      if (config._skipAuthRefresh) {
        Notify.create({
          type: 'warning',
          message: 'Session expired, please login again',
          position: 'top',
        });
        // Clear auth state and redirect
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        return Promise.reject(new Error('Authentication failed'));
      }

      // If not already retried, try to refresh token
      if (!config._retry) {
        config._retry = true;

        const refreshToken = localStorage.getItem('refresh_token');

        if (!refreshToken) {
          Notify.create({
            type: 'warning',
            message: 'Session expired, please login again',
            position: 'top',
          });
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          if (typeof window !== 'undefined') {
            window.location.href = '/login';
          }
          return Promise.reject(new Error('No refresh token'));
        }

        try {
          // Try to refresh the token
          const response = await api.post(
            '/admin/auth/refresh',
            { refresh_token: refreshToken },
            { _skipAuthRefresh: true } as Record<string, unknown>
          );

          const { access_token, refresh_token } = response.data;

          // Save new tokens
          localStorage.setItem('access_token', access_token);
          localStorage.setItem('refresh_token', refresh_token);

          // Update authorization header
          api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
          config.headers['Authorization'] = `Bearer ${access_token}`;

          // Retry original request
          return api(config);
        } catch (refreshError) {
          // Refresh failed, redirect to login
          Notify.create({
            type: 'warning',
            message: 'Session expired, please login again',
            position: 'top',
          });
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          if (typeof window !== 'undefined') {
            window.location.href = '/login';
          }
          return Promise.reject(
            refreshError instanceof Error ? refreshError : new Error('Token refresh failed')
          );
        }
      }
    }

    // Handle 403 Forbidden - treat as auth failure, redirect to login
    if (error.response?.status === 403) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
      return Promise.reject(new Error('Access denied'));
    }

    // Handle 5xx errors and network errors with retry logic
    if (!config.__retryCount) {
      config.__retryCount = 0;
    }

    const maxRetries = 2;
    const isServerError = error.response?.status >= 500;
    const isNetworkError = !error.response; // No response = server unreachable
    const shouldRetry =
      config.__retryCount < maxRetries &&
      (isServerError || isNetworkError);

    if (shouldRetry) {
      config.__retryCount += 1;
      const delay = Math.pow(2, config.__retryCount - 1) * 1000;
      await new Promise((resolve) => setTimeout(resolve, delay));
      return api(config);
    }

    return Promise.reject(new Error(error.message || 'Request failed'));
  }
);

export default boot(({ app }) => {
  // Make axios available globally
  app.config.globalProperties.$axios = axios;
  app.config.globalProperties.$api = api;
});

export { api };
