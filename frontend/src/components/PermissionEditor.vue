<template>
  <div>
    <div v-for="perm in managePermissions" :key="perm.key" class="q-mb-md">
      <q-select
        :model-value="getDisplayValue(perm.key)"
        :options="getOptions(perm.key)"
        :label="perm.label"
        :display-value="getDisplayText(perm.key)"
        multiple
        outlined
        dense
        dark
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
    <q-checkbox dark :model-value="!!modelValue.view_usage" @update:model-value="(v: boolean) => update('view_usage', v)" label="View Usage" />
    <q-checkbox dark :model-value="!!modelValue.view_monitor" @update:model-value="(v: boolean) => update('view_monitor', v)" label="View Monitor" />
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

const ALL_VALUE = '__all__';

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
  const resourceList = props.resources[perm.resourceKey] || [];
  return [{ label: 'All', value: ALL_VALUE }, ...resourceList];
}

function getResourceIds(key: string): string[] {
  const perm = managePermissions.find((p) => p.key === key);
  if (!perm) return [];
  return (props.resources[perm.resourceKey] || []).map((o) => o.value);
}

function isAll(key: string): boolean {
  const val = props.modelValue[key];
  return val === 'all' || val === true;
}

function getDisplayValue(key: string): string[] {
  if (isAll(key)) return [ALL_VALUE, ...getResourceIds(key)];
  const val = props.modelValue[key];
  if (Array.isArray(val)) return val;
  return [];
}

function getDisplayText(key: string): string {
  if (isAll(key)) return 'All';
  const val = props.modelValue[key];
  if (Array.isArray(val) && val.length > 0) return `${val.length} selected`;
  return 'None';
}

function onSelectionChange(key: string, newValues: string[]) {
  const oldValues = getDisplayValue(key);
  const hadAll = oldValues.includes(ALL_VALUE);
  const hasAll = newValues.includes(ALL_VALUE);
  const resourceIds = getResourceIds(key);

  if (!hadAll && hasAll) {
    // Checked "All"
    update(key, 'all');
  } else if (hadAll && !hasAll) {
    // Unchecked "All" — deselect everything
    update(key, 'none');
  } else if (hadAll && hasAll) {
    // Had All, still has All, but toggled an individual item off
    const withoutAll = newValues.filter((v) => v !== ALL_VALUE);
    if (withoutAll.length < resourceIds.length) {
      update(key, withoutAll);
    } else {
      update(key, 'all');
    }
  } else {
    // No "All" involved
    if (newValues.length === 0) {
      update(key, 'none');
    } else if (newValues.length === resourceIds.length) {
      update(key, 'all');
    } else {
      update(key, newValues);
    }
  }
}

function update(key: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value });
}
</script>
