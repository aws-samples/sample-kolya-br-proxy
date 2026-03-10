import { defineStore } from 'pinia';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';

export interface APIToken {
  id: string;
  name: string;
  expires_at: string | null;
  quota_usd: string | null;
  used_usd: string;
  remaining_quota: string | null;
  allowed_ips: string[];
  allowed_models: string[];
  is_active: boolean;
  is_expired: boolean;
  is_quota_exceeded: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface APITokenWithKey extends APIToken {
  token: string;
}

export interface CreateTokenRequest {
  name: string;
  expires_at?: string;
  quota_usd?: number;
  allowed_ips?: string[];
  allowed_models?: string[];
}

export const useTokensStore = defineStore('tokens', {
  state: () => ({
    tokens: [] as APIToken[],
    loading: false,
  }),

  actions: {
    async fetchTokens(includeInactive = false, force = false) {
      // Return cached data if available and not forcing refresh
      if (this.tokens.length > 0 && !force) {
        return;
      }

      this.loading = true;
      try {
        const response = await api.get<APIToken[]>('/admin/tokens', {
          params: { include_inactive: includeInactive },
        });
        this.tokens = response.data;
      } catch (error: unknown) {
        // Check if it's an authentication error
        if (error && typeof error === 'object' && 'response' in error) {
          const response = error.response as { status?: number; data?: { detail?: string } };
          if (response?.status === 401) {
            // Auth error will be handled by axios interceptor
            return;
          }
          const message = response?.data?.detail || 'Failed to fetch token list';
          Notify.create({
            type: 'negative',
            message,
            position: 'top',
          });
        } else {
          Notify.create({
            type: 'negative',
            message: 'Failed to fetch token list',
            position: 'top',
          });
        }
      } finally {
        this.loading = false;
      }
    },

    async createToken(data: CreateTokenRequest): Promise<APITokenWithKey | null> {
      try {
        const response = await api.post<APITokenWithKey>('/admin/tokens', data);

        Notify.create({
          type: 'positive',
          message: 'Token created successfully',
          position: 'top',
        });

        await this.fetchTokens(false, true);
        return response.data;
      } catch (error: unknown) {
        const message = error && typeof error === 'object' && 'response' in error
          ? (error.response as { data?: { detail?: string } })?.data?.detail || 'Failed to create token'
          : 'Failed to create token';
        Notify.create({
          type: 'negative',
          message,
          position: 'top',
        });
        return null;
      }
    },

    async updateToken(tokenId: string, data: Partial<CreateTokenRequest>, showNotification = false) {
      try {
        await api.put(`/admin/tokens/${tokenId}`, data);

        if (showNotification) {
          Notify.create({
            type: 'positive',
            message: 'Token updated successfully',
            position: 'top',
          });
        }

        await this.fetchTokens(false, true);
        return true;
      } catch (error: unknown) {
        const message = error && typeof error === 'object' && 'response' in error
          ? (error.response as { data?: { detail?: string } })?.data?.detail || 'Failed to update token'
          : 'Failed to update token';
        Notify.create({
          type: 'negative',
          message,
          position: 'top',
        });
        return false;
      }
    },

    async deleteToken(tokenId: string) {
      try {
        await api.delete(`/admin/tokens/${tokenId}`);

        Notify.create({
          type: 'positive',
          message: 'Token deleted successfully',
          position: 'top',
        });

        await this.fetchTokens(false, true);
        return true;
      } catch (error: unknown) {
        const message = error && typeof error === 'object' && 'response' in error
          ? (error.response as { data?: { detail?: string } })?.data?.detail || 'Failed to delete token'
          : 'Failed to delete token';
        Notify.create({
          type: 'negative',
          message,
          position: 'top',
        });
        return false;
      }
    },

    async revokeToken(tokenId: string) {
      try {
        await api.post(`/admin/tokens/${tokenId}/revoke`);

        Notify.create({
          type: 'positive',
          message: 'Token revoked',
          position: 'top',
        });

        await this.fetchTokens(false, true);
        return true;
      } catch (error: unknown) {
        const message = error && typeof error === 'object' && 'response' in error
          ? (error.response as { data?: { detail?: string } })?.data?.detail || 'Failed to revoke token'
          : 'Failed to revoke token';
        Notify.create({
          type: 'negative',
          message,
          position: 'top',
        });
        return false;
      }
    },
  },
});
