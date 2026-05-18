import { defineStore } from 'pinia';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';
import { extractErrorMessage } from 'src/utils/error';

export interface AlertRule {
  id: string;
  user_id: string;
  token_id: string | null;
  team_id: string | null;
  alert_type: 'soft' | 'hard';
  rule_key: string;
  threshold_value: string;
  cooldown_hours: number;
  notify_email: string | null;
  notify_in_app: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AlertNotification {
  id: string;
  user_id: string;
  alert_rule_id: string | null;
  rule_key: string;
  alert_type: string;
  scope_type: string;
  scope_id: string | null;
  scope_name: string | null;
  current_value: string;
  threshold_value: string;
  message: string;
  channels_used: string | null;
  is_read: boolean;
  created_at: string;
}

export interface CreateAlertRulePayload {
  alert_type: string;
  rule_key: string;
  threshold_value: number;
  token_id?: string;
  team_id?: string;
  cooldown_hours?: number;
  notify_email?: string | undefined;
  notify_in_app?: boolean;
}

export interface UpdateAlertRulePayload {
  threshold_value?: number;
  cooldown_hours?: number;
  is_active?: boolean;
  notify_email?: string | null;
  notify_in_app?: boolean;
}

export const SOFT_RULES = [
  { label: 'Monthly cost reached', value: 'monthly_cost', unit: '$' },
  { label: 'Daily cost reached', value: 'daily_cost', unit: '$' },
  { label: 'Total cost reached', value: 'lifetime_cost', unit: '$' },
  { label: 'Hourly cost reached', value: 'hourly_cost', unit: '$' },
];

export const HARD_RULES = [
  { label: 'Monthly quota usage', value: 'monthly_quota_pct', unit: '%' },
  { label: 'Total quota usage', value: 'lifetime_quota_pct', unit: '%' },
  { label: 'Daily limit usage', value: 'daily_limit_pct', unit: '%' },
];

export const TEAM_RULES = [
  { label: 'Team budget usage', value: 'team_budget_pct', unit: '%' },
];

export const ALL_RULES = [...SOFT_RULES, ...HARD_RULES, ...TEAM_RULES];

export function getRuleLabel(ruleKey: string): string {
  return ALL_RULES.find((r) => r.value === ruleKey)?.label || ruleKey;
}

export function getRuleUnit(ruleKey: string): string {
  return ALL_RULES.find((r) => r.value === ruleKey)?.unit || '';
}

let _pollTimer: ReturnType<typeof setInterval> | null = null;

export const useAlertsStore = defineStore('alerts', {
  state: () => ({
    rules: [] as AlertRule[],
    notifications: [] as AlertNotification[],
    unreadCount: 0,
    loading: false,
  }),

  actions: {
    async fetchRules(tokenId?: string, teamId?: string) {
      this.loading = true;
      try {
        const params: Record<string, string> = {};
        if (tokenId) params.token_id = tokenId;
        if (teamId) params.team_id = teamId;
        const response = await api.get<AlertRule[]>('/admin/alerts/rules', { params });
        this.rules = response.data;
      } catch (error) {
        Notify.create({ type: 'negative', message: extractErrorMessage(error, 'Failed to load alert rules'), position: 'top' });
      } finally {
        this.loading = false;
      }
    },

    async createRule(data: CreateAlertRulePayload) {
      try {
        const response = await api.post<AlertRule>('/admin/alerts/rules', data);
        Notify.create({ type: 'positive', message: 'Alert rule created', position: 'top' });
        return response.data;
      } catch (error) {
        Notify.create({ type: 'negative', message: extractErrorMessage(error, 'Failed to create alert rule'), position: 'top' });
        return null;
      }
    },

    async updateRule(ruleId: string, data: UpdateAlertRulePayload) {
      try {
        await api.put(`/admin/alerts/rules/${ruleId}`, data);
        Notify.create({ type: 'positive', message: 'Alert rule updated', position: 'top' });
        return true;
      } catch (error) {
        Notify.create({ type: 'negative', message: extractErrorMessage(error, 'Failed to update alert rule'), position: 'top' });
        return false;
      }
    },

    async deleteRule(ruleId: string) {
      try {
        await api.delete(`/admin/alerts/rules/${ruleId}`);
        Notify.create({ type: 'positive', message: 'Alert rule deleted', position: 'top' });
        return true;
      } catch (error) {
        Notify.create({ type: 'negative', message: extractErrorMessage(error, 'Failed to delete alert rule'), position: 'top' });
        return false;
      }
    },

    async fetchNotifications(unreadOnly = false, limit = 50) {
      try {
        const response = await api.get<AlertNotification[]>('/admin/alerts/notifications', {
          params: { unread_only: unreadOnly, limit },
        });
        this.notifications = response.data;
      } catch {
        // silent
      }
    },

    async fetchUnreadCount() {
      try {
        const response = await api.get<{ count: number }>('/admin/alerts/notifications/unread-count');
        if (response.data.count !== this.unreadCount) {
          this.unreadCount = response.data.count;
        }
      } catch {
        // silent
      }
    },

    async markRead(notificationId: string) {
      try {
        await api.post(`/admin/alerts/notifications/${notificationId}/read`);
        const n = this.notifications.find((x) => x.id === notificationId);
        if (n) n.is_read = true;
        this.unreadCount = Math.max(0, this.unreadCount - 1);
      } catch {
        // silent
      }
    },

    async markAllRead() {
      try {
        await api.post('/admin/alerts/notifications/read-all');
        this.notifications.forEach((n) => (n.is_read = true));
        this.unreadCount = 0;
      } catch {
        // silent
      }
    },

    startPolling() {
      if (_pollTimer) return;
      void this.fetchUnreadCount();
      _pollTimer = setInterval(() => {
        void this.fetchUnreadCount();
      }, 15000);
    },

    stopPolling() {
      if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
      }
    },
  },
});
