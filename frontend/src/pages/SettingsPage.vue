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


    </div>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
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
</script>
