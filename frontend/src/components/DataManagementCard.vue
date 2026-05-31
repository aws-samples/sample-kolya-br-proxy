<template>
  <q-card>
    <q-card-section>
      <div class="text-h6 q-mb-md">Data Management</div>
      <div class="text-caption text-grey q-mb-lg">
        Export or import application configuration (users, teams, API tokens, alerts, Entra group mappings).
      </div>

      <!-- Export -->
      <div class="q-mb-lg">
        <div class="text-subtitle2 q-mb-sm">Export Configuration</div>
        <div class="text-body2 text-grey q-mb-sm">
          Download a JSON file containing all application settings and data.
        </div>
        <q-btn
          label="Download Export"
          icon="download"
          color="grey-8"
          unelevated
          :loading="exporting"
          @click="handleExport"
        />
      </div>

      <q-separator class="q-mb-lg" />

      <!-- Import -->
      <div>
        <div class="text-subtitle2 q-mb-sm">Import Configuration</div>
        <div class="text-body2 text-grey q-mb-md">
          Upload a previously exported JSON file to restore configuration.
        </div>

        <div class="row q-col-gutter-md items-end">
          <div class="col-12 col-sm-6">
            <q-file
              v-model="importFile"
              label="Select JSON file"
              outlined
              dense
              accept=".json"
              clearable
            >
              <template v-slot:prepend>
                <q-icon name="attach_file" />
              </template>
            </q-file>
          </div>

          <div class="col-12 col-sm-4">
            <q-select
              v-model="conflictStrategy"
              :options="strategyOptions"
              label="Conflict Strategy"
              outlined
              dense
              emit-value
              map-options
            />
          </div>

          <div class="col-12 col-sm-2">
            <q-btn
              label="Import"
              icon="upload"
              color="grey-8"
              unelevated
              :loading="importing"
              :disable="!importFile"
              @click="handleImport"
            />
          </div>
        </div>
      </div>
    </q-card-section>

    <!-- Import Results Dialog -->
    <q-dialog v-model="showResults" persistent>
      <q-card style="min-width: 600px; max-width: 800px;">
        <q-card-section>
          <div class="text-h6">Import Results</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-list dense separator>
            <q-item v-for="(result, section) in importResults" :key="section">
              <q-item-section>
                <q-item-label>{{ sectionLabels[section] || section }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row q-gutter-sm">
                  <q-badge v-if="result.created" color="positive" :label="`+${result.created}`" />
                  <q-badge v-if="result.skipped" color="grey" :label="`skipped ${result.skipped}`" />
                  <q-badge v-if="result.overwritten" color="warning" text-color="dark" :label="`updated ${result.overwritten}`" />
                  <q-badge v-if="result.errors?.length" color="negative" :label="`${result.errors.length} errors`" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>

          <!-- Failed entries — must be reconfigured manually -->
          <div v-if="hasErrors" class="q-mt-md">
            <q-banner class="bg-negative text-white q-mb-sm" dense rounded>
              <template v-slot:avatar>
                <q-icon name="error" />
              </template>
              {{ errorCount }} entr{{ errorCount === 1 ? 'y' : 'ies' }} failed to import and
              must be reconfigured manually.
            </q-banner>
            <q-list dense bordered class="rounded-borders">
              <template v-for="(result, section) in importResults" :key="'err-'+section">
                <q-item
                  v-for="(err, i) in (result.errors || [])"
                  :key="section + '-' + i"
                >
                  <q-item-section avatar>
                    <q-icon name="warning" color="negative" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label caption class="text-grey-7">
                      {{ sectionLabels[section] || section }}
                    </q-item-label>
                    <q-item-label class="text-negative">{{ err }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-list>
          </div>

          <!-- Generated Tokens -->
          <div v-if="generatedKeys.length" class="q-mt-lg">
            <q-banner class="bg-warning text-dark q-mb-sm" dense rounded>
              <template v-slot:avatar>
                <q-icon name="warning" />
              </template>
              Save these API tokens now — they cannot be shown again.
            </q-banner>

            <q-table
              :rows="generatedKeys"
              :columns="tokenColumns"
              flat
              dense
              hide-bottom
              :pagination="{ rowsPerPage: 0 }"
            >
              <template v-slot:body-cell-token="props">
                <q-td :props="props">
                  <code class="text-caption">{{ props.row.token }}</code>
                  <q-btn
                    flat
                    dense
                    round
                    icon="content_copy"
                    size="xs"
                    class="q-ml-xs"
                    @click="copyToken(props.row.token)"
                  />
                </q-td>
              </template>
            </q-table>
          </div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat label="Close" color="grey-8" @click="showResults = false" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { Notify, copyToClipboard } from 'quasar';
import { api } from 'src/boot/axios';
import { extractErrorMessage } from 'src/utils/error';

interface SectionResult {
  created: number;
  skipped: number;
  overwritten: number;
  errors: string[];
  generated_keys?: { name: string; user_email: string; token: string }[];
}

const exporting = ref(false);
const importing = ref(false);
const importFile = ref<File | null>(null);
const conflictStrategy = ref('skip');
const showResults = ref(false);
const importResults = ref<Record<string, SectionResult>>({});

const strategyOptions = [
  { label: 'Skip existing', value: 'skip' },
  { label: 'Overwrite existing', value: 'overwrite' },
];

const sectionLabels: Record<string, string> = {
  users: 'Users',
  teams: 'Teams',
  tokens: 'API Tokens',
  team_members: 'Team Members',
  alert_rules: 'Alert Rules',
  entra_group_mappings: 'Entra Group Mappings',
};

const tokenColumns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left' as const },
  { name: 'user_email', label: 'User', field: 'user_email', align: 'left' as const },
  { name: 'token', label: 'Token', field: 'token', align: 'left' as const },
];

const generatedKeys = computed(() => {
  return importResults.value.tokens?.generated_keys || [];
});

const errorCount = computed(() => {
  return Object.values(importResults.value).reduce(
    (sum, r) => sum + (r.errors?.length || 0),
    0,
  );
});

const hasErrors = computed(() => errorCount.value > 0);

async function handleExport() {
  exporting.value = true;
  try {
    const response = await api.get('/admin/data-management/export', {
      responseType: 'blob',
    });

    const disposition = response.headers['content-disposition'] || '';
    const match = disposition.match(/filename="(.+)"/);
    const filename = match ? match[1] : 'config_export.json';

    const blob = new Blob([response.data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    Notify.create({ type: 'positive', message: 'Export downloaded', position: 'top' });
  } catch (error: unknown) {
    Notify.create({
      type: 'negative',
      message: extractErrorMessage(error, 'Export failed'),
      position: 'top',
    });
  } finally {
    exporting.value = false;
  }
}

async function handleImport() {
  if (!importFile.value) return;

  importing.value = true;
  try {
    const formData = new FormData();
    formData.append('file', importFile.value);
    formData.append('conflict_strategy', conflictStrategy.value);

    const { data } = await api.post('/admin/data-management/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });

    importResults.value = data;
    showResults.value = true;
    importFile.value = null;

    if (hasErrors.value) {
      Notify.create({
        type: 'warning',
        message: `Import completed with ${errorCount.value} failed entr${errorCount.value === 1 ? 'y' : 'ies'} — see details`,
        position: 'top',
        timeout: 6000,
      });
    } else {
      Notify.create({ type: 'positive', message: 'Import completed', position: 'top' });
    }
  } catch (error: unknown) {
    Notify.create({
      type: 'negative',
      message: extractErrorMessage(error, 'Import failed'),
      position: 'top',
    });
  } finally {
    importing.value = false;
  }
}

function copyToken(token: string) {
  void copyToClipboard(token).then(() => {
    Notify.create({ type: 'positive', message: 'Copied to clipboard', position: 'top' });
  });
}
</script>
