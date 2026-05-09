<template>
  <div>
    <div v-for="perm in managePermissions" :key="perm.key" class="q-mb-md">
      <q-select
        :model-value="getDisplayValue(perm.key)"
        :options="getOptions(perm.key)"
        :label="perm.label"
        multiple
        outlined
        dense
        use-chips
        emit-value
        map-options
        option-value="value"
        option-label="label"
        @update:model-value="(v: string[]) => onSelectionChange(perm.key, v)"
      >
        <template v-slot:option="{ itemProps, opt, selected, toggleOption }">
          <q-item v-bind="itemProps">
            <q-item-section side>
              <q-checkbox :model-value="selected" @update:model-value="toggleOption(opt)" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ opt.label }}</q-item-label>
            </q-item-section>
          </q-item>
        </template>
      </q-select>
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
  { key: 'manage_api_keys', resourceKey: 'api_keys' as const, label: 'Manage API Keys' },
  { key: 'manage_teams', resourceKey: 'teams' as const, label: 'Manage Teams' },
  { key: 'manage_models', resourceKey: 'models' as const, label: 'Manage Models' },
];

function getOptions(key: string): ResourceOption[] {
  const perm = managePermissions.find((p) => p.key === key);
  if (!perm) return [];
  return props.resources[perm.resourceKey] || [];
}

function getAllIds(key: string): string[] {
  return getOptions(key).map((o) => o.value);
}

function getDisplayValue(key: string): string[] {
  const val = props.modelValue[key];
  if (val === 'all' || val === true) return getAllIds(key);
  if (Array.isArray(val)) return val;
  return [];
}

function onSelectionChange(key: string, newValues: string[]) {
  const allIds = getAllIds(key);
  if (newValues.length === 0) {
    update(key, 'none');
  } else if (newValues.length === allIds.length) {
    update(key, 'all');
  } else {
    update(key, newValues);
  }
}

function update(key: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value });
}
</script>
