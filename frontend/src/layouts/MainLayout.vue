<template>
  <q-layout view="lHh Lpr lFf" class="tech-layout">
    <q-header elevated class="tech-header">
      <q-toolbar>
        <q-btn
          flat
          dense
          round
          icon="menu"
          aria-label="Menu"
          @click="toggleLeftDrawer"
        />

        <q-toolbar-title>
          <div class="row items-center">
            <q-avatar size="28px" class="q-mr-sm">
              <img src="~assets/kbp.png" alt="KBP" />
            </q-avatar>
            <span class="title-text">Kolya BR Proxy</span>
          </div>
        </q-toolbar-title>

        <q-btn flat round dense icon="account_circle">
          <q-menu dark class="user-menu">
            <q-list dark class="user-menu-list" style="min-width: 200px; background: #292a2d">
              <q-item>
                <q-item-section>
                  <q-item-label>{{ user?.email }}</q-item-label>
                  <q-item-label caption>
                    Balance: ${{ user?.current_balance }}
                  </q-item-label>
                </q-item-section>
              </q-item>
              <q-separator />
              <q-item clickable v-close-popup @click="goToSettings">
                <q-item-section avatar>
                  <q-icon name="settings" />
                </q-item-section>
                <q-item-section>Settings</q-item-section>
              </q-item>
              <q-item clickable v-close-popup @click="handleLogout">
                <q-item-section avatar>
                  <q-icon name="logout" />
                </q-item-section>
                <q-item-section>Logout</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="leftDrawerOpen" show-if-above class="tech-drawer">
      <q-list>
        <q-item-label header class="text-weight-bold drawer-header">
          Admin Panel
        </q-item-label>

        <q-item
          v-for="link in menuLinks"
          :key="link.title"
          clickable
          :to="link.to"
          exact
          class="menu-item"
          active-class="menu-item-active"
        >
          <q-item-section avatar>
            <q-icon :name="link.icon" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ link.title }}</q-item-label>
            <q-item-label caption>{{ link.caption }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container class="tech-page-container">
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from 'src/stores/auth';

const router = useRouter();
const authStore = useAuthStore();

const leftDrawerOpen = ref(false);

const user = computed(() => authStore.currentUser);

const menuLinks = [
  {
    title: 'Dashboard',
    caption: 'Overview and usage statistics',
    icon: 'dashboard',
    to: '/',
  },
  {
    title: 'API Keys',
    caption: 'API Key management',
    icon: 'vpn_key',
    to: '/tokens',
  },
  {
    title: 'Models',
    caption: 'Model management',
    icon: 'psychology',
    to: '/models',
  },
  {
    title: 'Playground',
    caption: 'Test conversations',
    icon: 'chat',
    to: '/playground',
  },
  {
    title: 'Monitor',
    caption: 'Usage charts and analytics',
    icon: 'insights',
    to: '/monitor',
  },
  {
    title: 'Settings',
    caption: 'Account settings',
    icon: 'settings',
    to: '/settings',
  },
];

function toggleLeftDrawer() {
  leftDrawerOpen.value = !leftDrawerOpen.value;
}

async function goToSettings() {
  await router.push('/settings');
}

async function handleLogout() {
  void authStore.logout();
  await router.replace('/login');
}

onMounted(() => {
  void authStore.initializeAuth();
});
</script>

<style scoped lang="scss">
.tech-layout {
  background: #1e1e1e;
}

.tech-header {
  background: #1e1e1e !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  min-height: 64px;
}

.tech-drawer {
  background: #1e1e1e !important;
  border-right: 1px solid rgba(255, 255, 255, 0.1);
  padding: 8px 0;
}

.drawer-header {
  color: #9aa0a6;
  font-size: 11px;
  padding: 12px 20px 8px 20px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  font-weight: 500;
  margin-bottom: 4px;
}

.menu-item {
  margin: 2px 12px;
  border-radius: 24px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  color: #e8eaed;
  padding: 10px 16px;
  min-height: 44px;
}

.menu-item:hover {
  background: rgba(255, 255, 255, 0.08) !important;
}

.menu-item-active {
  background: rgba(255, 255, 255, 0.12) !important;
  color: #ffffff;
  font-weight: 500;
}

:deep(.q-drawer .q-list) {
  padding: 0;
}

:deep(.q-drawer .q-item__section--avatar) {
  min-width: 40px;
  padding-right: 12px;
}

:deep(.q-drawer .q-icon) {
  font-size: 20px;
}

:deep(.q-drawer__content) {
  background: #1e1e1e !important;
}

.tech-page-container {
  background: #1e1e1e;
  padding: 24px;
}

:deep(.q-item__label) {
  color: #e8eaed;
  font-size: 14px;
  font-weight: 400;
}

:deep(.q-item__label--caption) {
  color: #9aa0a6;
  font-size: 12px;
}

:deep(.q-toolbar) {
  min-height: 64px;
  padding: 0 16px;
}

:deep(.q-icon) {
  color: #e8eaed;
}

:deep(.q-btn) {
  text-transform: none;
}

:deep(.q-menu),
:deep(.q-menu__content) {
  background: #292a2d !important;
  border: none !important;
  border-radius: 8px;
  box-shadow: none !important;
}

:deep(.user-menu),
:deep(.user-menu .q-menu__content) {
  background: #292a2d !important;
}

:deep(.user-menu-list) {
  background: #292a2d !important;
}

:deep(.q-list) {
  background: transparent !important;
}

:deep(.q-item) {
  color: #e8eaed;
  border-radius: 4px;
  margin: 4px;
  transition: background 0.2s;
}

:deep(.q-item:hover) {
  background: rgba(255, 255, 255, 0.08) !important;
}

:deep(.q-item__label) {
  color: #e8eaed !important;
}

:deep(.q-separator) {
  background: rgba(255, 255, 255, 0.1);
}

.title-text {
  font-weight: 500;
  letter-spacing: -0.5px;
}

// 全局卡片样式
:deep(.q-card) {
  background: #292a2d !important;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

:deep(.q-page) {
  color: #e8eaed;
}

:deep(.text-h4),
:deep(.text-h5),
:deep(.text-h6) {
  color: #ffffff;
  font-weight: 500;
}

:deep(.text-caption) {
  color: #9aa0a6;
}

:deep(.q-stepper) {
  background: transparent !important;
}

:deep(.q-stepper__step-inner) {
  background: transparent !important;
}

:deep(.q-item) {
  color: #e8eaed;
}

:deep(.q-btn) {
  border-radius: 24px;
  text-transform: none;
  font-weight: 500;
  padding: 8px 24px;
  min-height: 40px;
}

:deep(.q-btn--standard) {
  background: #1976d2 !important;
  color: #ffffff;
}

:deep(.q-btn--standard:hover) {
  background: #1565c0 !important;
}

:deep(.q-btn--standard .q-icon),
:deep(.q-btn.bg-primary .q-icon),
:deep(.q-btn[color="primary"] .q-icon) {
  color: #ffffff !important;
}

:deep(.q-btn--flat) {
  background: rgba(255, 255, 255, 0.05);
}

:deep(.q-btn--flat:hover) {
  background: rgba(255, 255, 255, 0.1);
}

:deep(.q-btn--flat .q-icon) {
  color: #e8eaed !important;
}

:deep(.q-btn--outline) {
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #e8eaed;
}

:deep(.q-btn--outline:hover) {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.3);
}

:deep(.q-btn--outline .q-icon) {
  color: #e8eaed !important;
}

// 对话框和弹窗
:deep(.q-dialog__backdrop) {
  background: rgba(0, 0, 0, 0.7) !important;
}

:deep(.q-dialog .q-card),
:deep(.q-dialog__inner > div) {
  background: #292a2d !important;
  color: #e8eaed;
  border: none !important;
  box-shadow: none !important;
}

:deep(.q-dialog .q-card__section) {
  color: #e8eaed;
}

:deep(.q-dialog .q-card__actions) {
  background: #292a2d !important;
}

:deep(.q-dialog__title) {
  color: #ffffff;
}

:deep(.q-dialog__message) {
  color: #e8eaed;
}

// Quasar Dialog 插件
:deep(.q-dialog-plugin) {
  background: #292a2d !important;
  color: #e8eaed;
  border: none !important;
  box-shadow: none !important;
}

:deep(.q-dialog-plugin .q-dialog__title) {
  color: #ffffff;
}

:deep(.q-dialog-plugin .q-dialog__message) {
  color: #e8eaed;
}

// 表格
:deep(.q-table) {
  background: #292a2d !important;
  color: #e8eaed;
}

:deep(.q-table__card) {
  background: #292a2d !important;
  box-shadow: none;
}

:deep(.q-table__top) {
  background: transparent !important;
  color: #e8eaed;
}

:deep(.q-table__middle) {
  background: #292a2d !important;
}

:deep(.q-table thead tr),
:deep(.q-table tbody td) {
  border-color: rgba(255, 255, 255, 0.1) !important;
}

:deep(.q-table thead th) {
  color: #9aa0a6;
  font-weight: 500;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.5px;
  background: #292a2d !important;
}

:deep(.q-table tbody tr) {
  background: #292a2d !important;
}

:deep(.q-table tbody tr:hover) {
  background: rgba(255, 255, 255, 0.05) !important;
}

// 输入框
:deep(.q-field__control) {
  background: rgba(255, 255, 255, 0.05) !important;
  color: #e8eaed;
}

:deep(.q-field__native),
:deep(.q-field__native input),
:deep(.q-field__native textarea) {
  color: #e8eaed !important;
  background: transparent !important;
}

:deep(.q-field__label) {
  color: #9aa0a6 !important;
}

:deep(.q-field__control::before) {
  border-color: rgba(255, 255, 255, 0.2) !important;
}

:deep(.q-field--focused .q-field__control::before) {
  border-color: rgba(255, 255, 255, 0.4) !important;
}

:deep(.q-field--filled .q-field__control) {
  background: rgba(255, 255, 255, 0.05) !important;
}

:deep(.q-field--filled .q-field__control::before) {
  background: transparent !important;
}

:deep(.q-field--outlined .q-field__control) {
  background: transparent !important;
}

:deep(input:-webkit-autofill),
:deep(input:-webkit-autofill:hover),
:deep(input:-webkit-autofill:focus) {
  -webkit-box-shadow: 0 0 0 1000px #292a2d inset !important;
  -webkit-text-fill-color: #e8eaed !important;
  background-color: #292a2d !important;
}

// 分页
:deep(.q-table__bottom) {
  background: transparent !important;
  color: #9aa0a6;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding: 12px 16px;
}

:deep(.q-table__control) {
  color: #9aa0a6;
  font-size: 13px;
}

:deep(.q-table__bottom-item) {
  color: #9aa0a6;
}

:deep(.q-pagination) {
  color: #e8eaed;
}

:deep(.q-pagination__content button) {
  color: #e8eaed;
  border-radius: 4px;
  min-width: 32px;
  height: 32px;
}

:deep(.q-pagination__content button:hover) {
  background: rgba(255, 255, 255, 0.08);
}

:deep(.q-pagination__content .q-btn--active) {
  background: rgba(255, 255, 255, 0.12);
}

:deep(.q-select) {
  color: #e8eaed;
}

:deep(.q-select .q-field__native) {
  color: #e8eaed;
}

// 标签/徽章
:deep(.q-badge) {
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

// 分隔线
:deep(.q-separator) {
  background: rgba(255, 255, 255, 0.1) !important;
}

// 选择框
:deep(.q-select__dropdown-icon) {
  color: #9aa0a6;
}

// Tooltip
:deep(.q-tooltip) {
  background: #292a2d !important;
  color: #e8eaed;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}

// Notify
:deep(.q-notification) {
  background: #292a2d !important;
  color: #e8eaed;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
}

// 所有文本颜色统一
:deep(.text-grey-7),
:deep(.text-grey-8),
:deep(.text-grey-9) {
  color: #9aa0a6 !important;
}

:deep(.text-primary) {
  color: #1976d2 !important;
}

:deep(.text-secondary) {
  color: #26a69a !important;
}

:deep(.text-positive) {
  color: #21ba45 !important;
}

:deep(.text-negative) {
  color: #c10015 !important;
}

// Stepper 组件
:deep(.q-stepper__header) {
  background: transparent !important;
}

:deep(.q-stepper__tab) {
  color: #9aa0a6;
}

:deep(.q-stepper__tab--active) {
  color: #e8eaed;
}

:deep(.q-stepper__dot) {
  background: rgba(255, 255, 255, 0.1);
}

:deep(.q-stepper__dot--active) {
  background: #1976d2;
}

:deep(.q-stepper__line) {
  background: rgba(255, 255, 255, 0.1) !important;
}

// 代码块
:deep(pre),
:deep(code) {
  background: #1e1e1e !important;
  color: #e8eaed;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

// 列表项
:deep(.q-item__label) {
  color: #e8eaed;
}

:deep(.q-item__label--caption) {
  color: #9aa0a6 !important;
}

// 所有白色背景改为暗色
:deep(.bg-white) {
  background: #292a2d !important;
}

:deep(.bg-grey-1),
:deep(.bg-grey-2),
:deep(.bg-grey-3) {
  background: #1e1e1e !important;
}

// 确保所有输入框文字可见
:deep(input),
:deep(textarea),
:deep(select) {
  color: #e8eaed !important;
}

// 占位符文字
:deep(::placeholder) {
  color: #9aa0a6 !important;
  opacity: 1;
}

:deep(:-ms-input-placeholder) {
  color: #9aa0a6 !important;
}

:deep(::-ms-input-placeholder) {
  color: #9aa0a6 !important;
}

// 日期选择器
:deep(.q-date) {
  background: #292a2d !important;
  color: #e8eaed;
}

:deep(.q-date__header) {
  background: #1e1e1e !important;
  color: #e8eaed;
}

:deep(.q-date__view) {
  color: #e8eaed;
}

:deep(.q-date__calendar-item) {
  color: #e8eaed;
}

:deep(.q-date__calendar-item--in) {
  background: rgba(255, 255, 255, 0.05);
}

:deep(.q-date__range) {
  background: rgba(25, 118, 210, 0.2) !important;
}

// 弹出层
:deep(.q-popup-proxy) {
  background: #292a2d !important;
}

// 线性进度条
:deep(.q-linear-progress) {
  background: rgba(255, 255, 255, 0.1) !important;
}

// 徽章
:deep(.q-badge) {
  font-size: 11px;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 4px;
}

// 只读输入框
:deep(.q-field--readonly .q-field__control) {
  opacity: 0.6;
}
</style>
