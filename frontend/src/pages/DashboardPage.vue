<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Dashboard</div>

    <!-- Account Balance Card -->
    <q-card class="q-mb-md">
      <q-card-section>
        <div class="text-h6">Account Balance</div>
        <div v-if="!tokensStore.loaded" class="q-mt-md">
          <q-skeleton type="text" width="200px" height="48px" />
        </div>
        <div v-else class="text-h3 text-primary q-mt-md">
          ${{ totalBalance }}
        </div>
        <div class="text-caption text-grey-7 q-mt-sm">
          Total quota of all API Keys
        </div>
      </q-card-section>
    </q-card>

    <!-- Usage Statistics -->
    <q-card>
      <q-card-section>
        <div class="row items-center no-wrap q-gutter-sm q-mb-md">
          <div class="text-h6">Usage Statistics</div>
          <q-space />
          <div v-if="groupBy === 'token'" class="row items-center no-wrap q-gutter-xs">
            <span class="text-caption">Active:</span>
            <q-toggle
              v-model="showActiveTokens"
              dark
              color="primary"
              dense
            />
          </div>
          <q-input
            v-model="startDate"
            label="Start"
            outlined
            dense
            dark
            type="date"
            :min="minAllowedDate"
            style="width: 150px"
          />
          <q-input
            v-model="endDate"
            label="End"
            outlined
            dense
            dark
            type="date"
            :min="minAllowedDate"
            style="width: 150px"
          />
          <q-select
            v-model="groupBy"
            :options="groupByOptions"
            label="Group By"
            outlined
            dense
            dark
            style="width: 140px"
            emit-value
            map-options
          />
          <q-select
            v-if="groupBy === 'token'"
            v-model="selectedToken"
            :options="tokenOptions"
            label="API Key"
            outlined
            dense
            dark
            clearable
            style="width: 180px"
            emit-value
            map-options
          />
          <q-select
            v-if="groupBy === 'model'"
            v-model="selectedModel"
            :options="modelOptions"
            label="Model"
            outlined
            dense
            dark
            clearable
            style="width: 180px"
          />
          <q-btn
            icon="download"
            flat
            dense
            round
            size="xs"
            color="grey-7"
            :loading="exporting"
            @click="exportCsv"
          >
            <q-tooltip>Export CSV</q-tooltip>
          </q-btn>
          <q-btn
            v-if="authStore.isSuperAdmin"
            icon="vpn_key"
            flat
            dense
            round
            size="xs"
            color="grey-7"
            @click="exportKeys"
          >
            <q-tooltip>Export All Keys</q-tooltip>
          </q-btn>
        </div>

        <q-table
          :rows="displayRows"
          :columns="displayColumns"
          row-key="id"
          flat
          :loading="loading"
        >
          <template v-slot:body-cell-token_id="props">
            <q-td :props="props">
              <div class="text-mono text-caption">{{ props.row.token_id }}</div>
            </q-td>
          </template>

          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-badge
                :color="props.row.is_deleted ? 'negative' : 'positive'"
                :label="props.row.is_deleted ? 'Deleted' : 'Active'"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-cost="props">
            <q-td :props="props">
              <span class="text-weight-bold text-positive">${{ props.row.total_cost }}</span>
            </q-td>
          </template>
        </q-table>

        <div class="q-mt-sm q-px-md q-pb-md">
          <div class="text-caption text-grey-7 text-italic">
            * Cost estimates are for reference only. Please refer to your actual billing statement for accurate charges.
          </div>
        </div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { Notify } from 'quasar';
import { useTokensStore } from 'src/stores/tokens';
import { useDashboardStore } from 'src/stores/dashboard';
import { useAuthStore } from 'src/stores/auth';
import { api } from 'src/boot/axios';
import { getApiBaseUrl } from 'src/utils/api';

const tokensStore = useTokensStore();
const dashboardStore = useDashboardStore();
const authStore = useAuthStore();
const exporting = ref(false);

const groupBy = ref<'token' | 'model'>('token');
const selectedToken = ref<string | null>(null);
const selectedModel = ref<string | null>(null);
const MAX_QUERY_DAYS = 90;
const minAllowedDate = computed(() => {
  const d = new Date();
  d.setDate(d.getDate() - MAX_QUERY_DAYS);
  return d.toISOString().slice(0, 10);
});
const startDate = ref<string>('');
const endDate = ref<string>('');
const showActiveTokens = ref(true);

const groupByOptions = [
  { label: 'By API Key', value: 'token' },
  { label: 'By Model', value: 'model' },
];

// Account balance = Total quota - Total used (only tokens WITH a quota limit)
// Tokens without quota (unlimited) are excluded from balance calculation
const totalBalance = computed(() => {
  const tokensWithQuota = tokensStore.tokens.filter((token) => token.quota_usd);

  const totalQuota = tokensWithQuota.reduce((sum, token) => {
    return sum + parseFloat(token.quota_usd!);
  }, 0);

  const totalUsed = tokensWithQuota.reduce((sum, token) => {
    const used = token.used_usd ? parseFloat(token.used_usd) : 0;
    return sum + used;
  }, 0);

  return (totalQuota - totalUsed).toFixed(2);
});

const tokenOptions = computed(() => [
  { label: 'All', value: null },
  ...tokensStore.tokens.map((token) => ({
    label: token.name,
    value: token.id,
  })),
]);

const modelOptions = computed(() => {
  if (!dashboardStore.usageByModel || dashboardStore.usageByModel.length === 0) {
    return ['All'];
  }
  const models = new Set(dashboardStore.usageByModel.map((item) => item.model));
  return ['All', ...Array.from(models)];
});

const displayColumns = computed(() => {
  if (groupBy.value === 'token') {
    return [
      {
        name: 'token_id',
        label: 'ID',
        field: 'token_id',
        align: 'left' as const,
      },
      {
        name: 'name',
        label: 'API Key',
        field: 'token_name',
        align: 'left' as const,
      },
      {
        name: 'status',
        label: 'Status',
        field: 'is_deleted',
        align: 'center' as const,
      },
      {
        name: 'requests',
        label: 'Requests',
        field: 'total_requests',
        align: 'right' as const,
      },
      {
        name: 'tokens',
        label: 'Tokens',
        field: 'total_tokens',
        align: 'right' as const,
      },
      {
        name: 'cost',
        label: 'Cost',
        field: 'total_cost',
        align: 'right' as const,
      },
    ];
  } else {
    return [
      {
        name: 'model',
        label: 'Model',
        field: 'model',
        align: 'left' as const,
      },
      {
        name: 'requests',
        label: 'Requests',
        field: 'total_requests',
        align: 'right' as const,
      },
      {
        name: 'tokens',
        label: 'Tokens',
        field: 'total_tokens',
        align: 'right' as const,
      },
      {
        name: 'cost',
        label: 'Cost',
        field: 'total_cost',
        align: 'right' as const,
      },
    ];
  }
});

const loading = computed(() => dashboardStore.loading);

const displayRows = computed(() => {
  if (groupBy.value === 'token') {
    let rows = dashboardStore.usageByToken;
    if (showActiveTokens.value) {
      rows = rows.filter((item) => !item.is_deleted);
    }
    return rows.map((item, index) => ({
      id: index,
      ...item,
    }));
  } else {
    let rows = dashboardStore.usageByModel;
    if (selectedModel.value && selectedModel.value !== '全部') {
      rows = rows.filter((item) => item.model === selectedModel.value);
    }
    return rows.map((item, index) => ({
      id: index,
      ...item,
    }));
  }
});

function buildParams() {
  const params: Record<string, string> = {};
  if (startDate.value) {
    const start = new Date(startDate.value);
    start.setHours(0, 0, 0, 0);
    params.start_date = start.toISOString();
  }
  if (endDate.value) {
    const end = new Date(endDate.value);
    end.setHours(23, 59, 59, 999);
    params.end_date = end.toISOString();
  }
  return params;
}

async function fetchUsageByToken() {
  const params = buildParams();
  if (selectedToken.value) {
    params.token_id = selectedToken.value;
  }
  await dashboardStore.fetchUsageByToken(params);
}

async function fetchUsageByModel() {
  const params = buildParams();
  await dashboardStore.fetchUsageByModel(params);
}

watch(groupBy, async (newValue) => {
  if (!authStore.hasPermission('view_usage')) return;
  if (newValue === 'token') {
    await fetchUsageByToken();
  } else {
    await fetchUsageByModel();
  }
});

watch(selectedToken, async () => {
  if (!authStore.hasPermission('view_usage')) return;
  if (groupBy.value === 'token') {
    await fetchUsageByToken();
  }
});

watch([startDate, endDate], async () => {
  if (!authStore.hasPermission('view_usage')) return;
  if (groupBy.value === 'token') {
    await fetchUsageByToken();
  } else {
    await fetchUsageByModel();
  }
});

async function exportCsv() {
  exporting.value = true;
  try {
    const params: Record<string, string> = {
      granularity: 'daily',
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    if (startDate.value) {
      const start = new Date(startDate.value);
      start.setHours(0, 0, 0, 0);
      params.start_date = start.toISOString();
    } else {
      const d = new Date();
      d.setDate(d.getDate() - 89);
      d.setHours(0, 0, 0, 0);
      params.start_date = d.toISOString();
    }
    if (endDate.value) {
      const end = new Date(endDate.value);
      end.setHours(23, 59, 59, 999);
      params.end_date = end.toISOString();
    } else {
      params.end_date = new Date().toISOString();
    }
    if (selectedToken.value && groupBy.value === 'token') {
      params.token_id = selectedToken.value;
    }
    if (selectedModel.value && groupBy.value === 'model' && selectedModel.value !== 'All') {
      params.model = selectedModel.value;
    }

    const response = await api.get('/admin/usage/breakdown', { params });
    const rows = response.data.data as Array<Record<string, unknown>>;

    if (!rows || rows.length === 0) {
      Notify.create({ type: 'warning', message: 'No data to export', position: 'top' });
      return;
    }

    const tokenStatusMap = new Map(
      tokensStore.tokens.map(t => [t.id, t.is_active ? 'Active' : 'Inactive'])
    );

    const isSuperAdmin = authStore.isSuperAdmin;
    const headers = isSuperAdmin
      ? ['Date', 'API Key', 'Status', 'Model', 'Prompt Tokens', 'Completion Tokens', 'Total Tokens', 'Requests', 'Cost (USD)']
      : ['Date', 'Status', 'Model', 'Prompt Tokens', 'Completion Tokens', 'Total Tokens', 'Requests', 'Cost (USD)'];
    const csvRows = rows.map(r => {
      const row = isSuperAdmin
        ? [r.time_bucket, r.token_name, tokenStatusMap.get(String(r.token_id)) ?? 'Unknown', r.model, r.prompt_tokens, r.completion_tokens, r.total_tokens, r.request_count, r.total_cost]
        : [r.time_bucket, tokenStatusMap.get(String(r.token_id)) ?? 'Unknown', r.model, r.prompt_tokens, r.completion_tokens, r.total_tokens, r.request_count, r.total_cost];
      return row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',');
    });

    const csv = [headers.join(','), ...csvRows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `usage_${params.start_date.slice(0, 10)}_${params.end_date.slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } } };
    Notify.create({
      type: 'negative',
      message: err.response?.data?.detail || 'Failed to export CSV',
      position: 'top',
    });
  } finally {
    exporting.value = false;
  }
}

function exportKeys() {
  const token = localStorage.getItem('access_token');
  if (!token) return;
  window.open(`${getApiBaseUrl()}/admin/tokens/export/keys?token=${encodeURIComponent(token)}`, '_blank');
}

onMounted(async () => {
  const tasks: Promise<unknown>[] = [];
  if (authStore.hasPermission('manage_api_keys')) {
    tasks.push(tokensStore.fetchTokens());
  }
  if (authStore.hasPermission('view_usage')) {
    tasks.push(fetchUsageByToken());
    tasks.push(fetchUsageByModel());
  }
  await Promise.all(tasks);
});
</script>

<style scoped lang="scss">
.q-code {
  background: #1e1e1e;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;

  pre {
    margin: 0;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    color: #e8eaed;
  }
}

:deep(.q-stepper__title) {
  background: transparent !important;
}

:deep(.q-stepper__label) {
  background: transparent !important;
}
</style>
