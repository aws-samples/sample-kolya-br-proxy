<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Model Permission Management</div>

    <!-- Step Indicator -->
    <q-stepper
      v-model="step"
      vertical
      color="grey-8"
      animated
      flat
      class="bg-transparent"
    >
      <!-- Step 1: Select API Key -->
      <q-step
        :name="1"
        title="Select API Key"
        icon="vpn_key"
        :done="step > 1"
      >
        <div class="text-body2 text-grey-7 q-mb-md">
          Select an API Key to configure model permissions
        </div>
        <q-select
          v-model="selectedTokenId"
          :options="tokenOptions"
          option-value="id"
          option-label="label"
          outlined
          rounded
          dark
          label="Select API Key"
          emit-value
          map-options
          clearable
          @update:model-value="onTokenChange"
          :loading="tokensStore.loading"
          class="q-mb-md"
        >
          <template v-slot:no-option>
            <q-item>
              <q-item-section class="text-grey">
                No API Keys available
              </q-item-section>
            </q-item>
          </template>
        </q-select>
        <div v-if="selectedTokenId && currentToken" class="text-caption text-grey-7 q-mb-md">
          Current config: {{ currentToken.allowed_models?.length > 0 ? currentToken.allowed_models.join(', ') : 'No model permissions' }}
        </div>
        <q-stepper-navigation>
          <q-btn
            @click="step = 2"
            color="green"
            icon="arrow_downward"
            :disable="!selectedTokenId"
            fab-mini
            class="circle-btn"
          >
            <q-tooltip>Next</q-tooltip>
          </q-btn>
        </q-stepper-navigation>
      </q-step>

      <!-- Step 2: Configure Model Permissions -->
      <q-step
        :name="2"
        title="Configure Model Permissions"
        icon="settings"
      >
        <div class="text-body2 text-grey-7 q-mb-md">
          Configure allowed models for this API Key
        </div>
      </q-step>
    </q-stepper>

    <!-- Models Table -->
    <div v-if="step === 2 && selectedTokenId" style="margin-left: 48px">
      <div class="q-mb-md">
        <q-btn
          color="grey-8"
          icon="add"
          label="Add Model"
          @click="openAddDialog"
          unelevated
          size="sm"
        />
      </div>
      <q-table
        :rows="models"
        :columns="columns"
        row-key="model_id"
        flat
        :loading="loading"
        :rows-per-page-options="[10, 25, 50]"
        class="bg-transparent"
      >
        <template v-slot:body-cell-action="props">
          <q-td :props="props">
            <q-btn
              flat
              dense
              round
              icon="delete"
              @click="deleteModel(props.row)"
              :loading="deletingModelId === props.row.id"
            >
              <q-tooltip>Delete</q-tooltip>
            </q-btn>
          </q-td>
        </template>
      </q-table>
      <div class="q-mt-xl">
        <q-btn
          @click="step = 1"
          color="green"
          icon="arrow_upward"
          fab-mini
          class="circle-btn"
        >
          <q-tooltip>Previous</q-tooltip>
        </q-btn>
      </div>
    </div>

    <!-- Add Model Dialog -->
    <q-dialog v-model="showAddDialog">
      <q-card dark style="min-width: 520px">
        <q-card-section>
          <div class="text-h6">Add Model</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <!-- Provider selector -->
          <div class="text-caption text-grey-6 q-mb-xs">Provider</div>
          <q-btn-toggle
            v-model="selectedProvider"
            no-caps
            unelevated
            dense
            toggle-color="grey-7"
            color="grey-9"
            text-color="grey-4"
            toggle-text-color="white"
            :options="[
              { label: 'AWS Bedrock', value: 'bedrock' },
              { label: 'Google Gemini', value: 'google' },
            ]"
            class="q-mb-md"
            @update:model-value="onProviderChange"
          />

          <q-select
            v-model="selectedAwsModel"
            :options="filteredAwsModels"
            option-label="friendly_name"
            option-value="friendly_name"
            :label="selectedProvider === 'google' ? 'Select Gemini Model' : 'Select Model from AWS Bedrock'"
            outlined
            dark
            :loading="loadingAwsModels"
            use-input
            input-debounce="300"
            @filter="filterModels"
          >
            <template v-slot:option="scope">
              <q-item v-bind="scope.itemProps">
                <q-item-section>
                  <q-item-label>
                    {{ scope.opt.friendly_name }}
                    <template v-if="scope.opt.provider === 'google'">
                      <q-badge color="green-8" label="Google" class="q-ml-sm" />
                    </template>
                    <template v-else>
                      <q-badge
                        v-if="scope.opt.is_cross_region"
                        :color="scope.opt.cross_region_type === 'global' ? 'orange-8' : 'blue-8'"
                        :label="scope.opt.cross_region_type === 'global' ? 'Global' : scope.opt.cross_region_type?.toUpperCase()"
                        class="q-ml-sm"
                      />
                      <q-badge v-else color="grey-7" label="Standard" class="q-ml-sm" />
                    </template>
                  </q-item-label>
                  <q-item-label caption class="text-mono">{{ scope.opt.model_id }}</q-item-label>
                </q-item-section>
              </q-item>
            </template>
          </q-select>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn label="Cancel" unelevated v-close-popup color="grey-7" />
          <q-btn
            label="Add"
            color="grey-8"
            @click="addModel"
            :loading="adding"
            :disable="!selectedAwsModel"
            unelevated
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<style scoped lang="scss">
:deep(.q-stepper__label) {
  background: transparent !important;
}

:deep(.q-stepper__line:before) {
  background: white !important;
}

:deep(.q-stepper__line:after) {
  background: white !important;
}

.circle-btn {
  width: 40px !important;
  height: 40px !important;
  border-radius: 50% !important;
  min-width: 40px !important;
  min-height: 40px !important;
  padding: 0 !important;
  background-color: #21ba45 !important;

  &:hover {
    background-color: #1a9435 !important;
  }
}
</style>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { Notify } from 'quasar';
import { api } from 'src/boot/axios';

interface Model {
  id: string;
  model_id: string;
  model_name: string;
  friendly_name: string;
  provider: string;
  streaming_supported: boolean;
  is_active: boolean;
}

interface AwsModel {
  model_id: string;
  model_name: string;
  friendly_name: string;
  provider: string;
  is_cross_region: boolean;
  cross_region_type: string | null;
  streaming_supported: boolean;
}



import { useModelsStore } from 'src/stores/models';
import { useTokensStore } from 'src/stores/tokens';

const modelsStore = useModelsStore();
const tokensStore = useTokensStore();

const step = ref(1);
const showAddDialog = ref(false);
const selectedProvider = ref<'bedrock' | 'google'>('bedrock');
const awsModels = ref<AwsModel[]>([]);
const filteredAwsModels = ref<AwsModel[]>([]);
const loadingAwsModels = ref(false);
const selectedAwsModel = ref<AwsModel | null>(null);
const adding = ref(false);
const deletingModelId = ref<string | null>(null);
const selectedTokenId = ref<string | null>(null);


const columns = [
  {
    name: 'name',
    label: 'Model Name',
    field: 'model_name',
    align: 'left' as const,
    sortable: true,
  },
  {
    name: 'model_id',
    label: 'Model ID',
    field: 'model_id',
    align: 'left' as const,
  },
  {
    name: 'action',
    label: 'Action',
    field: 'id',
    align: 'center' as const,
  },
];

const models = computed(() => modelsStore.models);
const loading = computed(() => modelsStore.loading);

const tokenOptions = computed(() => {
  return tokensStore.tokens.map(token => ({
    id: token.id,
    label: `${token.name} (${token.id.substring(0, 8)}...)`,
    value: token.id,
  }));
});

const currentToken = computed(() => {
  if (!selectedTokenId.value) return null;
  return tokensStore.tokens.find(t => t.id === selectedTokenId.value);
});

function openAddDialog() {
  selectedProvider.value = 'bedrock';
  selectedAwsModel.value = null;
  filteredAwsModels.value = _modelsForProvider();
  showAddDialog.value = true;
}

async function fetchAwsModels() {
  loadingAwsModels.value = true;
  try {
    const response = await api.get<{ models: AwsModel[] }>('/admin/models/aws-available');
    awsModels.value = response.data.models;
    // Initialize with current provider filter
    filteredAwsModels.value = _modelsForProvider();
  } catch {
    Notify.create({
      type: 'negative',
      message: 'Failed to fetch model list',
      position: 'top',
    });
  } finally {
    loadingAwsModels.value = false;
  }
}

function _modelsForProvider(): AwsModel[] {
  if (selectedProvider.value === 'google') {
    return awsModels.value.filter(m => m.provider === 'google');
  }
  return awsModels.value.filter(m => m.provider !== 'google');
}

function onProviderChange() {
  // Clear selection when switching provider
  selectedAwsModel.value = null;
  filteredAwsModels.value = _modelsForProvider();
}

function filterModels(val: string, update: (fn: () => void) => void) {
  update(() => {
    const providerModels = _modelsForProvider();
    if (val === '') {
      filteredAwsModels.value = providerModels;
    } else {
      const needle = val.toLowerCase();
      filteredAwsModels.value = providerModels.filter(
        model =>
          model.friendly_name.toLowerCase().includes(needle) ||
          model.model_id.toLowerCase().includes(needle)
      );
    }
  });
}

async function addModel() {
  if (!selectedAwsModel.value || !selectedTokenId.value) return;

  adding.value = true;
  try {
    // Use model_id as-is from backend (already has correct prefix:
    // cross-region models have geographic prefix e.g. "us.", standard models have no prefix)
    await api.post('/admin/models', {
      token_id: selectedTokenId.value,
      model_name: selectedAwsModel.value.model_id,
    });

    Notify.create({
      type: 'positive',
      message: 'Model added successfully',
      position: 'top',
    });

    showAddDialog.value = false;
    selectedAwsModel.value = null;
    // Refresh models for the selected token only
    await modelsStore.fetchModels(selectedTokenId.value);
  } catch {
    Notify.create({
      type: 'negative',
      message: 'Failed to add model',
      position: 'top',
    });
  } finally {
    adding.value = false;
  }
}

async function deleteModel(model: Model) {
  deletingModelId.value = model.id;
  try {
    await api.delete(`/admin/models/${model.id}`);

    Notify.create({
      type: 'positive',
      message: 'Model deleted successfully',
      position: 'top',
    });

    // Remove model from local store (no need to refetch from AWS)
    modelsStore.models = modelsStore.models.filter(m => m.id !== model.id);
  } catch {
    Notify.create({
      type: 'negative',
      message: 'Failed to delete model',
      position: 'top',
    });
  } finally {
    deletingModelId.value = null;
  }
}

async function onTokenChange() {
  // Token changed, reload models for the selected token
  if (selectedTokenId.value) {
    // Clear old data first
    modelsStore.models = [];
    await modelsStore.fetchModels(selectedTokenId.value);
  } else {
    // Clear models if no token is selected
    modelsStore.models = [];
  }
}

onMounted(async () => {
  await Promise.all([
    tokensStore.fetchTokens(),
    fetchAwsModels(),
  ]);
  // Don't load models on init, wait for user to select a token
});
</script>
