import { defineStore } from 'pinia';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';

export interface UsageStats {
  current_month_cost: string;
  current_month_requests: number;
  current_month_tokens: number;
  last_30_days_cost: string;
  last_30_days_requests: number;
  total_cost: string;
  total_requests: number;
}

export interface UsageByToken {
  token_id: string;
  token_name: string;
  is_deleted: boolean;
  total_cost: string;
  total_requests: number;
  total_tokens: number;
}

export interface UsageByModel {
  model: string;
  total_cost: string;
  total_requests: number;
  total_tokens: number;
}

export const useDashboardStore = defineStore('dashboard', {
  state: () => ({
    usageStats: null as UsageStats | null,
    usageByToken: [] as UsageByToken[],
    usageByModel: [] as UsageByModel[],
    loading: false,
    // Cache query parameters
    lastTokenQuery: null as { token_id?: string; start_date?: string; end_date?: string } | null,
    lastModelQuery: null as { start_date?: string; end_date?: string } | null,
  }),

  actions: {
    async fetchUsageStats(force = false) {
      // Return cached data if available and not forcing refresh
      if (this.usageStats && !force) {
        return;
      }

      this.loading = true;
      try {
        const response = await api.get<UsageStats>('/admin/usage/stats');
        this.usageStats = response.data;
      } catch (error: unknown) {
        // Check if it's an authentication error
        if (error && typeof error === 'object' && 'response' in error) {
          const response = error.response as { status?: number; data?: { detail?: string } };
          if (response?.status === 401) {
            // Auth error will be handled by axios interceptor
            return;
          }
          const message = response?.data?.detail || 'Failed to fetch usage statistics';
          Notify.create({
            type: 'negative',
            message,
            position: 'top',
          });
        } else {
          Notify.create({
            type: 'negative',
            message: 'Failed to fetch usage statistics',
            position: 'top',
          });
        }
      } finally {
        this.loading = false;
      }
    },

    async fetchUsageByToken(params?: { token_id?: string; start_date?: string; end_date?: string }, force = false) {
      // Check if query parameters changed
      const paramsChanged = JSON.stringify(params) !== JSON.stringify(this.lastTokenQuery);

      // Return cached data if available, params unchanged, and not forcing refresh
      if (this.usageByToken.length > 0 && !paramsChanged && !force) {
        return;
      }

      this.loading = true;
      try {
        const response = await api.get<UsageByToken[]>('/admin/usage/by-token', { params });
        this.usageByToken = response.data || [];
        this.lastTokenQuery = params || null;
      } catch (error: unknown) {
        console.error('Failed to fetch usage by token:', error);
        this.usageByToken = [];
      } finally {
        this.loading = false;
      }
    },

    async fetchUsageByModel(params?: { start_date?: string; end_date?: string }, force = false) {
      // Check if query parameters changed
      const paramsChanged = JSON.stringify(params) !== JSON.stringify(this.lastModelQuery);

      // Return cached data if available, params unchanged, and not forcing refresh
      if (this.usageByModel.length > 0 && !paramsChanged && !force) {
        return;
      }

      this.loading = true;
      try {
        const response = await api.get<UsageByModel[]>('/admin/usage/by-model', { params });
        this.usageByModel = response.data || [];
        this.lastModelQuery = params || null;
      } catch (error: unknown) {
        console.error('Failed to fetch usage by model:', error);
        this.usageByModel = [];
      } finally {
        this.loading = false;
      }
    },

    async refreshAll() {
      await Promise.all([
        this.fetchUsageStats(true),
        this.fetchUsageByToken(this.lastTokenQuery || undefined, true),
        this.fetchUsageByModel(this.lastModelQuery || undefined, true),
      ]);
    },
  },
});
