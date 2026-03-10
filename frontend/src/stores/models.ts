import { defineStore } from 'pinia';
import { api } from 'src/boot/axios';

export interface Model {
  id: string;
  model_name: string;
  model_id: string;
  friendly_name: string;
  is_active: boolean;
}

interface ModelsState {
  models: Model[];
  loading: boolean;
}

export const useModelsStore = defineStore('models', {
  state: (): ModelsState => ({
    models: [],
    loading: false,
  }),

  getters: {
    activeModels: (state) => state.models.filter(m => m.is_active),
  },

  actions: {
    async fetchModels(tokenIdOrForce?: string | boolean) {
      // Handle parameter: can be token_id (string) or force (boolean)
      let tokenId: string | undefined;
      let force = false;

      if (typeof tokenIdOrForce === 'string') {
        tokenId = tokenIdOrForce;
        force = true; // Always reload if token_id is specified
      } else if (typeof tokenIdOrForce === 'boolean') {
        force = tokenIdOrForce;
      }

      // Return cached data if available and not forcing refresh
      if (this.models.length > 0 && !force) {
        return;
      }

      this.loading = true;
      try {
        const params = tokenId ? { token_id: tokenId } : {};
        const response = await api.get<{ models: Model[] }>('/admin/models', { params });
        this.models = response.data.models;
      } catch (error) {
        console.error('Failed to fetch models:', error);
      } finally {
        this.loading = false;
      }
    },
  },
});
