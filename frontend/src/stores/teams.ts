import { defineStore } from 'pinia';
import { api } from '@/boot/axios';
import { Notify } from 'quasar';

export interface TeamMember {
  token_id: string;
  token_name: string;
  allocated_usd: string;
  used_usd: string;
  remaining_usd: string;
  daily_limit_usd: string;
  daily_used_usd: string;
  is_active: boolean;
  last_used_at: string | null;
}

export interface TeamDashboard {
  id: string;
  name: string;
  monthly_budget_usd: string;
  monthly_reset_policy: string;
  daily_limit_enabled: boolean;
  total_allocated_usd: string;
  total_used_usd: string;
  unallocated_pool_usd: string;
  members: TeamMember[];
}

export interface TeamListItem {
  id: string;
  name: string;
  monthly_budget_usd: string;
  monthly_reset_policy: string;
  daily_limit_enabled: boolean;
  member_count: number;
  total_used_usd: string;
  unallocated_pool_usd: string;
  created_at: string;
}

export const useTeamsStore = defineStore('teams', {
  state: () => ({
    teams: [] as TeamListItem[],
    currentTeam: null as TeamDashboard | null,
    loading: false,
  }),

  actions: {
    async fetchTeams() {
      this.loading = true;
      try {
        const response = await api.get<TeamListItem[]>('/admin/teams');
        this.teams = response.data;
      } catch {
        Notify.create({ type: 'negative', message: 'Failed to load teams' });
      } finally {
        this.loading = false;
      }
    },

    async fetchTeamDashboard(teamId: string) {
      this.loading = true;
      try {
        const response = await api.get<TeamDashboard>(`/admin/teams/${teamId}`);
        this.currentTeam = response.data;
      } catch {
        Notify.create({ type: 'negative', message: 'Failed to load team details' });
      } finally {
        this.loading = false;
      }
    },

    async createTeam(data: { name: string; monthly_budget_usd: string; monthly_reset_policy: string; daily_limit_enabled?: boolean }) {
      const response = await api.post('/admin/teams', data);
      await this.fetchTeams();
      Notify.create({ type: 'positive', message: 'Team created' });
      return response.data;
    },

    async updateTeam(teamId: string, data: { name?: string; monthly_budget_usd?: string; monthly_reset_policy?: string; daily_limit_enabled?: boolean }) {
      await api.put(`/admin/teams/${teamId}`, data);
      await this.fetchTeams();
      if (this.currentTeam?.id === teamId) {
        await this.fetchTeamDashboard(teamId);
      }
      Notify.create({ type: 'positive', message: 'Team updated' });
    },

    async deleteTeam(teamId: string) {
      await api.delete(`/admin/teams/${teamId}`);
      this.currentTeam = null;
      await this.fetchTeams();
      Notify.create({ type: 'positive', message: 'Team deleted' });
    },

    async addMember(teamId: string, tokenId: string, allocatedUsd: string) {
      await api.post(`/admin/teams/${teamId}/members`, {
        token_id: tokenId,
        allocated_usd: allocatedUsd,
      });
      await this.fetchTeamDashboard(teamId);
      Notify.create({ type: 'positive', message: 'Member added' });
    },

    async removeMember(teamId: string, tokenId: string) {
      await api.delete(`/admin/teams/${teamId}/members/${tokenId}`);
      await this.fetchTeamDashboard(teamId);
      Notify.create({ type: 'positive', message: 'Member removed' });
    },

    async adjustMember(teamId: string, tokenId: string, allocatedUsd: string) {
      await api.put(`/admin/teams/${teamId}/members/${tokenId}`, {
        allocated_usd: allocatedUsd,
      });
      await this.fetchTeamDashboard(teamId);
      Notify.create({ type: 'positive', message: 'Allocation updated' });
    },

    async transferAllocation(teamId: string, fromTokenId: string, toTokenId: string, amount: string) {
      await api.post(`/admin/teams/${teamId}/transfer`, {
        from_token_id: fromTokenId,
        to_token_id: toTokenId,
        amount,
      });
      await this.fetchTeamDashboard(teamId);
      Notify.create({ type: 'positive', message: 'Transfer complete' });
    },

    async batchCreateMembers(teamId: string, data: {
      names: string;
      per_member_allocation: string;
      model_names?: string[];
    }) {
      const response = await api.post(`/admin/teams/${teamId}/members/batch`, data);
      await this.fetchTeamDashboard(teamId);
      Notify.create({ type: 'positive', message: `${response.data.total} members created` });
      return response.data;
    },
  },
});
