<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Monitor</div>

    <!-- Filters Row -->
    <q-card class="q-mb-md">
      <q-card-section>
        <div class="row items-center q-gutter-sm">
          <q-select
            v-model="monitorStore.selectedTokenIds"
            :options="tokenOptions"
            label="API Keys"
            outlined
            dense
            dark
            multiple
            emit-value
            map-options
            stack-label
            style="min-width: 280px"
          >
            <template v-slot:selected>
              <div class="row items-center full-width">
                <span class="text-grey-5">
                  {{ monitorStore.selectedTokenIds.length }} selected
                </span>
              </div>
            </template>
            <template v-slot:option="scope">
              <q-item v-bind="scope.itemProps">
                <q-item-section side>
                  <q-checkbox
                    :model-value="monitorStore.selectedTokenIds.includes(scope.opt.value)"
                    dense
                    dark
                    @click.stop="toggleToken(scope.opt.value)"
                  />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ scope.opt.label }}</q-item-label>
                </q-item-section>
              </q-item>
            </template>
            <template v-slot:append>
              <q-icon
                v-if="monitorStore.selectedTokenIds.length > 0"
                name="cancel"
                class="cursor-pointer"
                @click.stop="monitorStore.selectedTokenIds = []"
              />
            </template>
          </q-select>

          <q-btn-toggle
            v-model="datePreset"
            no-caps
            unelevated
            toggle-color="grey-8"
            color="grey-10"
            text-color="grey-5"
            toggle-text-color="white"
            :options="datePresetOptions"
            class="q-ml-sm"
          />

          <template v-if="datePreset === 'custom'">
            <q-input
              v-model="customStart"
              label="Start Date"
              outlined
              dense
              dark
              type="date"
              :min="minAllowedDate"
              style="width: 160px"
            />
            <q-input
              v-model="customEnd"
              label="End Date"
              outlined
              dense
              dark
              type="date"
              :min="minAllowedDate"
              style="width: 160px"
            />
          </template>

          <q-btn-toggle
            v-model="monitorStore.granularity"
            no-caps
            unelevated
            toggle-color="grey-8"
            color="grey-10"
            text-color="grey-5"
            toggle-text-color="white"
            :options="granularityOptions"
            class="q-ml-sm"
          />
        </div>
      </q-card-section>
    </q-card>

    <!-- Summary Cards -->
    <div class="row q-gutter-md q-mb-md">
      <div class="col">
        <q-card>
          <q-card-section>
            <div class="text-caption text-grey-7">Total Calls</div>
            <div v-if="monitorStore.loading">
              <q-skeleton type="text" width="120px" height="36px" />
            </div>
            <div v-else class="text-h4 text-primary q-mt-xs">
              {{ totalCalls.toLocaleString() }}
            </div>
          </q-card-section>
        </q-card>
      </div>
      <div class="col">
        <q-card>
          <q-card-section>
            <div class="text-caption text-grey-7">Total Tokens</div>
            <div v-if="monitorStore.loading">
              <q-skeleton type="text" width="120px" height="36px" />
            </div>
            <div v-else class="text-h4 text-secondary q-mt-xs">
              {{ totalTokens.toLocaleString() }}
            </div>
          </q-card-section>
        </q-card>
      </div>
      <div class="col">
        <q-card>
          <q-card-section>
            <div class="text-caption text-grey-7">Total Cost</div>
            <div v-if="monitorStore.loading">
              <q-skeleton type="text" width="120px" height="36px" />
            </div>
            <div v-else class="text-h4 text-positive q-mt-xs">
              ${{ totalCost }}
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- API Call Counts Chart -->
    <q-card class="q-mb-md">
      <q-card-section>
        <div class="text-h6 q-mb-md">API Call Counts per Token</div>
        <div v-if="monitorStore.loading" class="chart-placeholder">
          <q-skeleton type="rect" height="300px" />
        </div>
        <div v-else-if="callsChartData.datasets.length === 0" class="chart-placeholder text-grey-7 text-center">
          <q-icon name="insights" size="48px" class="q-mb-sm" />
          <div>Select API keys to view call count trends</div>
        </div>
        <div v-else style="height: 300px; position: relative">
          <Line :data="callsChartData" :options="chartOptions" />
        </div>
      </q-card-section>
    </q-card>

    <!-- Token Usage Chart -->
    <q-card class="q-mb-md">
      <q-card-section>
        <div class="text-h6 q-mb-md">Token Usage (Prompt vs Completion)</div>
        <div v-if="monitorStore.loading" class="chart-placeholder">
          <q-skeleton type="rect" height="300px" />
        </div>
        <div v-else-if="tokenUsageChartData.datasets.length === 0" class="chart-placeholder text-grey-7 text-center">
          <q-icon name="insights" size="48px" class="q-mb-sm" />
          <div>No token usage data available</div>
        </div>
        <div v-else style="height: 300px; position: relative">
          <Line :data="tokenUsageChartData" :options="chartOptions" />
        </div>
      </q-card-section>
    </q-card>

    <!-- Model Pricing Table -->
    <q-card>
      <q-card-section>
        <div class="row items-center justify-between q-mb-md">
          <div class="text-h6">Model Pricing Table</div>
          <div class="row items-center q-gutter-sm">
            <q-chip
              v-if="monitorStore.pricingTable"
              dense
              color="grey-8"
              text-color="grey-5"
              icon="schedule"
            >
              Cache: {{ formatCacheAge(monitorStore.pricingTable.cache_info.cache_age_seconds) }}
            </q-chip>
            <q-btn
              flat
              dense
              icon="refresh"
              color="primary"
              :loading="monitorStore.loadingPricing"
              @click="refreshPricingTable"
            >
              <q-tooltip>Refresh pricing data</q-tooltip>
            </q-btn>
          </div>
        </div>

        <div v-if="monitorStore.loadingPricing" class="chart-placeholder">
          <q-skeleton type="rect" height="400px" />
        </div>
        <div v-else-if="!monitorStore.pricingTable || monitorStore.pricingTable.pricing_data.length === 0" class="chart-placeholder text-grey-7 text-center">
          <q-icon name="price_check" size="48px" class="q-mb-sm" />
          <div>No pricing data available</div>
        </div>
        <q-table
          v-else
          :rows="filteredPricingData"
          :columns="pricingColumns"
          :row-key="(row) => row.model_id + '|' + row.region"
          flat
          dense
          dark
          :pagination="{ rowsPerPage: 20 }"
        >
          <template v-slot:top-right>
            <div class="row q-gutter-sm">
              <q-select
                v-model="selectedProvider"
                :options="providerOptions"
                label="Provider"
                outlined
                dense
                dark
                emit-value
                map-options
                style="min-width: 160px"
              />
              <q-select
                v-model="selectedRegion"
                :options="regionOptions"
                label="Region"
                outlined
                dense
                dark
                emit-value
                map-options
                style="min-width: 180px"
              />
              <q-input
                v-model="pricingFilter"
                dense
                debounce="300"
                placeholder="Search models"
                dark
                outlined
                style="min-width: 180px"
              >
                <template v-slot:append>
                  <q-icon name="search" />
                </template>
              </q-input>
            </div>
          </template>

          <template v-slot:body-cell-provider="props">
            <q-td :props="props">
              <q-chip
                dense
                :color="PROVIDER_COLORS[props.value] ?? 'grey-7'"
                text-color="white"
                size="sm"
              >
                {{ props.value }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-input_price_per_1m="props">
            <q-td :props="props">
              <span class="text-mono">{{ formatPrice(props.value) }}</span>
            </q-td>
          </template>

          <template v-slot:body-cell-output_price_per_1m="props">
            <q-td :props="props">
              <span class="text-mono">{{ formatPrice(props.value) }}</span>
            </q-td>
          </template>

          <template v-slot:body-cell-source="props">
            <q-td :props="props">
              <q-chip
                dense
                :color="props.value === 'api' ? 'blue-8' : props.value === 'aws-scraper' ? 'teal-8' : 'purple-8'"
                text-color="white"
                size="sm"
              >
                {{ props.value }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-last_updated="props">
            <q-td :props="props">
              <span class="text-caption text-grey-7">
                {{ props.value ? formatDate(props.value) : 'N/A' }}
              </span>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { Notify } from 'quasar';
import { Line } from 'vue-chartjs';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { useMonitorStore } from 'src/stores/monitor';
import { useTokensStore } from 'src/stores/tokens';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
);

const monitorStore = useMonitorStore();
const tokensStore = useTokensStore();

const datePreset = ref('7d');
const customStart = ref('');
const customEnd = ref('');
const pricingFilter = ref('');
const selectedRegion = ref<string | null>(null);
const selectedProvider = ref<string | null>(null);

// Provider colours — keyed by the display name returned by getProvider()
const PROVIDER_COLORS: Record<string, string> = {
  Amazon:    'blue-8',
  Anthropic: 'orange-8',
  Google:    'green-8',
  Gemini:    'teal-8',
  Meta:      'indigo-7',
  Mistral:   'deep-orange-7',
  Cohere:    'cyan-8',
  DeepSeek:  'purple-8',
  MiniMax:   'pink-7',
  Moonshot:  'blue-grey-7',
  NVIDIA:    'green-9',
  OpenAI:    'grey-7',
  Qwen:      'amber-8',
  AI21:      'light-blue-8',
  Writer:    'brown-7',
  ZAI:       'red-8',
};

const MAX_QUERY_DAYS = 90;
const minAllowedDate = computed(() => {
  const d = new Date();
  d.setDate(d.getDate() - MAX_QUERY_DAYS);
  return d.toISOString().slice(0, 10);
});

const datePresetOptions = [
  { label: '24h', value: '24h' },
  { label: '7d', value: '7d' },
  { label: '30d', value: '30d' },
  { label: '90d', value: '90d' },
  { label: 'Custom', value: 'custom' },
];

const granularityOptions = [
  { label: 'Hourly', value: 'hourly' },
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
  { label: 'Monthly', value: 'monthly' },
];

const CHART_COLORS = [
  '#1976d2',
  '#26a69a',
  '#f2c037',
  '#e91e63',
  '#9c27b0',
  '#ff9800',
  '#4caf50',
  '#00bcd4',
  '#ff5722',
  '#607d8b',
];

const pricingColumns = [
  {
    name: 'provider',
    label: 'Provider',
    field: 'provider',
    align: 'left' as const,
    sortable: true,
  },
  {
    name: 'model_id',
    label: 'Model ID',
    field: 'model_id',
    align: 'left' as const,
    sortable: true,
  },
  {
    name: 'region',
    label: 'Region',
    field: 'region',
    align: 'left' as const,
    sortable: true,
  },
  {
    name: 'input_price_per_1m',
    label: 'Input / 1M',
    field: 'input_price_per_1m',
    align: 'right' as const,
    sortable: true,
  },
  {
    name: 'output_price_per_1m',
    label: 'Output / 1M',
    field: 'output_price_per_1m',
    align: 'right' as const,
    sortable: true,
  },
  {
    name: 'source',
    label: 'Source',
    field: 'source',
    align: 'center' as const,
    sortable: true,
  },
  {
    name: 'last_updated',
    label: 'Updated',
    field: 'last_updated',
    align: 'center' as const,
    sortable: true,
  },
];

const tokenOptions = computed(() =>
  tokensStore.tokens.map((token) => ({
    label: token.name,
    value: token.id,
  })),
);

/**
 * Extract a human-readable provider name from a model_id.
 *
 * model_id formats:
 *   "amazon.nova-lite-v1:0"          → "Amazon"
 *   "anthropic.claude-3-5-sonnet…"   → "Anthropic"
 *   "us.amazon.nova-lite-v1:0"       → "Amazon"   (cross-region prefix)
 *   "global.anthropic.claude-…"      → "Anthropic"
 *   "gemini-2.5-pro"                 → "Gemini"
 *   "gemini-1.5-flash"               → "Gemini"
 *   "zai.glm-5"                      → "ZAI"
 */
function getProvider(modelId: string): string {
  // Strip cross-region prefixes: "us.", "eu.", "ap.", "global."
  const stripped = modelId.replace(/^(us|eu|ap|global|us-gov)\.[a-z]{0,4}\.?/, '');

  const prefix = (stripped.split('.')[0] ?? '').toLowerCase();

  const MAP: Record<string, string> = {
    amazon:    'Amazon',
    anthropic: 'Anthropic',
    meta:      'Meta',
    mistral:   'Mistral',
    cohere:    'Cohere',
    deepseek:  'DeepSeek',
    minimax:   'MiniMax',
    moonshot:  'Moonshot',
    nvidia:    'NVIDIA',
    openai:    'OpenAI',
    qwen:      'Qwen',
    ai21:      'AI21',
    writer:    'Writer',
    zai:       'ZAI',
    stability: 'Stability',
    twelvelabs:'TwelveLabs',
    google:    'Google',
    luma:      'Luma',
  };

  if (MAP[prefix]) return MAP[prefix];

  // Gemini models don't have a dot-prefix — identify by name
  if (modelId.startsWith('gemini-') || modelId.startsWith('gemini/')) return 'Gemini';

  // Fallback: capitalise first segment
  return prefix.charAt(0).toUpperCase() + prefix.slice(1);
}

/**
 * Format a per-1M price string with sensible precision.
 * Always shows at least 2 decimal places; uses up to 4 for sub-cent prices.
 */
function formatPrice(value: string): string {
  const n = Number(value);
  if (n === 0) return '$0.00';
  // Use 4 decimal places for prices < $0.10, else 2
  const decimals = n < 0.10 ? 4 : 2;
  return '$' + n.toFixed(decimals);
}

const enrichedPricingData = computed(() => {
  if (!monitorStore.pricingTable) return [];
  return monitorStore.pricingTable.pricing_data.map(record => ({
    ...record,
    provider: getProvider(record.model_id),
  }));
});

const providerOptions = computed(() => {
  const providers = new Set<string>();
  enrichedPricingData.value.forEach(r => providers.add(r.provider));
  return [
    { label: 'All Providers', value: null },
    ...Array.from(providers).sort().map(p => ({ label: p, value: p })),
  ];
});

const regionOptions = computed(() => {
  const regions = new Set<string>();
  enrichedPricingData.value.forEach(r => regions.add(r.region));
  return [
    { label: 'All Regions', value: null },
    ...Array.from(regions).sort().map(region => ({
      label: region,
      value: region,
    })),
  ];
});

const filteredPricingData = computed(() => {
  let data = enrichedPricingData.value;

  if (selectedProvider.value) {
    data = data.filter(r => r.provider === selectedProvider.value);
  }

  if (selectedRegion.value) {
    data = data.filter(r => r.region === selectedRegion.value);
  }

  if (pricingFilter.value) {
    const searchLower = pricingFilter.value.toLowerCase();
    data = data.filter(r =>
      r.model_id.toLowerCase().includes(searchLower) ||
      r.region.toLowerCase().includes(searchLower) ||
      r.provider.toLowerCase().includes(searchLower),
    );
  }

  return data;
});

const totalCalls = computed(() => {
  // 如果没有选中任何 token，显示所有
  if (monitorStore.selectedTokenIds.length === 0) {
    return monitorStore.tokenSummary.reduce((sum, item) => sum + item.call_count, 0);
  }
  // 只计算选中的 token
  return monitorStore.tokenSummary
    .filter(item => monitorStore.selectedTokenIds.includes(item.token_id))
    .reduce((sum, item) => sum + item.call_count, 0);
});

const totalTokens = computed(() => {
  // 如果没有选中任何 token，显示所有
  if (monitorStore.selectedTokenIds.length === 0) {
    return monitorStore.tokenSummary.reduce((sum, item) => sum + item.total_tokens, 0);
  }
  // 只计算选中的 token
  return monitorStore.tokenSummary
    .filter(item => monitorStore.selectedTokenIds.includes(item.token_id))
    .reduce((sum, item) => sum + item.total_tokens, 0);
});

const totalCost = computed(() => {
  let sum: number;
  // 如果没有选中任何 token，显示所有
  if (monitorStore.selectedTokenIds.length === 0) {
    sum = monitorStore.tokenSummary.reduce(
      (acc, item) => acc + Number(item.total_cost),
      0,
    );
  } else {
    // 只计算选中的 token
    sum = monitorStore.tokenSummary
      .filter(item => monitorStore.selectedTokenIds.includes(item.token_id))
      .reduce((acc, item) => acc + Number(item.total_cost), 0);
  }
  return sum.toFixed(4);
});

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      labels: {
        color: '#9aa0a6',
      },
    },
    tooltip: {
      backgroundColor: '#292a2d',
      titleColor: '#e8eaed',
      bodyColor: '#e8eaed',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      borderWidth: 1,
    },
  },
  scales: {
    x: {
      ticks: { color: '#9aa0a6' },
      grid: { color: 'rgba(255, 255, 255, 0.05)' },
    },
    y: {
      ticks: { color: '#9aa0a6' },
      grid: { color: 'rgba(255, 255, 255, 0.05)' },
    },
  },
};

const callsChartData = computed(() => {
  // Collect all unique time buckets across all series and sort them
  const bucketSet = new Set<string>();
  for (const ts of monitorStore.tokenTimeseries) {
    for (const p of ts.data) {
      bucketSet.add(p.time_bucket);
    }
  }
  const allBuckets = Array.from(bucketSet).sort();
  const labels = allBuckets.map((b) => formatBucket(b));

  // Align each series to the unified time axis (0 for missing buckets)
  const datasets = monitorStore.tokenTimeseries.map((ts, index) => {
    const bucketMap = new Map(ts.data.map((p) => [p.time_bucket, p.value]));
    return {
      label: ts.token_name,
      data: allBuckets.map((b) => bucketMap.get(b) ?? 0),
      borderColor: CHART_COLORS[index % CHART_COLORS.length],
      backgroundColor: CHART_COLORS[index % CHART_COLORS.length] + '33',
      tension: 0.3,
      fill: false,
    };
  });

  return { labels, datasets };
});

const tokenUsageChartData = computed(() => {
  // 如果没有选中任何 token，使用所有 token 的聚合数据
  if (monitorStore.selectedTokenIds.length === 0) {
    const stats = monitorStore.aggregatedStats;
    const labels = stats.map((s) => formatBucket(s.time_bucket));

    return {
      labels,
      datasets: [
        {
          label: 'Prompt Tokens',
          data: stats.map((s) => s.total_prompt_tokens),
          borderColor: '#1976d2',
          backgroundColor: '#1976d233',
          tension: 0.3,
          fill: true,
        },
        {
          label: 'Completion Tokens',
          data: stats.map((s) => s.total_completion_tokens),
          borderColor: '#26a69a',
          backgroundColor: '#26a69a33',
          tension: 0.3,
          fill: true,
        },
      ],
    };
  }

  // 如果选中了特定 token，也使用聚合数据（因为后端 aggregatedStats 会根据 token_id 过滤）
  const stats = monitorStore.aggregatedStats;
  const labels = stats.map((s) => formatBucket(s.time_bucket));

  return {
    labels,
    datasets: [
      {
        label: 'Prompt Tokens',
        data: stats.map((s) => s.total_prompt_tokens),
        borderColor: '#1976d2',
        backgroundColor: '#1976d233',
        tension: 0.3,
        fill: true,
      },
      {
        label: 'Completion Tokens',
        data: stats.map((s) => s.total_completion_tokens),
        borderColor: '#26a69a',
        backgroundColor: '#26a69a33',
        tension: 0.3,
        fill: true,
      },
    ],
  };
});

function formatBucket(bucket: string): string {
  const d = new Date(bucket);
  if (monitorStore.granularity === 'hourly') {
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatCacheAge(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

async function refreshPricingTable() {
  await monitorStore.fetchPricingTable(true);
}

const toggleToken = (tokenId: string) => {
  const index = monitorStore.selectedTokenIds.indexOf(tokenId);
  if (index > -1) {
    monitorStore.selectedTokenIds.splice(index, 1);
  } else {
    monitorStore.selectedTokenIds.push(tokenId);
  }
};

function applyDatePreset(preset: string) {
  const now = new Date();
  const end = now.toISOString();

  let start: Date;
  switch (preset) {
    case '24h':
      start = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      break;
    case '7d':
      start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      break;
    case '30d':
      start = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      break;
    case '90d':
      start = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
      break;
    default:
      return;
  }

  monitorStore.dateRange.start = start.toISOString();
  monitorStore.dateRange.end = end;
}

function applyCustomDates() {
  if (!customStart.value || !customEnd.value) return;

  const start = new Date(customStart.value);
  const end = new Date(customEnd.value);
  const earliest = new Date();
  earliest.setDate(earliest.getDate() - MAX_QUERY_DAYS);

  if (start < earliest) {
    Notify.create({
      type: 'warning',
      message: `Start date cannot be more than ${MAX_QUERY_DAYS} days ago`,
      position: 'top',
    });
    customStart.value = minAllowedDate.value;
    return;
  }

  const diffDays = (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24);
  if (diffDays > MAX_QUERY_DAYS) {
    Notify.create({
      type: 'warning',
      message: `Date range cannot exceed ${MAX_QUERY_DAYS} days`,
      position: 'top',
    });
    return;
  }

  start.setHours(0, 0, 0, 0);
  monitorStore.dateRange.start = start.toISOString();
  end.setHours(23, 59, 59, 999);
  monitorStore.dateRange.end = end.toISOString();
}

watch(datePreset, (preset) => {
  if (preset !== 'custom') {
    applyDatePreset(preset);
    void monitorStore.fetchAll();
  }
});

watch([customStart, customEnd], () => {
  if (datePreset.value === 'custom' && customStart.value && customEnd.value) {
    applyCustomDates();
    void monitorStore.fetchAll();
  }
});

watch(
  () => monitorStore.granularity,
  () => {
    void monitorStore.fetchAll();
  },
);

watch(
  () => monitorStore.selectedTokenIds,
  () => {
    void monitorStore.fetchTokenTimeseries();
    void monitorStore.fetchAggregatedStats();
  },
  { deep: true },
);

onMounted(async () => {
  applyDatePreset('7d');
  await tokensStore.fetchTokens();

  // 默认选中所有 token
  monitorStore.selectedTokenIds = tokensStore.tokens.map(token => token.id);

  await monitorStore.fetchAll();

  // Fetch pricing table
  await monitorStore.fetchPricingTable();
});
</script>

<style scoped lang="scss">
.text-mono {
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: #9aa0a6;
}

.chart-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}
</style>
