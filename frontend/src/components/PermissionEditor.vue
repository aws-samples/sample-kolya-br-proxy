<template>
  <div>
    <div v-for="perm in managePermissions" :key="perm.key" class="q-mb-md">
      <div class="text-caption text-weight-medium q-mb-xs">{{ perm.label }}</div>
      <q-btn-toggle
        :model-value="getScope(perm.key)"
        @update:model-value="(v: string) => setScope(perm.key, v)"
        :options="scopeToggleOptions"
        dense
        no-caps
        toggle-color="primary"
        class="q-mb-xs"
      />
      <q-select
        v-if="getScope(perm.key) === 'custom'"
        :model-value="getSelectedIds(perm.key)"
        @update:model-value="(v: string[]) => setSelectedIds(perm.key, v)"
        :options="getResourceOptions(perm.key)"
        multiple
        emit-value
        map-options
        outlined
        dense
        use-chips
        class="q-mt-xs"
        :label="`Select ${perm.label.replace('Manage ', '')}`"
      />
    </div>
    <q-separator class="q-my-sm" />
    <q-checkbox :model-value="!!modelValue.view_usage" @update:model-value="(v: boolean) => update('view_usage', v)" label="View Usage" />
    <q-checkbox :model-value="!!modelValue.view_monitor" @update:model-value="(v: boolean) => update('view_monitor', v)" label="View Monitor" />
  </div>
</template>

<script setup lang="ts">
interface ResourceOption {
  label: string;
  value: string;
}

interface Resources {
  api_keys: ResourceOption[];
  teams: ResourceOption[];
  models: ResourceOption[];
}

const props = defineProps<{
  modelValue: Record<string, unknown>;
  resources: Resources;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>];
}>();

const managePermissions = [
  { key: 'manage_api_keys', resourceKey: 'api_keys' },
  { key: 'manage_teams', resourceKey: 'teams' },
  { key: 'manage_models', resourceKey: 'models' },
].map((p) => ({
  ...p,
  label: p.key.replace(/^manage_/, '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
  get label() {
    return `Manage ${p.key.replace(/^manage_/, '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}`;
  },
}));

const scopeToggleOptions = [
  { label: 'All', value: 'all' },
  { label: 'Custom', value: 'custom' },
  { label: 'None', value: 'none' },
];

function getScope(key: string): string {
  const val = props.modelValue[key];
  if (val === 'all' || val === true) return 'all';
  if (val === 'none' || val === false || val === undefined) return 'none';
  if (Array.isArray(val)) return 'custom';
  return 'none';
}

function getSelectedIds(key: string): string[] {
  const val = props.modelValue[key];
  return Array.isArray(val) ? val : [];
}

function getResourceOptions(key: string): ResourceOption[] {
  const perm = managePermissions.find((p) => p.key === key);
  if (!perm) return [];
  return props.resources[perm.resourceKey as keyof Resources] || [];
}

function update(key: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value });
}

function setScope(key: string, scope: string) {
  if (scope === 'all') {
    update(key, 'all');
  } else if (scope === 'none') {
    update(key, 'none');
  } else {
    update(key, getSelectedIds(key));
  }
}

function setSelectedIds(key: string, ids: string[]) {
  update(key, ids);
}
</script>
