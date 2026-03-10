import { defineStore } from 'pinia';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';

export interface AggregatedStat {
  time_bucket: string;
  call_count: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_cost: number;
}

export interface TokenSummary {
  token_id: string;
  token_name: string;
  call_count: number;
  total_tokens: number;
  total_cost: number;
}

export interface TimeseriesPoint {
  time_bucket: string;
  value: number;
}

export interface TokenTimeseries {
  token_id: string;
  token_name: string;
  data: TimeseriesPoint[];
}

export interface DateRange {
  start: string;
  end: string;
}

export interface PricingRecord {
  model_id: string;
  region: string;
  input_price_per_token: string;
  output_price_per_token: string;
  input_price_per_1k: string;
  output_price_per_1k: string;
  input_price_per_1m: string;
  output_price_per_1m: string;
  source: string;
  last_updated: string | null;
}

export interface PricingTableResponse {
  total_records: number;
  pricing_data: PricingRecord[];
  cache_info: {
    cached_at: string;
    cache_duration_hours: number;
    expires_at: string;
    is_cached: boolean;
    cache_age_seconds: number;
  };
}

export const useMonitorStore = defineStore('monitor', {
  state: () => ({
    selectedTokenIds: [] as string[],
    dateRange: {
      start: '',
      end: '',
    } as DateRange,
    granularity: 'daily' as string,
    aggregatedStats: [] as AggregatedStat[],
    tokenSummary: [] as TokenSummary[],
    tokenTimeseries: [] as TokenTimeseries[],
    pricingTable: null as PricingTableResponse | null,
    loading: false,
    loadingPricing: false,
  }),

  actions: {
    async fetchAggregatedStats() {
      this.loading = true;
      try {
        const params: Record<string, string> = {
          granularity: this.granularity,
          tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        };
        if (this.dateRange.start) {
          params.start_date = this.dateRange.start;
        }
        if (this.dateRange.end) {
          params.end_date = this.dateRange.end;
        }
        if (this.selectedTokenIds.length > 0) {
          params.token_ids = this.selectedTokenIds.join(',');
        }
        const response = await api.get<{
          granularity: string;
          start_date: string;
          end_date: string;
          data: AggregatedStat[];
        }>('/admin/usage/aggregated-stats', { params });
        this.aggregatedStats = response.data.data || [];
      } catch (error: unknown) {
        if (error && typeof error === 'object' && 'response' in error) {
          const response = error.response as { status?: number; data?: { detail?: string } };
          if (response?.status === 401) {
            return;
          }
          const message = response?.data?.detail || 'Failed to fetch aggregated stats';
          Notify.create({
            type: 'negative',
            message,
            position: 'top',
          });
        } else {
          Notify.create({
            type: 'negative',
            message: 'Failed to fetch aggregated stats',
            position: 'top',
          });
        }
        this.aggregatedStats = [];
      } finally {
        this.loading = false;
      }
    },

    async fetchTokenSummary() {
      this.loading = true;
      try {
        const params: Record<string, string> = {};
        if (this.dateRange.start) {
          params.start_date = this.dateRange.start;
        }
        if (this.dateRange.end) {
          params.end_date = this.dateRange.end;
        }
        const response = await api.get<TokenSummary[]>(
          '/admin/usage/token-summary',
          { params },
        );
        this.tokenSummary = response.data || [];
      } catch (error: unknown) {
        if (error && typeof error === 'object' && 'response' in error) {
          const response = error.response as { status?: number; data?: { detail?: string } };
          if (response?.status === 401) {
            return;
          }
          const message = response?.data?.detail || 'Failed to fetch token summary';
          Notify.create({
            type: 'negative',
            message,
            position: 'top',
          });
        } else {
          Notify.create({
            type: 'negative',
            message: 'Failed to fetch token summary',
            position: 'top',
          });
        }
        this.tokenSummary = [];
      } finally {
        this.loading = false;
      }
    },

    async fetchTokenTimeseries(metric = 'calls') {
      if (this.selectedTokenIds.length === 0) {
        this.tokenTimeseries = [];
        return;
      }
      this.loading = true;
      try {
        const params: Record<string, string> = {
          granularity: this.granularity,
          metric,
          token_ids: this.selectedTokenIds.join(','),
          tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        };
        if (this.dateRange.start) {
          params.start_date = this.dateRange.start;
        }
        if (this.dateRange.end) {
          params.end_date = this.dateRange.end;
        }
        const response = await api.get<{
          granularity: string;
          metric: string;
          series: TokenTimeseries[];
        }>('/admin/usage/tokens-timeseries', { params });
        this.tokenTimeseries = response.data.series || [];
      } catch (error: unknown) {
        if (error && typeof error === 'object' && 'response' in error) {
          const response = error.response as { status?: number; data?: { detail?: string } };
          if (response?.status === 401) {
            return;
          }
          const message = response?.data?.detail || 'Failed to fetch token timeseries';
          Notify.create({
            type: 'negative',
            message,
            position: 'top',
          });
        } else {
          Notify.create({
            type: 'negative',
            message: 'Failed to fetch token timeseries',
            position: 'top',
          });
        }
        this.tokenTimeseries = [];
      } finally {
        this.loading = false;
      }
    },

    async fetchPricingTable(forceRefresh = false) {
      this.loadingPricing = true;
      try {
        const params: Record<string, string> = {};
        if (forceRefresh) {
          params.force_refresh = 'true';
        }
        const response = await api.get<PricingTableResponse>(
          '/admin/monitor/pricing-table',
          { params },
        );
        this.pricingTable = response.data;
      } catch (error: unknown) {
        if (error && typeof error === 'object' && 'response' in error) {
          const response = error.response as { status?: number; data?: { detail?: string } };
          if (response?.status === 401) {
            return;
          }
          const message = response?.data?.detail || 'Failed to fetch pricing table';
          Notify.create({
            type: 'negative',
            message,
            position: 'top',
          });
        } else {
          Notify.create({
            type: 'negative',
            message: 'Failed to fetch pricing table',
            position: 'top',
          });
        }
        this.pricingTable = null;
      } finally {
        this.loadingPricing = false;
      }
    },

    async fetchAll() {
      await Promise.all([
        this.fetchAggregatedStats(),
        this.fetchTokenSummary(),
        this.fetchTokenTimeseries(),
      ]);
    },
  },
});
