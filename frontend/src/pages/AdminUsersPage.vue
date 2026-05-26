<template>
  <q-page padding>
    <div class="row items-center q-mb-lg">
      <div class="text-h5">Admin Users</div>
      <q-space />
      <q-btn v-if="!authStore.groupSyncEnabled" color="primary" icon="person_add" label="Invite Admin" @click="showInviteDialog = true" />
    </div>

    <q-table
      :rows="users"
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
      <template v-slot:body-cell-last_login_at="props">
        <q-td :props="props">
          {{ props.row.last_login_at ? new Date(props.row.last_login_at).toLocaleString() : 'Never' }}
        </q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn flat dense round size="xs" icon="edit" class="action-btn" @click="editUser(props.row)" />
          <q-btn flat dense round size="xs" icon="block" color="negative" class="action-btn" @click="deactivateUser(props.row)" v-if="props.row.role !== 'super_admin'" />
        </q-td>
      </template>
    </q-table>

    <!-- Invite Dialog -->
    <q-dialog v-model="showInviteDialog">
      <q-card dark style="min-width: 550px">
        <q-card-section>
          <div class="text-h6">Invite Admin</div>
        </q-card-section>
        <q-card-section>
          <q-input v-model="inviteForm.email" label="Email" type="email" outlined dark class="q-mb-md" />
          <q-input v-model="inviteForm.username" label="Username" outlined dark class="q-mb-md" hint="Cognito login username" />
          <q-input v-model="inviteForm.temp_password" label="Temporary Password" type="password" outlined dark class="q-mb-md" hint="User must change on first login" />
          <q-select v-model="inviteForm.role" :options="roleOptions" label="Role" outlined dark class="q-mb-md" />
          <div v-if="inviteForm.role === 'admin'" class="q-mb-md">
            <div class="text-subtitle2 q-mb-sm">Permissions</div>
            <PermissionEditor v-model="inviteForm.permissions" :resources="resources" />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" label="Invite" @click="submitInvite" :loading="submitting" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Invite Link Dialog -->
    <q-dialog v-model="showInviteLinkDialog">
      <q-card dark style="min-width: 450px">
        <q-card-section>
          <div class="text-h6">Invite Link</div>
        </q-card-section>
        <q-card-section>
          <p>Share this link with the invited admin:</p>
          <q-input :model-value="inviteLink" readonly outlined dense dark>
            <template v-slot:append>
              <q-btn flat dense icon="content_copy" @click="copyInviteLink" />
            </template>
          </q-input>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Close" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Edit Dialog -->
    <q-dialog v-model="showEditDialog">
      <q-card dark style="min-width: 550px">
        <q-card-section>
          <div class="text-h6">Edit {{ editForm.email }}</div>
        </q-card-section>
        <q-card-section>
          <q-select v-model="editForm.role" :options="roleOptions" label="Role" outlined dark class="q-mb-md" />
          <div v-if="editForm.role === 'admin'" class="q-mb-md">
            <div class="text-subtitle2 q-mb-sm">Permissions</div>
            <PermissionEditor v-model="editForm.permissions" :resources="resources" />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" label="Save" @click="submitEdit" :loading="submitting" />
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
import { useAuthStore } from 'src/stores/auth';

const authStore = useAuthStore();

interface AdminUser {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string;
  permissions: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

const users = ref<AdminUser[]>([]);
const loading = ref(false);
const submitting = ref(false);
const showInviteDialog = ref(false);
const showInviteLinkDialog = ref(false);
const showEditDialog = ref(false);
const inviteLink = ref('');
const resources = ref<Resources>({ api_keys: [], teams: [], models: [] });

const roleOptions = ['super_admin', 'admin'];

const columns = [
  { name: 'email', label: 'Email', field: 'email', align: 'left' as const },
  { name: 'role', label: 'Role', field: 'role', align: 'left' as const },
  { name: 'permissions', label: 'Permissions', field: 'permissions', align: 'left' as const },
  { name: 'last_login_at', label: 'Last Login', field: 'last_login_at', align: 'left' as const },
  { name: 'actions', label: 'Actions', field: 'id', align: 'center' as const },
];

function formatPermLabel(key: string, val: unknown): string {
  const name = key.replace(/^manage_/, '').replace(/_/g, ' ');
  if (val === 'all' || val === true) return name;
  if (Array.isArray(val)) return `${name} (${val.length})`;
  if (val === false) return '';
  return name;
}

const defaultPermissions = (): Record<string, unknown> => ({
  manage_api_keys: 'all', // pragma: allowlist secret
  manage_teams: 'all',
  manage_models: 'all',
  view_usage: true,
  view_monitor: true,
});

const inviteForm = ref({
  email: '',
  username: '',
  temp_password: '',
  role: 'admin',
  permissions: defaultPermissions(),
});

const editForm = ref({
  id: '',
  email: '',
  role: 'admin',
  permissions: defaultPermissions(),
});

async function fetchUsers() {
  loading.value = true;
  try {
    const response = await api.get('/admin/users');
    users.value = response.data;
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

function copyInviteLink() {
  void navigator.clipboard.writeText(inviteLink.value);
  Notify.create({ type: 'positive', message: 'Link copied', position: 'top' });
}

function buildPermissionsPayload(perms: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(perms)) {
    if (val === 'none' || val === false) continue;
    result[key] = val;
  }
  return result;
}

async function submitInvite() {
  submitting.value = true;
  try {
    const payload: Record<string, unknown> = {
      email: inviteForm.value.email,
      username: inviteForm.value.username,
      temp_password: inviteForm.value.temp_password,
      role: inviteForm.value.role,
    };
    if (inviteForm.value.role === 'admin') {
      payload.permissions = buildPermissionsPayload(inviteForm.value.permissions);
    }
    await api.post('/admin/users', payload);
    showInviteDialog.value = false;
    inviteLink.value = `${window.location.origin}/login`;
    showInviteLinkDialog.value = true;
    inviteForm.value = { email: '', username: '', temp_password: '', role: 'admin', permissions: defaultPermissions() };
    await fetchUsers();
  } catch (error: unknown) {
    Notify.create({ type: 'negative', message: extractErrorMessage(error), position: 'top' });
  } finally {
    submitting.value = false;
  }
}

function editUser(user: AdminUser) {
  const perms = defaultPermissions();
  if (user.permissions) {
    for (const key of Object.keys(perms)) {
      if (key in user.permissions) {
        const v = user.permissions[key];
        perms[key] = v === false ? 'none' : v;
      } else {
        perms[key] = 'none';
      }
    }
  }
  editForm.value = {
    id: user.id,
    email: user.email,
    role: user.role,
    permissions: perms,
  };
  showEditDialog.value = true;
}

async function submitEdit() {
  submitting.value = true;
  try {
    const payload: Record<string, unknown> = { role: editForm.value.role };
    if (editForm.value.role === 'admin') {
      payload.permissions = buildPermissionsPayload(editForm.value.permissions);
    }
    await api.put(`/admin/users/${editForm.value.id}`, payload);
    Notify.create({ type: 'positive', message: 'Admin updated', position: 'top' });
    showEditDialog.value = false;
    await fetchUsers();
  } catch (error: unknown) {
    Notify.create({ type: 'negative', message: extractErrorMessage(error), position: 'top' });
  } finally {
    submitting.value = false;
  }
}

async function deactivateUser(user: AdminUser) {
  if (!confirm(`Deactivate ${user.email}?`)) return;
  try {
    await api.delete(`/admin/users/${user.id}`);
    Notify.create({ type: 'positive', message: 'Admin deactivated', position: 'top' });
    await fetchUsers();
  } catch (error: unknown) {
    Notify.create({ type: 'negative', message: extractErrorMessage(error), position: 'top' });
  }
}

onMounted(async () => {
  await Promise.all([fetchUsers(), fetchResources()]);
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
