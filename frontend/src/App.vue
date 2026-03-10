<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useAuthStore } from 'src/stores/auth';

const authStore = useAuthStore();

onMounted(() => {
  void authStore.initializeAuth();
});
</script>
