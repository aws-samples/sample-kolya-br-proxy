<template>
  <q-layout view="lHh lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center tech-bg">
        <q-card class="login-card q-pa-md glass-card">
          <q-card-section class="text-center">
            <div class="text-h4 text-weight-bold text-primary q-mb-md">
              Kolya BR Proxy
            </div>
            <div class="text-subtitle1 text-grey-7">Admin Panel Login</div>
          </q-card-section>

          <q-card-section>
            <q-form class="q-gutter-md">
              <div class="text-center q-mb-md text-grey-7">Sign in with your account</div>

              <div class="login-buttons-container">
                <div class="login-btn-wrapper">
                  <q-btn
                    label="Login with AWS Cognito"
                    color="grey-8"
                    class="full-width login-btn"
                    @click="loginWithCognito"
                    unelevated
                    :loading="loadingCognito"
                  />
                </div>

                <div class="login-btn-wrapper">
                  <q-btn
                    label="Login with Microsoft Account"
                    color="grey-8"
                    class="full-width login-btn"
                    @click="loginWithMicrosoft"
                    outline
                    unelevated
                    :loading="loadingMicrosoft"
                  />
                </div>
              </div>
            </q-form>
          </q-card-section>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { api } from 'src/boot/axios';
import { Notify } from 'quasar';

const loadingCognito = ref(false);
const loadingMicrosoft = ref(false);

const loginWithCognito = async () => {
  try {
    loadingCognito.value = true;

    const redirectUri = (window as unknown as Record<string, Record<string, string>>).__CONFIG__?.cognitoRedirectUri || `${window.location.origin}/auth/cognito/callback`;

    console.log('Requesting Cognito login URL...', { redirectUri });

    const response = await api.get('/admin/auth/cognito/login', {
      params: { redirect_uri: redirectUri },
    });

    console.log('Cognito login response:', response.data);

    const { authorization_url, state } = response.data;

    // Save state for verification
    sessionStorage.setItem('oauth_state', state);

    // Redirect to Cognito login
    if (authorization_url) {
      console.log('Redirecting to:', authorization_url);
      const link = document.createElement('a');
      link.href = authorization_url;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } else {
      console.error('No authorization_url in response:', response.data);
      Notify.create({
        type: 'negative',
        message: 'Failed to get Cognito login link',
        position: 'top',
      });
    }
  } catch (error: unknown) {
    console.error('Cognito login error:', error);
    const err = error as { response?: { data?: { detail?: string } } };
    Notify.create({
      type: 'negative',
      message: err.response?.data?.detail || 'Cognito login failed',
      position: 'top',
    });
  } finally {
    loadingCognito.value = false;
  }
};

const loginWithMicrosoft = async () => {
  try {
    loadingMicrosoft.value = true;

    const redirectUri = (window as unknown as Record<string, Record<string, string>>).__CONFIG__?.microsoftRedirectUri || `${window.location.origin}/auth/microsoft/callback`;

    console.log('Requesting Microsoft login URL...', { redirectUri });

    const response = await api.get('/admin/auth/microsoft/login', {
      params: { redirect_uri: redirectUri },
    });

    console.log('Microsoft login response:', response.data);

    const { authorization_url, state } = response.data;

    // Save state for verification
    sessionStorage.setItem('oauth_state', state);

    // Redirect to Microsoft login
    if (authorization_url) {
      console.log('Redirecting to:', authorization_url);
      const link = document.createElement('a');
      link.href = authorization_url;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } else {
      console.error('No authorization_url in response:', response.data);
      Notify.create({
        type: 'negative',
        message: 'Failed to get Microsoft login link',
        position: 'top',
      });
    }
  } catch (error: unknown) {
    console.error('Microsoft login error:', error);
    const err = error as { response?: { data?: { detail?: string } } };
    Notify.create({
      type: 'negative',
      message: err.response?.data?.detail || 'Microsoft login failed',
      position: 'top',
    });
  } finally {
    loadingMicrosoft.value = false;
  }
};
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



.login-card {
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
  animation: cardFloat 3s ease-in-out infinite;
}

@keyframes cardFloat {
  0%, 100% {
    transform: translateY(0px);
  }
  50% {
    transform: translateY(-10px);
  }
}

:deep(.q-field__control) {
  background: rgba(30, 41, 59, 0.5) !important;
  border-color: rgba(59, 130, 246, 0.3) !important;
  transition: all 0.3s ease;
}

:deep(.q-field__control:hover) {
  border-color: rgba(0, 188, 212, 0.6) !important;
  box-shadow: 0 0 15px rgba(0, 188, 212, 0.3);
}

:deep(.q-field--focused .q-field__control) {
  border-color: #00bcd4 !important;
  box-shadow: 0 0 20px rgba(0, 188, 212, 0.5);
}

.login-buttons-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.login-btn-wrapper {
  transition: opacity 0.3s ease;
}

.login-buttons-container:hover .login-btn-wrapper {
  opacity: 0.4;
}

.login-buttons-container .login-btn-wrapper:hover {
  opacity: 1;
}

:deep(.q-btn) {
  background: linear-gradient(135deg, #2d3748 0%, #1a202c 100%) !important;
  border: 1px solid rgba(0, 188, 212, 0.3);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.4);
  transition: all 0.3s ease;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-weight: 600;
}

:deep(.login-btn-wrapper:hover .q-btn) {
  background: linear-gradient(135deg, #374151 0%, #2d3748 100%) !important;
  border-color: rgba(0, 188, 212, 0.6);
  box-shadow: 0 6px 25px rgba(0, 188, 212, 0.3);
  transform: translateY(-2px);
  color: #ffffff !important;
}

:deep(.text-primary) {
  color: #ffffff !important;
  text-decoration: none;
  transition: all 0.3s ease;
}

:deep(.text-primary:hover) {
  color: #4dd0e1 !important;
  text-shadow: 0 0 10px rgba(0, 188, 212, 0.5);
}

:deep(.text-h4) {
  color: #ffffff !important;
  text-shadow: 0 0 20px rgba(0, 188, 212, 0.6), 0 2px 4px rgba(0, 0, 0, 0.5);
}

:deep(.text-subtitle1) {
  color: rgba(255, 255, 255, 0.9) !important;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}

:deep(.q-field__label) {
  color: rgba(255, 255, 255, 0.8) !important;
}

:deep(.q-field__native) {
  color: #ffffff !important;
}

:deep(.q-icon) {
  color: #ffffff;
}

:deep(.q-field__control::before) {
  border-color: rgba(255, 255, 255, 0.3) !important;
}

:deep(input:-webkit-autofill),
:deep(input:-webkit-autofill:hover),
:deep(input:-webkit-autofill:focus),
:deep(input:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 1000px rgba(30, 41, 59, 0.5) inset !important;
  -webkit-text-fill-color: #ffffff !important;
  box-shadow: 0 0 0 1000px rgba(30, 41, 59, 0.5) inset !important;
  background-color: rgba(30, 41, 59, 0.5) !important;
  background-clip: content-box !important;
}
</style>
