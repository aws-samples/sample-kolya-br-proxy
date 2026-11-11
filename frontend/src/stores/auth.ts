import { defineStore } from 'pinia';
import { api } from '@/boot/axios';
import { Notify } from 'quasar';
import { clearAccessToken, getAccessToken, restoreSession, setAccessToken } from '@/auth/credential';

export interface User {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  role?: 'super_admin' | 'admin' | 'viewer';
  permissions?: Record<string, boolean | string | string[]> | null;
  email_verified: boolean;
  current_balance: string;
  group_sync_enabled?: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}


export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    accessToken: null as string | null,
    isAuthenticated: false,
  }),

  getters: {
    isLoggedIn: (state) => state.isAuthenticated && Boolean(state.accessToken),
    currentUser: (state) => state.user,
    isAdmin: (state) => state.user?.is_admin || false,
    isSuperAdmin: (state) => state.user?.role === 'super_admin',
    // Viewer: read-only access to every page; no writes, no plaintext keys.
    // The backend enforces this; these getters only shape the UI.
    isViewer: (state) => state.user?.role === 'viewer',
    canWrite: (state) => Boolean(state.user) && state.user?.role !== 'viewer',
    canViewSuperAdminPages: (state) =>
      state.user?.role === 'super_admin' || state.user?.role === 'viewer',
    groupSyncEnabled: (state) => state.user?.group_sync_enabled || false,
    hasPermission: (state) => (permission: string) => {
      if (!state.user) return false;
      if (state.user.role === 'super_admin' || state.user.role === 'viewer') return true;
      if (!state.user.permissions || Object.keys(state.user.permissions).length === 0) return true;
      const val = state.user.permissions[permission];
      if (val === 'all' || val === true) return true;
      if (Array.isArray(val) && val.length > 0) return true;
      return false;
    },
  },

  actions: {
    async fetchCurrentUser() {
      if (!this.accessToken) return;

      try {
        const response = await api.get<User>('/admin/auth/me', {
          headers: {
            Authorization: `Bearer ${this.accessToken}`,
          },
        });

        this.user = response.data;
        this.isAuthenticated = true;
      } catch (error: unknown) {
        // If 401 error, try to refresh token
        if (error && typeof error === 'object' && 'response' in error) {
          const response = error.response as { status?: number };
          if (response?.status === 401) {
            const refreshed = await this.refreshAccessToken();
            if (refreshed) {
              // Refresh successful, fetch user info again
              await this.fetchCurrentUser();
              return;
            }
            // Refresh failed, logout and redirect
            Notify.create({
              type: 'warning',
              message: 'Session expired, please login again',
              position: 'top',
            });
            void this.logoutSilently();
            return;
          }
        }
        // Other errors (network errors, etc.), don't logout, just log error
        console.error('Failed to fetch current user:', error);
      }
    },

    async refreshAccessToken() {
      try {
        // Cookie is sent automatically via withCredentials
        const response = await api.post<LoginResponse>('/admin/auth/refresh', {}, {
          // Skip interceptor to prevent infinite loop
          _skipAuthRefresh: true,
        } as Record<string, unknown>);

        const { access_token } = response.data;

        this.accessToken = access_token;
        setAccessToken(access_token);
        api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;

        return true;
      } catch {
        Notify.create({
          type: 'warning',
          message: 'Session expired, please login again',
          position: 'top',
        });
        void this.logoutSilently();
        return false;
      }
    },

    async revokeAndClearSession() {
      // Revoke refresh token on server (clears cookie server-side)
      try {
        await api.post('/admin/auth/revoke', {});
      } catch {
        // Ignore errors during logout
      }

      this.user = null;
      this.accessToken = null;
      this.isAuthenticated = false;

      clearAccessToken();

      delete api.defaults.headers.common['Authorization'];
    },

    redirectToLogin() {
      // Use a full navigation to ensure no authenticated state survives.
      if (typeof window !== 'undefined') {
        window.location.assign('/login');
      }
    },

    async logout() {
      await this.revokeAndClearSession();
      Notify.create({
        type: 'info',
        message: 'Logged out',
        position: 'top',
      });
      this.redirectToLogin();
    },

    async logoutSilently() {
      await this.revokeAndClearSession();
      this.redirectToLogin();
    },

    async initializeAuth() {
      // The access token is memory-only, so a fresh page load has none:
      // restore it from the HttpOnly refresh cookie.
      if (!this.accessToken) {
        this.accessToken = getAccessToken();
      }
      if (!this.accessToken) {
        const restored = await restoreSession(async () => {
          const response = await api.post<LoginResponse>('/admin/auth/refresh', {}, {
            _skipAuthRefresh: true,
            _silent: true,
          } as Record<string, unknown>);
          return response.data.access_token;
        });
        if (restored) this.accessToken = getAccessToken();
      }

      if (this.accessToken) {
        api.defaults.headers.common['Authorization'] = `Bearer ${this.accessToken}`;
        await this.fetchCurrentUser();
      }
    },

    updateUser(user: User) {
      this.user = user;
    },
  },
});
