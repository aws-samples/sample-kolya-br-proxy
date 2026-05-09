<template>
  <q-page padding>
    <div class="row items-center q-mb-lg">
      <div class="text-h5">Admin Users</div>
      <q-space />
      <q-btn color="primary" icon="person_add" label="Invite Admin" @click="showInviteDialog = true" />
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
              :label="String(key)"
              class="q-mr-xs"
            />
          </template>
          <template v-else>
            <span class="text-grey">none</span>
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
          <q-btn flat dense icon="edit" @click="editUser(props.row)" />
          <q-btn flat dense icon="block" color="negative" @click="deactivateUser(props.row)" v-if="props.row.role !== 'super_admin'" />
        </q-td>
      </template>
    </q-table>

    <!-- Invite Dialog -->
    <q-dialog v-model="showInviteDialog">
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">Invite Admin</div>
        </q-card-section>
        <q-card-section>
          <q-input v-model="inviteForm.email" label="Email" type="email" outlined class="q-mb-md" />
          <q-select v-model="inviteForm.role" :options="roleOptions" label="Role" outlined class="q-mb-md" />
          <div v-if="inviteForm.role === 'admin'" class="q-mb-md">
            <div class="text-subtitle2 q-mb-sm">Permissions</div>
            <q-checkbox v-model="inviteForm.permissions.manage_api_keys" label="Manage API Keys" />
            <q-checkbox v-model="inviteForm.permissions.manage_teams" label="Manage Teams" />
            <q-checkbox v-model="inviteForm.permissions.manage_models" label="Manage Models" />
            <q-checkbox v-model="inviteForm.permissions.view_usage" label="View Usage" />
            <q-checkbox v-model="inviteForm.permissions.view_monitor" label="View Monitor" />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" label="Invite" @click="submitInvite" :loading="submitting" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Edit Dialog -->
    <q-dialog v-model="showEditDialog">
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">Edit {{ editForm.email }}</div>
        </q-card-section>
        <q-card-section>
          <q-select v-model="editForm.role" :options="roleOptions" label="Role" outlined class="q-mb-md" />
          <div v-if="editForm.role === 'admin'" class="q-mb-md">
            <div class="text-subtitle2 q-mb-sm">Permissions</div>
            <q-checkbox v-model="editForm.permissions.manage_api_keys" label="Manage API Keys" />
            <q-checkbox v-model="editForm.permissions.manage_teams" label="Manage Teams" />
            <q-checkbox v-model="editForm.permissions.manage_models" label="Manage Models" />
            <q-checkbox v-model="editForm.permissions.view_usage" label="View Usage" />
            <q-checkbox v-model="editForm.permissions.view_monitor" label="View Monitor" />
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

interface AdminUser {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string;
  permissions: Record<string, boolean> | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

const users = ref<AdminUser[]>([]);
const loading = ref(false);
const submitting = ref(false);
const showInviteDialog = ref(false);
const showEditDialog = ref(false);

const roleOptions = ['super_admin', 'admin'];

const columns = [
  { name: 'email', label: 'Email', field: 'email', align: 'left' as const },
  { name: 'role', label: 'Role', field: 'role', align: 'left' as const },
  { name: 'permissions', label: 'Permissions', field: 'permissions', align: 'left' as const },
  { name: 'last_login_at', label: 'Last Login', field: 'last_login_at', align: 'left' as const },
  { name: 'actions', label: 'Actions', field: 'id', align: 'center' as const },
];

const defaultPermissions = () => ({
  manage_api_keys: true,
  manage_teams: true,
  manage_models: true,
  view_usage: true,
  view_monitor: true,
});

const inviteForm = ref({
  email: '',
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

async function submitInvite() {
  submitting.value = true;
  try {
    const payload: Record<string, unknown> = {
      email: inviteForm.value.email,
      role: inviteForm.value.role,
    };
    if (inviteForm.value.role === 'admin') {
      payload.permissions = inviteForm.value.permissions;
    }
    await api.post('/admin/users', payload);
    Notify.create({ type: 'positive', message: 'Admin invited', position: 'top' });
    showInviteDialog.value = false;
    inviteForm.value = { email: '', role: 'admin', permissions: defaultPermissions() };
    await fetchUsers();
  } catch (error: unknown) {
    Notify.create({ type: 'negative', message: extractErrorMessage(error), position: 'top' });
  } finally {
    submitting.value = false;
  }
}

function editUser(user: AdminUser) {
  editForm.value = {
    id: user.id,
    email: user.email,
    role: user.role,
    permissions: user.permissions ? { ...defaultPermissions(), ...user.permissions } : defaultPermissions(),
  };
  showEditDialog.value = true;
}

async function submitEdit() {
  submitting.value = true;
  try {
    const payload: Record<string, unknown> = { role: editForm.value.role };
    if (editForm.value.role === 'admin') {
      payload.permissions = editForm.value.permissions;
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

onMounted(fetchUsers);
</script>
