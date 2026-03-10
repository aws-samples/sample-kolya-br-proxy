import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  // Auth routes (no layout)
  {
    path: '/login',
    component: () => import('pages/LoginPage.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/auth/microsoft/callback',
    component: () => import('pages/MicrosoftCallbackPage.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/auth/cognito/callback',
    component: () => import('pages/CognitoCallbackPage.vue'),
    meta: { requiresAuth: false },
  },

  // Main app routes (with layout)
  {
    path: '/',
    component: () => import('layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('pages/DashboardPage.vue'),
      },
      {
        path: 'tokens',
        name: 'tokens',
        component: () => import('pages/TokensPage.vue'),
      },
      {
        path: 'models',
        name: 'models',
        component: () => import('pages/ModelsPage.vue'),
      },
      {
        path: 'playground',
        name: 'playground',
        component: () => import('pages/PlaygroundPage.vue'),
      },
      {
        path: 'monitor',
        name: 'monitor',
        component: () => import('pages/MonitorPage.vue'),
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('pages/SettingsPage.vue'),
      },
    ],
  },

  // Always leave this as last one
  {
    path: '/:catchAll(.*)*',
    component: () => import('pages/ErrorNotFound.vue'),
  },
];

export default routes;
