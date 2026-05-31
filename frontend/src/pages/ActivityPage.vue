<template>
  <q-page padding>
    <div class="row items-center q-mb-lg">
      <div class="text-h5 q-mr-md">Activity</div>
      <q-select
        v-model="days"
        :options="dayOptions"
        dense
        outlined
        style="width: 140px"
        @update:model-value="fetchActivity"
      />
      <q-space />
      <q-btn flat dense round icon="refresh" @click="fetchActivity" />
    </div>

    <q-table
      :rows="items"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      :pagination="{ rowsPerPage: 50 }"
    >
      <template v-slot:body-cell-action="props">
        <q-td :props="props">
          <q-badge :color="actionColor(props.row.action)" :label="formatAction(props.row.action)" />
        </q-td>
      </template>
      <template v-slot:body-cell-created_at="props">
        <q-td :props="props">
          {{ formatTime(props.row.created_at) }}
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { api } from 'src/boot/axios';

interface ActivityItem {
  id: string;
  user_id: string | null;
  user_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: string | null;
  created_at: string;
}

const items = ref<ActivityItem[]>([]);
const loading = ref(false);
const days = ref({ label: 'Last 7 days', value: 7 });
const dayOptions = [
  { label: 'Last 7 days', value: 7 },
  { label: 'Last 14 days', value: 14 },
  { label: 'Last 30 days', value: 30 },
];

const columns = [
  { name: 'user_email', label: 'User', field: 'user_email', align: 'left' as const },
  { name: 'action', label: 'Action', field: 'action', align: 'left' as const },
  { name: 'resource_type', label: 'Resource', field: 'resource_type', align: 'left' as const },
  { name: 'details', label: 'Details', field: (row: ActivityItem) => parseDetails(row.details), align: 'left' as const },
  { name: 'created_at', label: 'Time', field: 'created_at', align: 'left' as const },
];

function parseDetails(details: string | null): string {
  if (!details) return '';
  try {
    const obj = JSON.parse(details);
    if (obj.name) return obj.name;
    if (obj.token_name) return obj.token_name;
    if (obj.email) return obj.email;
    if (obj.names) return obj.names.join(', ');
    return JSON.stringify(obj);
  } catch {
    return details;
  }
}

function formatAction(action: string): string {
  return action.replace(/_/g, ' ');
}

function actionColor(action: string): string {
  if (action.includes('created') || action.includes('added')) return 'positive';
  if (action.includes('deleted') || action.includes('removed')) return 'negative';
  if (action.includes('updated')) return 'info';
  if (action.includes('login')) return 'primary';
  return 'grey';
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

async function fetchActivity() {
  loading.value = true;
  try {
    const response = await api.get('/admin/audit-logs/activity', {
      params: { days: days.value.value, page_size: 100 },
    });
    items.value = response.data.items;
  } catch {
    // handled by axios interceptor
  } finally {
    loading.value = false;
  }
}

onMounted(fetchActivity);
</script>
