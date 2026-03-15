<template>
  <q-layout view="lHh lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center tech-bg">
        <q-card class="callback-card q-pa-md glass-card">
          <q-card-section class="text-center">
            <q-spinner-dots color="primary" size="50px" />
            <div class="text-h6 q-mt-md text-white">Logging in...</div>
          </q-card-section>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from 'src/stores/auth';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';

const router = useRouter();
const authStore = useAuthStore();

onMounted(async () => {
  try {
    // Get code and state from URL
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    const state = urlParams.get('state');

    if (!code) {
      throw new Error('No authorization code received');
    }

    // Verify state
    const savedState = sessionStorage.getItem('oauth_state');
    if (state !== savedState) {
      throw new Error('Invalid state parameter');
    }

    // Exchange code for token
    const redirectUri = (window as unknown as Record<string, Record<string, string>>).__CONFIG__?.cognitoRedirectUri || `${window.location.origin}/auth/cognito/callback`;

    console.log('Exchanging code for token...', { code, redirectUri });

    const response = await api.post('/admin/auth/cognito/callback', null, {
      params: {
        code,
        state,
        redirect_uri: redirectUri,
      },
    });

    console.log('Token exchange response:', response.data);

    // Save access token (refresh token is set as HttpOnly cookie by the server)
    const { access_token, user } = response.data;
    authStore.accessToken = access_token;
    authStore.user = user;
    authStore.isAuthenticated = true;

    localStorage.setItem('access_token', access_token);

    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;

    // Clean up
    sessionStorage.removeItem('oauth_state');

    Notify.create({
      type: 'positive',
      message: 'Login successful',
      position: 'top',
    });

    // Redirect to dashboard
    await router.replace('/');
  } catch (error: unknown) {
    console.error('Cognito OAuth callback error:', error);

    const err = error as { response?: { data?: { detail?: string } }; message?: string };
    Notify.create({
      type: 'negative',
      message: err.response?.data?.detail || err.message || 'Cognito login failed',
      position: 'top',
    });

    // Redirect to login page
    await router.replace('/login');
  }
});
</script>

<style scoped lang="scss">
.tech-bg {
  background: url('/src/assets/acheron-blackhole.gif') center/cover no-repeat;
  position: relative;
  overflow: hidden;
}

.tech-bg::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 0;
}

.callback-card {
  width: 100%;
  max-width: 420px;
  position: relative;
  z-index: 1;
}

.glass-card {
  background: rgba(15, 23, 42, 0.7) !important;
  backdrop-filter: blur(20px);
  border: 1px solid rgba(0, 188, 212, 0.3);
  box-shadow:
    0 8px 32px 0 rgba(0, 0, 0, 0.37),
    0 0 20px rgba(0, 188, 212, 0.2),
    inset 0 0 20px rgba(0, 188, 212, 0.05);
  border-radius: 16px;
}
</style>
