<template>
  <q-page class="q-pa-md">
    <!-- Header row -->
    <div class="row items-center q-mb-md">
      <div class="text-h4">Traces</div>
      <q-badge
        :color="enabled ? 'green-7' : 'red-7'"
        :label="enabled ? 'Recording ON' : 'Recording OFF'"
        class="q-ml-md"
      />
      <q-space />
      <q-btn
        flat
        dense
        icon="refresh"
        label="Refresh"
        :loading="loading"
        @click="fetchTraces"
      />
      <q-btn
        flat
        dense
        :icon="autoOn ? 'pause' : 'play_arrow'"
        :label="autoOn ? 'Auto: On' : 'Auto: Off'"
        :color="autoOn ? 'primary' : undefined"
        class="q-ml-sm"
        @click="toggleAuto"
      />
      <q-btn
        flat
        dense
        icon="delete_outline"
        label="Clear"
        color="negative"
        class="q-ml-sm"
        @click="clearTraces"
      />
    </div>

    <!-- Filters -->
    <q-card class="q-mb-md">
      <q-card-section class="row items-center q-gutter-md">
        <q-select
          v-model="filterModel"
          :options="modelOptions"
          label="Model"
          outlined
          dense
          dark
          emit-value
          map-options
          style="min-width: 200px"
        />
        <q-select
          v-model="filterToken"
          :options="tokenOptions"
          label="API Key"
          outlined
          dense
          dark
          emit-value
          map-options
          style="min-width: 200px"
        />
        <q-input
          v-model="search"
          label="Search content"
          outlined
          dense
          dark
          clearable
          debounce="300"
          style="min-width: 220px"
        >
          <template v-slot:prepend>
            <q-icon name="search" />
          </template>
        </q-input>
        <q-space />
        <div class="text-grey-5">{{ filtered.length }} / {{ allTraces.length }} traces</div>
      </q-card-section>
    </q-card>


    <!-- Error banner -->
    <q-banner v-if="error" class="bg-red-9 text-white q-mb-md" rounded dense>
      {{ error }}
    </q-banner>

    <!-- Timeline -->
    <div v-if="!filtered.length" class="text-center text-grey-6 q-pa-xl">
      No traces yet. Waiting for requests...
    </div>

    <q-list v-else bordered separator class="trace-list">
      <q-expansion-item
        v-for="t in filtered"
        :key="t.request_id"
        group="traces"
        dense
      >
        <!-- Trace header -->
        <template v-slot:header>
          <q-item-section avatar class="trace-avatar">
            <q-badge color="blue-9" :label="t.model" class="model-badge" />
          </q-item-section>
          <q-item-section>
            <div class="row items-center q-gutter-xs">
              <q-badge v-if="t.stream" color="orange-9" label="stream" />
              <q-badge :color="stopColor(t.stop_reason)" :label="t.stop_reason || '?'" />
              <span class="text-caption text-grey-5">{{ t.token_name }}</span>
              <span class="text-caption text-grey-7">{{ fmtTime(t.timestamp) }}</span>
              <span class="text-caption text-grey-6">{{ t.duration_s }}s</span>
            </div>
          </q-item-section>
          <q-item-section side>
            <div class="row items-center q-gutter-sm token-stats">
              <span class="text-grey-5">in:{{ fmt(t.input_tokens) }}</span>
              <span class="text-grey-5">out:{{ fmt(t.output_tokens) }}</span>
              <span v-if="t.cache_read_input_tokens" class="text-green-5"
                >⚡{{ fmt(t.cache_read_input_tokens) }}</span
              >
              <span v-if="t.cache_creation_input_tokens" class="text-orange-5"
                >✎{{ fmt(t.cache_creation_input_tokens) }}</span
              >
            </div>
          </q-item-section>
        </template>

        <!-- Trace body -->
        <q-card>
          <q-card-section style="max-height: 80vh; overflow-y: auto">
            <!-- Usage grid -->
            <div class="usage-grid q-mb-md">
              <div class="usage-item">
                <span class="k">Input</span><span class="v">{{ fmt(t.input_tokens) }}</span>
              </div>
              <div class="usage-item">
                <span class="k">Output</span><span class="v">{{ fmt(t.output_tokens) }}</span>
              </div>
              <div class="usage-item">
                <span class="k">Cache Read</span
                ><span class="v text-green-5">{{ fmt(t.cache_read_input_tokens) }}</span>
              </div>
              <div class="usage-item">
                <span class="k">Cache Write</span
                ><span class="v text-orange-5">{{ fmt(t.cache_creation_input_tokens) }}</span>
              </div>
              <div class="usage-item">
                <span class="k">Duration</span><span class="v">{{ t.duration_s }}s</span>
              </div>
              <div class="usage-item">
                <span class="k">Request ID</span><span class="v mono">{{ t.request_id }}</span>
              </div>
            </div>

            <!-- System prompt -->
            <q-expansion-item
              v-if="systemText(t)"
              label="System Prompt"
              header-class="section-header"
              dense
            >
              <div class="block-text system-block">{{ systemText(t) }}</div>
            </q-expansion-item>

            <!-- Tools -->
            <q-expansion-item
              v-if="t.tools && t.tools.length"
              :label="`Tools (${t.tools.length})`"
              header-class="section-header"
              dense
            >
              <div class="tools-scroll">
                <div v-for="(tool, i) in t.tools" :key="i" class="tool-def">
                  <div class="tool-name">{{ tool.name }}</div>
                  <div v-if="tool.description" class="tool-desc">
                    {{ String(tool.description).slice(0, 200) }}
                  </div>
                  <pre class="tool-schema">{{ schemaPreview(tool.input_schema) }}</pre>
                </div>
              </div>
            </q-expansion-item>

            <!-- Messages -->
            <q-expansion-item
              v-if="t.messages && t.messages.length"
              :label="`Messages (${t.messages.length})`"
              header-class="section-header"
              default-opened
              dense
            >
              <div class="section-scroll">
                <div v-for="(m, i) in t.messages" :key="i" class="msg" :class="m.role">
                  <div class="role-tag" :class="m.role">{{ m.role }}</div>
                  <template v-if="typeof m.content === 'string'">
                    <div class="block-text">{{ m.content }}</div>
                  </template>
                  <template v-else>
                    <div
                      v-for="(b, j) in m.content"
                      :key="j"
                      v-html="renderBlock(b)"
                      class="block-wrap"
                    ></div>
                  </template>
                </div>
              </div>
            </q-expansion-item>

            <!-- Response -->
            <q-expansion-item
              v-if="t.response_content && t.response_content.length"
              label="Response"
              header-class="section-header"
              default-opened
              dense
            >
              <div class="section-scroll">
                <div
                  v-for="(b, i) in t.response_content"
                  :key="i"
                  v-html="renderBlock(b)"
                  class="block-wrap"
                ></div>
              </div>
            </q-expansion-item>

            <!-- Error -->
            <div v-if="t.error" class="block-text error-block q-mt-sm">{{ t.error }}</div>
          </q-card-section>
        </q-card>
      </q-expansion-item>
    </q-list>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { api } from 'src/boot/axios';
import { Dialog, Notify } from 'quasar';

interface ContentBlock {
  type?: string;
  text?: string;
  thinking?: string;
  name?: string;
  id?: string;
  input?: unknown;
  content?: unknown;
  is_error?: boolean;
  source?: { media_type?: string };
}

interface Trace {
  request_id: string;
  timestamp: number;
  model: string;
  token_id: string;
  token_name: string;
  system?: string | { text?: string }[] | null;
  messages?: { role: string; content: string | ContentBlock[] }[];
  tools?: { name?: string; description?: string; input_schema?: unknown }[];
  response_content?: ContentBlock[];
  stream?: boolean;
  stop_reason?: string;
  duration_s?: number;
  input_tokens?: number;
  output_tokens?: number;
  cache_read_input_tokens?: number;
  cache_creation_input_tokens?: number;
  error?: string | null;
}

const allTraces = ref<Trace[]>([]);
const enabled = ref(false);
const loading = ref(false);
const error = ref('');

const filterModel = ref('all');
const filterToken = ref('all');
const search = ref('');

let autoInterval: ReturnType<typeof setInterval> | null = null;
const autoOn = ref(false);

const modelOptions = computed(() => {
  const set = new Set(allTraces.value.map((t) => t.model));
  return [{ label: 'All', value: 'all' }, ...[...set].map((m) => ({ label: m, value: m }))];
});

const tokenOptions = computed(() => {
  const map = new Map<string, string>();
  allTraces.value.forEach((t) => {
    if (t.token_name) map.set(t.token_id, t.token_name);
  });
  return [
    { label: 'All', value: 'all' },
    ...[...map].map(([id, name]) => ({ label: name, value: id })),
  ];
});

const filtered = computed(() => {
  let list = allTraces.value;
  if (filterModel.value !== 'all') list = list.filter((t) => t.model === filterModel.value);
  if (filterToken.value !== 'all') list = list.filter((t) => t.token_id === filterToken.value);
  if (search.value) {
    const q = search.value.toLowerCase();
    list = list.filter((t) => JSON.stringify(t).toLowerCase().includes(q));
  }
  return list;
});


async function fetchTraces() {
  loading.value = true;
  try {
    const { data } = await api.get('/admin/traces/');
    enabled.value = data.enabled;
    allTraces.value = data.traces || [];
    error.value = '';
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load traces';
  } finally {
    loading.value = false;
  }
}

function clearTraces() {
  Dialog.create({
    title: 'Clear Traces',
    message: 'Clear all stored traces? This cannot be undone.',
    cancel: true,
    dark: true,
  }).onOk(() => {
    void (async () => {
      try {
        await api.delete('/admin/traces/');
        await fetchTraces();
        Notify.create({ type: 'positive', message: 'Traces cleared', position: 'top' });
      } catch (e) {
        Notify.create({
          type: 'negative',
          message: e instanceof Error ? e.message : 'Failed to clear',
          position: 'top',
        });
      }
    })();
  });
}

function toggleAuto() {
  autoOn.value = !autoOn.value;
  if (autoOn.value) {
    autoInterval = setInterval(() => void fetchTraces(), 3000);
  } else if (autoInterval) {
    clearInterval(autoInterval);
    autoInterval = null;
  }
}

// --- formatting helpers ---
function fmt(n?: number): string {
  const v = n || 0;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return String(v);
}

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function stopColor(reason?: string): string {
  if (reason === 'end_turn') return 'green-8';
  if (reason === 'tool_use') return 'orange-9';
  if (reason === 'max_tokens') return 'red-8';
  return 'grey-8';
}

function systemText(t: Trace): string {
  if (!t.system) return '';
  if (typeof t.system === 'string') return t.system;
  return t.system.map((b) => b.text || '').join('\n');
}

function schemaPreview(schema: unknown): string {
  return JSON.stringify(schema, null, 2).slice(0, 500);
}

function esc(s: string | number | null | undefined): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderBlock(b: ContentBlock): string {
  if (!b) return '';
  const type = b.type || 'text';
  if (type === 'text') return `<div class="block-text">${esc(b.text)}</div>`;
  if (type === 'thinking') return `<div class="block-text thinking-block">${esc(b.thinking)}</div>`;
  if (type === 'tool_use') {
    const inputStr =
      typeof b.input === 'string' ? b.input : JSON.stringify(b.input || {}, null, 2);
    return `<div class="block-text tool-use-block"><span class="tool-name">${esc(
      b.name,
    )}</span> <span class="tool-id">${esc(b.id)}</span><div class="tool-input">${esc(
      inputStr,
    )}</div></div>`;
  }
  if (type === 'tool_result') {
    const content =
      typeof b.content === 'string' ? b.content : JSON.stringify(b.content || '', null, 2);
    return `<div class="block-text tool-result-block${
      b.is_error ? ' error-block' : ''
    }">${esc(content)}</div>`;
  }
  if (type === 'image') return `<div class="block-text">[image: ${esc(b.source?.media_type)}]</div>`;
  if (type === 'redacted_thinking')
    return `<div class="block-text thinking-block">[redacted thinking]</div>`;
  return `<div class="block-text">${esc(JSON.stringify(b))}</div>`;
}

onMounted(() => {
  void fetchTraces();
});

onUnmounted(() => {
  if (autoInterval) clearInterval(autoInterval);
});
</script>

<style scoped lang="scss">
.trace-list {
  border-radius: 12px;
  overflow: hidden;
}

.trace-avatar {
  min-width: auto;
  padding-right: 12px;
}

.model-badge {
  font-family: 'SF Mono', Menlo, monospace;
}

.token-stats {
  font-size: 12px;
  font-family: 'SF Mono', Menlo, monospace;
}

.usage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
}

.usage-item {
  display: flex;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.04);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;

  .k {
    color: #9aa0a6;
  }
  .v {
    color: #e8eaed;
    font-weight: 500;
  }
  .v.mono {
    font-family: 'SF Mono', Menlo, monospace;
    font-size: 11px;
  }
}

.msg {
  margin: 6px 0;
  padding: 8px 10px;
  border-radius: 6px;

  &.system {
    border-left: 3px solid #7c3aed;
  }
  &.user {
    border-left: 3px solid #58a6ff;
  }
  &.assistant {
    border-left: 3px solid #d2a8ff;
  }
}

.role-tag {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  margin-bottom: 4px;

  &.system {
    color: #a78bfa;
  }
  &.user {
    color: #79c0ff;
  }
  &.assistant {
    color: #d2a8ff;
  }
}

:deep(.block-text),
.block-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 12px;
  padding: 6px 8px;
  border-radius: 4px;
  margin: 4px 0;
  color: #c9d1d9;
  background: rgba(0, 0, 0, 0.25);
}

:deep(.thinking-block) {
  color: #a78bfa;
  max-height: 220px;
  overflow-y: auto;
}

:deep(.tool-use-block) {
  border-left: 2px solid #d29922;
}

:deep(.tool-result-block) {
  border-left: 2px solid #3fb950;
  max-height: 220px;
  overflow-y: auto;
}

:deep(.error-block),
.error-block {
  border-left: 2px solid #f85149;
  color: #ff7b72;
}

:deep(.tool-name) {
  color: #d29922;
  font-weight: 600;
}

:deep(.tool-id) {
  color: #6e7681;
  font-size: 10px;
}

:deep(.tool-input) {
  margin-top: 4px;
}

.system-block {
  max-height: 300px;
  overflow-y: auto;
}

.tools-scroll {
  max-height: 400px;
  overflow-y: auto;
}

.section-scroll {
  max-height: 600px;
  overflow-y: auto;
}

.tool-def {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 6px 0;

  .tool-name {
    color: #58a6ff;
    font-weight: 600;
    font-size: 13px;
  }
  .tool-desc {
    color: #9aa0a6;
    font-size: 12px;
    margin: 4px 0;
  }
  .tool-schema {
    font-family: 'SF Mono', Menlo, monospace;
    font-size: 11px;
    color: #8b949e;
    white-space: pre-wrap;
    word-break: break-word;
    margin: 0;
    max-height: 300px;
    overflow-y: auto;
  }
}

:deep(.section-header) {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #9aa0a6;
  letter-spacing: 0.5px;
}
</style>
