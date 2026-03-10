<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Dashboard</div>

    <!-- Account Balance Card -->
    <q-card class="q-mb-md">
      <q-card-section>
        <div class="text-h6">Account Balance</div>
        <div v-if="tokensStore.loading" class="q-mt-md">
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
        <div class="row items-center justify-between q-mb-md">
          <div class="text-h6">Usage Statistics</div>
          <div class="row q-gutter-sm">
            <div v-if="groupBy === 'token'" class="row items-center q-gutter-sm">
              <span class="text-caption">Show Active:</span>
              <q-toggle
                v-model="showActiveTokens"
                dark
                color="primary"
              />
            </div>
            <q-input
              v-model="startDate"
              label="Start Date"
              outlined
              dense
              dark
              type="date"
              style="width: 160px"
            />
            <q-input
              v-model="endDate"
              label="End Date"
              outlined
              dense
              dark
              type="date"
              style="width: 160px"
            />
            <q-select
              v-model="groupBy"
              :options="groupByOptions"
              label="Group By"
              outlined
              dense
              dark
              style="width: 150px"
              emit-value
              map-options
            />
            <q-select
              v-if="groupBy === 'token'"
              v-model="selectedToken"
              :options="tokenOptions"
              label="Filter API Key"
              outlined
              dense
              dark
              clearable
              style="width: 200px"
              emit-value
              map-options
            />
            <q-select
              v-if="groupBy === 'model'"
              v-model="selectedModel"
              :options="modelOptions"
              label="Filter Model"
              outlined
              dense
              dark
              clearable
              style="width: 200px"
            />
          </div>
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
import { useTokensStore } from 'src/stores/tokens';
import { useDashboardStore } from 'src/stores/dashboard';

const tokensStore = useTokensStore();
const dashboardStore = useDashboardStore();

const groupBy = ref<'token' | 'model'>('token');
const selectedToken = ref<string | null>(null);
const selectedModel = ref<string | null>(null);
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

  return (totalQuota - totalUsed).toFixed(8);
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
  if (newValue === 'token') {
    await fetchUsageByToken();
  } else {
    await fetchUsageByModel();
  }
});

watch(selectedToken, async () => {
  if (groupBy.value === 'token') {
    await fetchUsageByToken();
  }
});

watch([startDate, endDate], async () => {
  if (groupBy.value === 'token') {
    await fetchUsageByToken();
  } else {
    await fetchUsageByModel();
  }
});

onMounted(async () => {
  // 并行加载所有数据以提高性能
  await Promise.all([
    tokensStore.fetchTokens(),
    fetchUsageByToken(),
    fetchUsageByModel(),
  ]);
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
