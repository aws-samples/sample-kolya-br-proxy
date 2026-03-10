<template>
  <q-page class="q-pa-md">
    <div class="row items-center justify-between q-mb-md">
      <div class="text-h4">API Keys</div>
      <q-btn
        color="grey-8"
        icon="add"
        label="Create Key"
        @click="showCreateDialog = true"
        unelevated
      />
    </div>

    <!-- Keys List -->
    <q-card>
      <q-card-section>
        <q-table
          :rows="filteredTokens"
          :columns="columns"
          row-key="id"
          :loading="loading"
          flat
          bordered
        >
          <template v-slot:body-cell-id="props">
            <q-td :props="props">
              <div class="text-mono text-caption">{{ props.row.id }}</div>
            </q-td>
          </template>

          <template v-slot:body-cell-name="props">
            <q-td :props="props">
              <div class="text-weight-bold">{{ props.row.name }}</div>
            </q-td>
          </template>

          <template v-slot:body-cell-key="props">
            <q-td :props="props">
              <div class="row items-center no-wrap">
                <span class="text-mono">kbr_••••••••</span>
                <q-btn
                  flat
                  dense
                  round
                  size="sm"
                  icon="content_copy"
                  color="grey-7"
                  @click="copyTokenKey(props.row)"
                  :loading="copyingTokenId === props.row.id"
                  class="q-ml-xs"
                >
                  <q-tooltip>Copy Key</q-tooltip>
                </q-btn>
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-badge
                :color="getStatusColor(props.row)"
                :label="getStatusLabel(props.row)"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-quota="props">
            <q-td :props="props">
              <div v-if="props.row.quota_usd">
                ${{ props.row.used_usd }} / ${{ props.row.quota_usd }}
                <q-linear-progress
                  :value="getQuotaProgress(props.row)"
                  :color="getQuotaColor(props.row)"
                  class="q-mt-xs"
                />
              </div>
              <div v-else class="text-grey-7">Unlimited</div>
            </q-td>
          </template>

          <template v-slot:body-cell-expires_at="props">
            <q-td :props="props">
              <div v-if="props.row.expires_at">
                {{ formatDate(props.row.expires_at) }}
              </div>
              <div v-else class="text-grey-7">Never expires</div>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                flat
                dense
                round
                icon="account_balance_wallet"
                color="positive"
                @click="rechargeToken(props.row)"
                class="q-mr-xs"
              >
                <q-tooltip>Recharge</q-tooltip>
              </q-btn>
              <q-btn
                flat
                dense
                round
                icon="delete"
                color="negative"
                @click="deleteToken(props.row)"
                :loading="deletingTokenId === props.row.id"
              >
                <q-tooltip>Delete</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- Recharge Dialog -->
    <q-dialog v-model="showEditDialog">
      <q-card dark style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">Recharge Quota</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="text-caption text-grey-7 q-mb-md">
            Token: {{ editingToken?.name }}
          </div>

          <div class="q-mb-md">
            <div class="text-caption text-grey-7">Current Quota</div>
            <div class="text-h6 text-primary">
              ${{ editingToken?.quota_usd || '0.00' }}
            </div>
          </div>

          <q-input
            v-model.number="rechargeAmount"
            label="Recharge Amount (USD)"
            outlined
            rounded
            dark
            type="text"
            hint="Enter amount to add"
          />

          <div class="q-mt-md text-caption text-grey-7">
            Quota after recharge: ${{ calculateNewQuota() }}
          </div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn label="Cancel" flat v-close-popup />
          <q-btn
            label="Recharge"
            color="positive"
            @click="saveRecharge"
            :loading="updating"
            :disable="!rechargeAmount || rechargeAmount <= 0"
            unelevated
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Create Key Dialog -->
    <q-dialog v-model="showCreateDialog">
      <q-card dark style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">Create API Key</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit="handleCreateToken">
            <q-input
              v-model="newToken.name"
              label="Key Name"
              outlined
              rounded
              dark
              :rules="[(val) => !!val || 'Please enter name']"
              class="q-mb-md"
            />

            <q-input
              v-model.number="newToken.quota_usd"
              label="Quota (USD)"
              outlined
              rounded
              dark
              type="text"
              hint="Leave empty for unlimited"
              class="q-mb-md"
            />

            <q-input
              v-model="newToken.expires_at"
              label="Expiration Time"
              outlined
              rounded
              dark
              hint="Leave empty for never expires"
              class="q-mb-md"
            >
              <template v-slot:append>
                <q-icon name="event" class="cursor-pointer">
                  <q-popup-proxy
                    cover
                    transition-show="scale"
                    transition-hide="scale"
                  >
                    <q-date dark v-model="newToken.expires_at" mask="YYYY-MM-DD">
                      <div class="row items-center justify-end">
                        <q-btn v-close-popup label="OK" color="grey-8" unelevated />
                      </div>
                    </q-date>
                  </q-popup-proxy>
                </q-icon>
              </template>
            </q-input>

            <div class="row justify-end q-mt-md q-gutter-sm">
              <q-btn label="Cancel" flat v-close-popup />
              <q-btn
                label="Create"
                type="submit"
                color="grey-8"
                :loading="creating"
                unelevated
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Display Key Dialog -->
    <q-dialog v-model="showKeyDialog">
      <q-card dark style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">API Key</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-input
            v-model="displayKey"
            outlined
            rounded
            readonly
            type="textarea"
            rows="3"
            dark
          />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn
            label="Copy"
            color="grey-8"
            @click="copyDisplayKey"
            unelevated
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useTokensStore } from 'src/stores/tokens';
import { Notify, Dialog } from 'quasar';
import { getApiBaseUrl } from 'src/utils/api';
import type { APIToken, CreateTokenRequest } from 'src/stores/tokens';

const tokensStore = useTokensStore();

const showCreateDialog = ref(false);
const showEditDialog = ref(false);
const showKeyDialog = ref(false);
const displayKey = ref('');
const creating = ref(false);
const updating = ref(false);
const editingToken = ref<APIToken | null>(null);
const rechargeAmount = ref<number | undefined>(undefined);
const copyingTokenId = ref<string | null>(null);
const deletingTokenId = ref<string | null>(null);

const newToken = ref({
  name: '',
  quota_usd: undefined as number | undefined,
  expires_at: '',
});

const columns = [
  {
    name: 'id',
    label: 'ID',
    field: 'id',
    align: 'left' as const,
  },
  {
    name: 'name',
    label: 'Name',
    field: 'name',
    align: 'left' as const,
  },
  {
    name: 'key',
    label: 'Key',
    field: 'token_hash',
    align: 'left' as const,
  },
  {
    name: 'status',
    label: 'Status',
    field: 'is_active',
    align: 'center' as const,
  },
  {
    name: 'quota',
    label: 'Quota Usage',
    field: 'quota_usd',
    align: 'left' as const,
  },
  {
    name: 'expires_at',
    label: 'Expiration',
    field: 'expires_at',
    align: 'left' as const,
  },
  {
    name: 'actions',
    label: 'Actions',
    field: 'id',
    align: 'center' as const,
  },
];

const tokens = computed(() => tokensStore.tokens);
const loading = computed(() => tokensStore.loading);
const filteredTokens = computed(() => {
  return tokens.value.filter(token => token.is_active);
});

function getStatusColor(token: APIToken) {
  if (!token.is_active) return 'grey';
  if (token.is_expired) return 'negative';
  if (token.is_quota_exceeded) return 'warning';
  return 'positive';
}

function getStatusLabel(token: APIToken) {
  if (!token.is_active) return 'Revoked';
  if (token.is_expired) return 'Expired';
  if (token.is_quota_exceeded) return 'Quota Exceeded';
  return 'Active';
}

function getQuotaProgress(token: APIToken) {
  if (!token.quota_usd) return 0;
  return parseFloat(token.used_usd) / parseFloat(token.quota_usd);
}

function getQuotaColor(token: APIToken) {
  const progress = getQuotaProgress(token);
  if (progress >= 0.9) return 'negative';
  if (progress >= 0.7) return 'warning';
  return 'positive';
}

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleString('zh-CN');
}

async function handleCreateToken() {
  creating.value = true;
  try {
    const tokenData: CreateTokenRequest = {
      name: newToken.value.name,
    };

    if (newToken.value.quota_usd !== undefined) {
      tokenData.quota_usd = newToken.value.quota_usd;
    }
    if (newToken.value.expires_at) {
      tokenData.expires_at = newToken.value.expires_at;
    }

    // createToken will automatically refresh the list
    const result = await tokensStore.createToken(tokenData);

    if (result) {
      // Close dialog
      showCreateDialog.value = false;

      // Reset form
      newToken.value = {
        name: '',
        quota_usd: undefined,
        expires_at: '',
      };
    }
  } finally {
    creating.value = false;
  }
}

async function copyTokenKey(token: APIToken) {
  copyingTokenId.value = token.id;
  try {
    const apiBaseUrl = getApiBaseUrl();

    // Get decrypted token from backend
    const response = await fetch(`${apiBaseUrl}/admin/tokens/${token.id}/plain`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
      },
    });

    if (!response.ok) {
      const text = await response.text();
      let error;
      try {
        error = JSON.parse(text);
      } catch {
        throw new Error(`HTTP ${response.status}: ${text}`);
      }

      if (response.status === 500 && error.detail?.includes('decrypt')) {
        Notify.create({
          type: 'warning',
          message: 'This API Key was created before encryption was enabled and cannot be viewed. Please create a new key.',
          position: 'top',
          timeout: 3000,
        });
        return;
      }
      throw new Error(error.detail || 'Failed to fetch token');
    }

    const data = await response.json();

    // Show custom dialog
    displayKey.value = data.token;
    showKeyDialog.value = true;

  } catch (err) {
    Notify.create({
      type: 'negative',
      message: 'Failed to retrieve: ' + (err instanceof Error ? err.message : 'Unknown error'),
      position: 'top',
    });
  } finally {
    copyingTokenId.value = null;
  }
}

async function copyDisplayKey() {
  try {
    // Try using modern Clipboard API
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(displayKey.value);
      showKeyDialog.value = false;
      Notify.create({
        type: 'positive',
        message: 'API Key copied to clipboard',
        position: 'top',
      });
      return;
    }

    // Fallback to traditional method
    const input = document.createElement('input');
    input.value = displayKey.value;
    input.style.position = 'absolute';
    input.style.left = '-9999px';
    input.setAttribute('readonly', '');
    document.body.appendChild(input);

    input.select();
    input.setSelectionRange(0, 99999);

    const successful = document.execCommand('copy');
    document.body.removeChild(input);

    if (successful) {
      showKeyDialog.value = false;
      Notify.create({
        type: 'positive',
        message: 'API Key copied to clipboard',
        position: 'top',
      });
    } else {
      throw new Error('Copy command failed');
    }
  } catch (err) {
    console.error('Copy error:', err);
    Notify.create({
      type: 'negative',
      message: 'Copy failed, please select and copy manually',
      position: 'top',
    });
  }
}

function rechargeToken(token: APIToken) {
  editingToken.value = token;
  rechargeAmount.value = undefined;
  showEditDialog.value = true;
}

function calculateNewQuota() {
  if (!editingToken.value) return '0.00';
  const currentQuota = editingToken.value.quota_usd ? parseFloat(editingToken.value.quota_usd) : 0;
  const recharge = rechargeAmount.value || 0;
  return (currentQuota + recharge).toFixed(2);
}

async function saveRecharge() {
  if (!editingToken.value || !rechargeAmount.value) return;

  updating.value = true;
  try {
    const currentQuota = editingToken.value.quota_usd ? parseFloat(editingToken.value.quota_usd) : 0;
    const newQuota = currentQuota + rechargeAmount.value;

    const updateData: Partial<CreateTokenRequest> = {
      quota_usd: newQuota,
    };

    const success = await tokensStore.updateToken(editingToken.value.id, updateData);

    if (success) {
      showEditDialog.value = false;
      Notify.create({
        type: 'positive',
        message: `Recharge successful! New quota: $${newQuota.toFixed(2)}`,
        position: 'top',
      });
    }
  } finally {
    updating.value = false;
  }
}

function deleteToken(token: APIToken) {
  Dialog.create({
    title: 'Delete Token',
    message: `Are you sure you want to permanently delete Token "${token.name}"? This action cannot be undone!`,
    cancel: {
      label: 'Cancel',
      color: 'grey-7',
      flat: true,
    },
    ok: {
      label: 'Confirm',
      color: 'negative',
      unelevated: true,
    },
    persistent: true,
    dark: true,
    class: 'flat-dialog',
  }).onOk(() => {
    deletingTokenId.value = token.id;
    void tokensStore.deleteToken(token.id).finally(() => {
      deletingTokenId.value = null;
    });
  });
}

onMounted(async () => {
  await tokensStore.fetchTokens();
});
</script>

<style scoped lang="scss">
.text-mono {
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: #9aa0a6;
}
</style>

<style lang="scss">
.flat-dialog .q-card {
  box-shadow: none !important;
}
</style>
