<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Settings</div>

    <div class="row q-col-gutter-md">
      <!-- Personal Information -->
      <div class="col-12 col-md-6">
        <q-card>
          <q-card-section>
            <div class="text-h6 q-mb-md">Personal Information</div>
            <q-form>
              <q-input
                v-model="user.email"
                label="Email"
                outlined
                readonly
                class="q-mb-md"
              />

              <q-input
                v-model="user.first_name"
                label="First Name"
                outlined
                class="q-mb-md"
              />

              <q-input
                v-model="user.last_name"
                label="Last Name"
                outlined
                class="q-mb-md"
              />

              <div class="row items-center q-mb-md">
                <q-icon
                  :name="user.email_verified ? 'check_circle' : 'cancel'"
                  :color="user.email_verified ? 'positive' : 'negative'"
                  size="sm"
                  class="q-mr-sm"
                />
                <span>
                  Email {{ user.email_verified ? 'verified' : 'not verified' }}
                </span>
              </div>

              <q-btn
                label="Save"
                color="grey-8"
                @click="saveProfile"
                :loading="saving"
                unelevated
              />
            </q-form>
          </q-card-section>
        </q-card>
      </div>

      <!-- Change Password -->
      <div class="col-12 col-md-6">
        <q-card>
          <q-card-section>
            <div class="text-h6 q-mb-md">Change Password</div>
            <q-form @submit="changePassword">
              <q-input
                v-model="passwordForm.oldPassword"
                type="password"
                label="Current Password"
                outlined
                :rules="[(val) => !!val || 'Please enter current password']"
                class="q-mb-md"
              />

              <q-input
                v-model="passwordForm.newPassword"
                type="password"
                label="New Password"
                outlined
                :rules="[
                  (val) => !!val || 'Please enter new password',
                  (val) => val.length >= 8 || 'Password must be at least 8 characters',
                ]"
                class="q-mb-md"
              />

              <q-input
                v-model="passwordForm.confirmPassword"
                type="password"
                label="Confirm New Password"
                outlined
                :rules="[
                  (val) => !!val || 'Please confirm new password',
                  (val) =>
                    val === passwordForm.newPassword || 'Passwords do not match',
                ]"
                class="q-mb-md"
              />

              <q-btn
                label="Change Password"
                type="submit"
                color="grey-8"
                :loading="changingPassword"
                unelevated
              />
            </q-form>
          </q-card-section>
        </q-card>
      </div>


      <!-- Observability -->
      <div class="col-12">
        <q-card>
          <q-card-section>
            <div class="text-h6 q-mb-md">Observability</div>

            <div class="row q-col-gutter-md items-end">
              <!-- Log Level -->
              <div class="col-12 col-sm-4">
                <q-select
                  v-model="obs.log_level"
                  :options="logLevelOptions"
                  label="Log Level"
                  outlined
                  dense
                  emit-value
                  map-options
                  :loading="obsLoading"
                />
              </div>

              <!-- Metrics Toggle -->
              <div class="col-12 col-sm-4">
                <div class="text-caption text-grey q-mb-xs">CloudWatch Metrics</div>
                <q-toggle
                  v-model="obs.metrics_enabled"
                  :label="obs.metrics_enabled ? 'Enabled' : 'Disabled'"
                  dense
                  :disable="obsLoading"
                />
              </div>

              <!-- Save Button -->
              <div class="col-12 col-sm-4">
                <q-btn
                  label="Apply"
                  color="grey-8"
                  unelevated
                  :loading="obsSaving"
                  :disable="!obsChanged"
                  @click="saveObservability"
                />
              </div>
            </div>

            <!-- Read-only info -->
            <div class="q-mt-md text-caption text-grey">
              Log Format: <strong>{{ obs.log_format }}</strong> &nbsp;|&nbsp;
              Tracing: <strong>{{ obs.tracing_exporter }}</strong>
              <span class="q-ml-sm">(require restart to change)</span>
            </div>
          </q-card-section>
        </q-card>
      </div>

    </div>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useAuthStore } from 'src/stores/auth';
import { Notify } from 'quasar';
import { api } from 'src/boot/axios';

const authStore = useAuthStore();

const saving = ref(false);
const changingPassword = ref(false);

const user = computed(() => authStore.currentUser || {
  id: '',
  email: '',
  first_name: '',
  last_name: '',
  email_verified: false,
  current_balance: '0.00',
  is_active: false,
});

const passwordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
});

async function saveProfile() {
  saving.value = true;
  try {
    const response = await api.put('/admin/auth/me', {
      first_name: user.value.first_name,
      last_name: user.value.last_name,
    });

    // Update auth store with new user data
    authStore.updateUser(response.data);

    Notify.create({
      type: 'positive',
      message: 'Personal information saved',
      position: 'top',
    });
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } } };
    Notify.create({
      type: 'negative',
      message: err.response?.data?.detail || 'Save failed',
      position: 'top',
    });
  } finally {
    saving.value = false;
  }
}

async function changePassword() {
  changingPassword.value = true;
  try {
    await api.post('/admin/auth/change-password', {
      old_password: passwordForm.value.oldPassword,
      new_password: passwordForm.value.newPassword,
    });

    Notify.create({
      type: 'positive',
      message: 'Password changed',
      position: 'top',
    });

    // Reset form
    passwordForm.value = {
      oldPassword: '',
      newPassword: '',
      confirmPassword: '',
    };
  } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } } };
    Notify.create({
      type: 'negative',
      message: err.response?.data?.detail || 'Failed to change password',
      position: 'top',
    });
  } finally {
    changingPassword.value = false;
  }
}

// --- Observability ---

const logLevelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
];

const obsLoading = ref(false);
const obsSaving = ref(false);

const obs = ref({
  log_level: 'INFO',
  log_format: 'text',
  metrics_enabled: false,
  tracing_exporter: 'disabled',
});

// Snapshot of server state to detect changes
const obsOriginal = ref({ log_level: 'INFO', metrics_enabled: false });

const obsChanged = computed(
  () =>
    obs.value.log_level !== obsOriginal.value.log_level ||
    obs.value.metrics_enabled !== obsOriginal.value.metrics_enabled,
);

async function loadObservability() {
  obsLoading.value = true;
  try {
    const { data } = await api.get('/admin/observability');
    obs.value.log_level = data.log_level;
    obs.value.log_format = data.log_format;
    obs.value.metrics_enabled = data.metrics_enabled;
    obs.value.tracing_exporter = data.tracing_exporter;
    obsOriginal.value = {
      log_level: data.log_level,
      metrics_enabled: data.metrics_enabled,
    };
  } catch {
    // Silently fail — section will show defaults
  } finally {
    obsLoading.value = false;
  }
}

async function saveObservability() {
  obsSaving.value = true;
  try {
    const payload: Record<string, unknown> = {};
    if (obs.value.log_level !== obsOriginal.value.log_level) {
      payload.log_level = obs.value.log_level;
    }
    if (obs.value.metrics_enabled !== obsOriginal.value.metrics_enabled) {
      payload.enable_metrics = obs.value.metrics_enabled;
    }

    await api.put('/admin/observability', payload);

    obsOriginal.value = {
      log_level: obs.value.log_level,
      metrics_enabled: obs.value.metrics_enabled,
    };

    Notify.create({
      type: 'positive',
      message: 'Observability settings updated',
      position: 'top',
    });
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: string } } };
    Notify.create({
      type: 'negative',
      message: err.response?.data?.error || 'Failed to update settings',
      position: 'top',
    });
  } finally {
    obsSaving.value = false;
  }
}

onMounted(() => {
  void loadObservability();
});
</script>
