<template>
  <q-page padding>
    <div class="row items-center q-mb-lg">
      <div class="text-h5">Entra ID Group Mappings</div>
      <q-space />
      <q-btn color="primary" icon="add" label="Add Mapping" @click="openCreateDialog" />
    </div>

    <q-table
      :rows="mappings"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      :pagination="{ rowsPerPage: 20 }"
    >
      <template v-slot:body-cell-role="props">
        <q-td :props="props">
          <q-badge :color="props.row.role === 'super_admin' ? 'purple' : 'blue'" :label="props.row.role" />
        </q-td>
      </template>
      <template v-slot:body-cell-permissions="props">
        <q-td :props="props">
          <template v-if="props.row.role === 'super_admin'">
            <q-badge color="purple" label="all" />
          </template>
          <template v-else-if="props.row.permissions">
            <q-badge
              v-for="(val, key) in props.row.permissions"
              :key="key"
              :color="val ? 'positive' : 'grey'"
              :label="formatPermLabel(String(key), val)"
              class="q-mr-xs"
            />
          </template>
          <template v-else>
            <q-badge color="positive" label="all" />
          </template>
        </q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn flat dense round size="xs" icon="edit" class="action-btn" @click="openEditDialog(props.row)" />
          <q-btn flat dense round size="xs" icon="delete" color="negative" class="action-btn" @click="deleteMapping(props.row)" />
        </q-td>
      </template>
    </q-table>

    <!-- Create/Edit Dialog -->
    <q-dialog v-model="showDialog">
      <q-card dark style="min-width: 550px">
        <q-card-section>
          <div class="text-h6">{{ editingId ? 'Edit' : 'Add' }} Group Mapping</div>
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="form.entra_group_id"
            label="Entra Group ID"
            outlined
            dark
            class="q-mb-md"
            hint="Azure AD security group object ID"
            :disable="!!editingId"
          />
          <q-input
            v-model="form.group_name"
            label="Group Name"
            outlined
            dark
            class="q-mb-md"
            hint="Display name for this group"
          />
          <q-select
            v-model="form.role"
            :options="roleOptions"
            label="Role"
            outlined
            dark
            class="q-mb-md"
          />
          <q-input
            v-model.number="form.priority"
            label="Priority"
            type="number"
            outlined
            dark
            class="q-mb-md"
            hint="Higher priority wins when user is in multiple groups"
          />
          <div v-if="form.role === 'admin'" class="q-mb-md">
            <div class="text-subtitle2 q-mb-sm">Permissions</div>
            <PermissionEditor v-model="form.permissions" :resources="resources" />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" :label="editingId ? 'Save' : 'Create'" @click="submitForm" :loading="submitting" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';
import { extractErrorMessage } from 'src/utils/error';
import PermissionEditor from 'src/components/PermissionEditor.vue';
import type { Resources } from 'src/types/permissions';

interface GroupMapping {
  id: string;
  entra_group_id: string;
  group_name: string;
  role: string;
  permissions: Record<string, unknown> | null;
  priority: number;
  created_at: string;
  updated_at: string;
}

const mappings = ref<GroupMapping[]>([]);
const loading = ref(false);
const submitting = ref(false);
const showDialog = ref(false);
const editingId = ref<string | null>(null);
const resources = ref<Resources>({ api_keys: [], teams: [], models: [] });

const roleOptions = ['super_admin', 'admin'];

const columns = [
  { name: 'group_name', label: 'Group Name', field: 'group_name', align: 'left' as const },
  { name: 'entra_group_id', label: 'Group ID', field: 'entra_group_id', align: 'left' as const },
  { name: 'role', label: 'Role', field: 'role', align: 'left' as const },
  { name: 'permissions', label: 'Permissions', field: 'permissions', align: 'left' as const },
  { name: 'priority', label: 'Priority', field: 'priority', align: 'center' as const },
  { name: 'actions', label: 'Actions', field: 'id', align: 'center' as const },
];

const defaultPermissions = (): Record<string, unknown> => ({
  manage_api_keys: 'all',
  manage_teams: 'all',
  manage_models: 'all',
  view_usage: true,
  view_monitor: true,
});

const form = ref({
  entra_group_id: '',
  group_name: '',
  role: 'admin',
  priority: 0,
  permissions: defaultPermissions(),
});

function formatPermLabel(key: string, val: unknown): string {
  const name = key.replace(/^manage_/, '').replace(/_/g, ' ');
  if (val === 'all' || val === true) return name;
  if (Array.isArray(val)) return `${name} (${val.length})`;
  if (val === false) return '';
  return name;
}

function openCreateDialog() {
  editingId.value = null;
  form.value = {
    entra_group_id: '',
    group_name: '',
    role: 'admin',
    priority: 0,
    permissions: defaultPermissions(),
  };
  showDialog.value = true;
}

function openEditDialog(row: GroupMapping) {
  editingId.value = row.id;
  const perms = defaultPermissions();
  if (row.permissions) {
    for (const key of Object.keys(perms)) {
      if (key in row.permissions) {
        const v = row.permissions[key];
        perms[key] = v === false ? 'none' : v;
      } else {
        perms[key] = 'none';
      }
    }
  }
  form.value = {
    entra_group_id: row.entra_group_id,
    group_name: row.group_name,
    role: row.role,
    priority: row.priority,
    permissions: perms,
  };
  showDialog.value = true;
}

function buildPermissionsPayload(perms: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(perms)) {
    if (val === 'none' || val === false) continue;
    result[key] = val;
  }
  return result;
}

async function submitForm() {
  submitting.value = true;
  try {
    const payload: Record<string, unknown> = {
      group_name: form.value.group_name,
      role: form.value.role,
      priority: form.value.priority,
    };
    if (form.value.role === 'admin') {
      payload.permissions = buildPermissionsPayload(form.value.permissions);
    }

    if (editingId.value) {
      await api.put(`/admin/entra-groups/${editingId.value}`, payload);
      Notify.create({ type: 'positive', message: 'Mapping updated', position: 'top' });
    } else {
      payload.entra_group_id = form.value.entra_group_id;
      await api.post('/admin/entra-groups', payload);
      Notify.create({ type: 'positive', message: 'Mapping created', position: 'top' });
    }
    showDialog.value = false;
    await fetchMappings();
  } catch (error: unknown) {
    Notify.create({ type: 'negative', message: extractErrorMessage(error), position: 'top' });
  } finally {
    submitting.value = false;
  }
}

async function deleteMapping(row: GroupMapping) {
  if (!confirm(`Delete mapping for "${row.group_name}"?`)) return;
  try {
    await api.delete(`/admin/entra-groups/${row.id}`);
    Notify.create({ type: 'positive', message: 'Mapping deleted', position: 'top' });
    await fetchMappings();
  } catch (error: unknown) {
    Notify.create({ type: 'negative', message: extractErrorMessage(error), position: 'top' });
  }
}

async function fetchMappings() {
  loading.value = true;
  try {
    const response = await api.get('/admin/entra-groups');
    mappings.value = response.data;
  } catch {
    // handled by interceptor
  } finally {
    loading.value = false;
  }
}

async function fetchResources() {
  try {
    const res = await api.get('/admin/users/resources');
    const data = res.data;
    resources.value = {
      api_keys: (data.api_keys || []).map((t: { id: string; name: string }) => ({
        label: t.name,
        value: t.id,
      })),
      teams: (data.teams || []).map((t: { id: string; name: string }) => ({
        label: t.name,
        value: t.id,
      })),
      models: (data.models || []).map((m: { id: string; name: string }) => ({
        label: m.name,
        value: m.id,
      })),
    };
  } catch {
    // non-critical
  }
}

onMounted(async () => {
  await Promise.all([fetchMappings(), fetchResources()]);
});
</script>

<style scoped>
.action-btn {
  min-height: 24px !important;
  min-width: 24px !important;
  padding: 2px !important;
  font-size: 16px !important;
}
</style>
