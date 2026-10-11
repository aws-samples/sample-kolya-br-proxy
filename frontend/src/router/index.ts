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
  if (process.env.SERVER) {
    createHistory = createMemoryHistory;
  } else if (process.env.VUE_ROUTER_MODE === 'history') {
    createHistory = createWebHistory;
  }

  const Router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,

    // Leave this as is and make changes in quasar.conf.js instead!
    // quasar.conf.js -> build -> vueRouterMode
    // quasar.conf.js -> build -> publicPath
    history: createHistory(process.env.VUE_ROUTER_BASE),
  });

  // Navigation guard for authentication
  Router.beforeEach((to, from, next) => {
    const requiresAuth = to.matched.some((record) => record.meta.requiresAuth);
    const requiresSuperAdmin = to.matched.some((record) => record.meta.requiresSuperAdmin);
    const storedCredential = localStorage.getItem(ACCESS_CREDENTIAL_STORAGE_KEY);

    if (requiresAuth && !storedCredential) {
      next('/login');
    } else if (!requiresAuth && storedCredential && to.path === '/login') {
      next('/');
    } else if (requiresSuperAdmin) {
      const authStore = useAuthStore();
      if (!authStore.isSuperAdmin) {
        next('/');
      } else {
        next();
      }
    } else {
      next();
    }
  });

  return Router;
});
