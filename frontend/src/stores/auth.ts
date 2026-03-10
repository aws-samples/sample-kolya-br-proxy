import { defineStore } from 'pinia';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';

export interface User {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  email_verified: boolean;
  current_balance: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    accessToken: localStorage.getItem('access_token') || null,
    refreshToken: localStorage.getItem('refresh_token') || null,
    isAuthenticated: false,
  }),

  getters: {
    isLoggedIn: (state) => state.isAuthenticated && !!state.accessToken,
    currentUser: (state) => state.user,
    isAdmin: (state) => state.user?.is_admin || false,
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
            this.logout(false);
            return;
          }
        }
        // Other errors (network errors, etc.), don't logout, just log error
        console.error('Failed to fetch current user:', error);
      }
    },

    async refreshAccessToken() {
      if (!this.refreshToken) {
        Notify.create({
          type: 'warning',
          message: 'Session expired, please login again',
          position: 'top',
        });
        this.logout(false);
        return false;
      }

      try {
        const response = await api.post<LoginResponse>(
          '/admin/auth/refresh',
          {
            refresh_token: this.refreshToken,
          },
          {
            // Skip interceptor to prevent infinite loop
            _skipAuthRefresh: true,
          } as Record<string, unknown>
        );

        const { access_token, refresh_token } = response.data;

        this.accessToken = access_token;
        this.refreshToken = refresh_token;

        localStorage.setItem('access_token', access_token);
        localStorage.setItem('refresh_token', refresh_token);

        api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;

        return true;
      } catch {
        Notify.create({
          type: 'warning',
          message: 'Session expired, please login again',
          position: 'top',
        });
        this.logout(false);
        return false;
      }
    },

    logout(showNotification = true) {
      this.user = null;
      this.accessToken = null;
      this.refreshToken = null;
      this.isAuthenticated = false;

      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');

      delete api.defaults.headers.common['Authorization'];

      if (showNotification) {
        Notify.create({
          type: 'info',
          message: 'Logged out',
          position: 'top',
        });
      }

      // Redirect to login page using window.location to ensure clean state
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
    },

    async initializeAuth() {
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
