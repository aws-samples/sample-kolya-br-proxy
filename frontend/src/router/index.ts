import { defineRouter } from '#q-app';
import {
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
} from 'vue-router';
import { ACCESS_CREDENTIAL_STORAGE_KEY, useAuthStore } from '@/stores/auth';
import routes from './routes'; // pi-lens-ignore: find-import-file-without-extension

/*
 * If not building with SSR mode, you can
 * directly export the Router instantiation;
 *
 * The function below can be async too; either use
 * async/await or return a Promise which resolves
 * with the Router instance.
 */

export default defineRouter(function (/* { store, ssrContext } */) {
  let createHistory = createWebHashHistory;
  if (import.meta.env.QUASAR_SERVER) {
    createHistory = createMemoryHistory;
  } else if (import.meta.env.QUASAR_VUE_ROUTER_MODE === 'history') {
    createHistory = createWebHistory;
  }

  const Router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,

    // Leave this as is and make changes in quasar.conf.js instead!
    // quasar.conf.js -> build -> vueRouterMode
    // quasar.conf.js -> build -> publicPath
    history: createHistory(import.meta.env.QUASAR_VUE_ROUTER_BASE),
  });

  // Navigation guard for authentication
  Router.beforeEach(async (to, from, next) => {
    const requiresAuth = to.matched.some((record) => record.meta.requiresAuth);
    const requiresSuperAdmin = to.matched.some((record) => record.meta.requiresSuperAdmin);
    const requiresWrite = to.matched.some((record) => record.meta.requiresWrite);
    const storedCredential = localStorage.getItem(ACCESS_CREDENTIAL_STORAGE_KEY);

    if (requiresAuth && !storedCredential) {
      next('/login');
    } else if (!requiresAuth && storedCredential && to.path === '/login') {
      next('/');
    } else if (requiresSuperAdmin || requiresWrite) {
      const authStore = useAuthStore();
      // On a hard reload the user profile may not be loaded yet; role checks
      // against a null user would wrongly bounce privileged users to '/'.
      if (!authStore.user) {
        await authStore.initializeAuth();
      }
      const allowed =
        (!requiresSuperAdmin || authStore.canViewSuperAdminPages) &&
        (!requiresWrite || authStore.canWrite);
      if (allowed) {
        next();
      } else {
        next('/');
      }
    } else {
      next();
    }
  });

  return Router;
});
