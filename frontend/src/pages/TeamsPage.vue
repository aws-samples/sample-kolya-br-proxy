<template>
  <q-page class="q-pa-md">
    <!-- Team List View -->
    <template v-if="!selectedTeam">
      <div class="row items-center justify-between q-mb-md">
        <div class="text-h4">Teams</div>
        <q-btn
          color="grey-8"
          icon="add"
          label="Create Team"
          @click="showCreateDialog = true"
          unelevated
        />
      </div>

      <q-card>
        <q-card-section>
          <q-table
            :rows="teams"
            :columns="teamColumns"
            row-key="id"
            :loading="loading"
            flat
            bordered
          >
            <template v-slot:body-cell-name="props">
              <q-td :props="props">
                <a
                  class="text-weight-bold cursor-pointer text-primary"
                  @click="selectTeam(props.row.id)"
                >
                  {{ props.row.name }}
                </a>
              </q-td>
            </template>

            <template v-slot:body-cell-budget="props">
              <q-td :props="props">
                ${{ props.row.monthly_budget_usd }}
              </q-td>
            </template>

            <template v-slot:body-cell-used="props">
              <q-td :props="props">
                <div>${{ props.row.total_used_usd }}</div>
                <q-linear-progress
                  :value="getBudgetProgress(props.row)"
                  :color="getBudgetColor(props.row)"
                  class="q-mt-xs"
                  style="max-width: 120px"
                />
              </q-td>
            </template>

            <template v-slot:body-cell-unallocated="props">
              <q-td :props="props">
                ${{ props.row.unallocated_pool_usd }}
              </q-td>
            </template>

            <template v-slot:body-cell-policy="props">
              <q-td :props="props">
                <q-badge
                  :color="props.row.monthly_reset_policy === 'reset' ? 'blue-7' : 'teal-7'"
                  :label="props.row.monthly_reset_policy"
                />
              </q-td>
            </template>

            <template v-slot:body-cell-actions="props">
              <q-td :props="props">
                <q-btn
                  flat
                  dense
                  round
                  size="xs"
                  icon="edit"
                  color="grey-7"
                  @click.stop="editTeam(props.row)"
                  class="q-mr-xs"
                >
                  <q-tooltip>Edit Team</q-tooltip>
                </q-btn>
                <q-btn
                  flat
                  dense
                  round
                  size="xs"
                  icon="delete"
                  color="negative"
                  @click.stop="confirmDeleteTeam(props.row)"
                >
                  <q-tooltip>Delete Team</q-tooltip>
                </q-btn>
              </q-td>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </template>

    <!-- Team Dashboard View -->
    <template v-else>
      <div class="row items-center q-mb-md">
        <q-btn
          flat
          round
          icon="arrow_back"
          @click="teamsStore.currentTeam = null"
          class="q-mr-sm"
        />
        <div class="text-h4">{{ selectedTeam.name }}</div>
        <q-space />
        <q-btn
          color="grey-8"
          icon="playlist_add"
          label="Batch Create"
          @click="showBatchDialog = true"
          unelevated
          class="q-mr-sm"
        />
        <q-btn
          color="grey-8"
          icon="swap_horiz"
          label="Transfer"
          @click="showTransferDialog = true"
          unelevated
          :disable="selectedTeam.members.length < 2"
        />
      </div>

      <!-- Budget Summary -->
      <div class="row q-gutter-md q-mb-md">
        <q-card class="col">
          <q-card-section>
            <div class="text-caption text-grey-7">Monthly Budget</div>
            <div class="text-h5">${{ selectedTeam.monthly_budget_usd }}</div>
          </q-card-section>
        </q-card>
        <q-card class="col">
          <q-card-section>
            <div class="text-caption text-grey-7">Total Used</div>
            <div class="text-h5">${{ selectedTeam.total_used_usd }}</div>
          </q-card-section>
        </q-card>
        <q-card class="col">
          <q-card-section>
            <div class="text-caption text-grey-7">Unallocated Pool</div>
            <div class="text-h5">${{ selectedTeam.unallocated_pool_usd }}</div>
          </q-card-section>
        </q-card>
        <q-card v-if="selectedTeam.daily_limit_enabled" class="col">
          <q-card-section>
            <div class="text-caption text-grey-7">Daily Budget (team)</div>
            <div class="text-h5">${{ teamDailyBudget }}</div>
            <div class="text-caption text-grey-7">= monthly / {{ daysInMonth }} days</div>
          </q-card-section>
        </q-card>
        <q-card class="col">
          <q-card-section>
            <div class="text-caption text-grey-7">Reset Policy</div>
            <div class="text-h5">
              <q-badge
                :color="selectedTeam.monthly_reset_policy === 'reset' ? 'blue-7' : 'teal-7'"
                :label="selectedTeam.monthly_reset_policy"
                class="text-body1"
              />
            </div>
          </q-card-section>
        </q-card>
      </div>

      <!-- Members Table -->
      <q-card>
        <q-card-section>
          <div class="text-h6 q-mb-sm">Members</div>
          <q-table
            :rows="selectedTeam.members"
            :columns="memberColumns"
            row-key="token_id"
            :loading="loading"
            flat
            bordered
          >
            <template v-slot:body-cell-name="props">
              <q-td :props="props">
                <div class="text-weight-bold">{{ props.row.token_name }}</div>
              </q-td>
            </template>

            <template v-slot:body-cell-allocation="props">
              <q-td :props="props">
                ${{ Number(props.row.allocated_usd).toFixed(2) }}
              </q-td>
            </template>

            <template v-slot:body-cell-used="props">
              <q-td :props="props">
                <div>${{ Number(props.row.used_usd).toFixed(2) }} / ${{ Number(props.row.allocated_usd).toFixed(2) }}</div>
                <q-linear-progress
                  :value="getMemberProgress(props.row)"
                  :color="getMemberColor(props.row)"
                  class="q-mt-xs"
                  style="max-width: 120px"
                />
              </q-td>
            </template>

            <template v-slot:body-cell-remaining="props">
              <q-td :props="props">
                ${{ Number(props.row.remaining_usd).toFixed(2) }}
              </q-td>
            </template>

            <template v-slot:body-cell-daily="props">
              <q-td :props="props">
                <div>${{ Number(props.row.daily_used_usd).toFixed(2) }} / ${{ Number(props.row.daily_limit_usd).toFixed(2) }}</div>
              </q-td>
            </template>

            <template v-slot:body-cell-status="props">
              <q-td :props="props">
                <q-badge
                  :color="props.row.is_active ? 'positive' : 'grey'"
                  :label="props.row.is_active ? 'Active' : 'Inactive'"
                />
              </q-td>
            </template>

            <template v-slot:body-cell-actions="props">
              <q-td :props="props">
                <q-btn
                  flat
                  dense
                  round
                  size="xs"
                  icon="tune"
                  color="grey-7"
                  @click="openAdjustDialog(props.row)"
                  class="q-mr-xs"
                >
                  <q-tooltip>Adjust Allocation</q-tooltip>
                </q-btn>
                <q-btn
                  flat
                  dense
                  round
                  size="xs"
                  icon="person_remove"
                  color="negative"
                  @click="confirmRemoveMember(props.row)"
                >
                  <q-tooltip>Remove Member</q-tooltip>
                </q-btn>
              </q-td>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </template>

    <!-- Create Team Dialog -->
    <q-dialog v-model="showCreateDialog">
      <q-card dark style="min-width: 450px">
        <q-card-section>
          <div class="text-h6">Create Team</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-form @submit="handleCreateTeam">
            <q-input
              v-model="createForm.name"
              label="Team Name"
              outlined
              rounded
              dark
              :rules="[(val) => !!val || 'Required']"
              class="q-mb-md"
            />
            <q-input
              v-model="createForm.monthly_budget_usd"
              label="Monthly Budget (USD)"
              outlined
              rounded
              dark
              type="text"
              :rules="[(val) => !!val || 'Required']"
              class="q-mb-md"
            />
            <q-select
              v-model="createForm.monthly_reset_policy"
              :options="policyOptions"
              label="Reset Policy"
              outlined
              rounded
              dark
              emit-value
              map-options
              class="q-mb-md"
            />
            <q-item dark dense class="q-mb-md">
              <q-item-section>
                <q-item-label>Daily Use Limitation</q-item-label>
                <q-item-label caption>Limit each member's daily spending (allocation / days in month)</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-toggle v-model="createForm.daily_limit_enabled" dark />
              </q-item-section>
            </q-item>
            <div class="row justify-end q-gutter-sm">
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

    <!-- Edit Team Dialog -->
    <q-dialog v-model="showEditDialog">
      <q-card dark style="min-width: 450px">
        <q-card-section>
          <div class="text-h6">Edit Team</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-form @submit="handleUpdateTeam">
            <q-input
              v-model="editForm.name"
              label="Team Name"
              outlined
              rounded
              dark
              class="q-mb-md"
            />
            <q-input
              v-model="editForm.monthly_budget_usd"
              label="Monthly Budget (USD)"
              outlined
              rounded
              dark
              type="text"
              class="q-mb-md"
            />
            <q-select
              v-model="editForm.monthly_reset_policy"
              :options="policyOptions"
              label="Reset Policy"
              outlined
              rounded
              dark
              emit-value
              map-options
              class="q-mb-md"
            />
            <q-item dark dense class="q-mb-md">
              <q-item-section>
                <q-item-label>Daily Use Limitation</q-item-label>
                <q-item-label caption>Limit each member's daily spending (allocation / days in month)</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-toggle v-model="editForm.daily_limit_enabled" dark />
              </q-item-section>
            </q-item>
            <div class="row justify-end q-gutter-sm">
              <q-btn label="Cancel" flat v-close-popup />
              <q-btn
                label="Save"
                type="submit"
                color="grey-8"
                :loading="updating"
                unelevated
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>


    <!-- Adjust Allocation Dialog -->
    <q-dialog v-model="showAdjustDialog">
      <q-card dark style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">Adjust Allocation</div>
          <div class="text-caption text-grey-7 q-mt-xs">
            Member: {{ adjustForm.token_name }}
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <div class="q-mb-md">
            <div class="text-caption text-grey-7">Current Allocation</div>
            <div class="text-h6 text-primary">${{ adjustForm.current }}</div>
          </div>
          <div class="q-mb-md">
            <div class="text-caption text-grey-7">Unallocated Pool</div>
            <div class="text-body1">${{ selectedTeam?.unallocated_pool_usd }}</div>
          </div>
          <q-input
            v-model="adjustForm.new_amount"
            label="New Allocation (USD)"
            outlined
            rounded
            dark
            type="text"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn label="Cancel" flat v-close-popup />
          <q-btn
            label="Save"
            color="grey-8"
            @click="handleAdjust"
            :loading="adjusting"
            unelevated
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Transfer Dialog -->
    <q-dialog v-model="showTransferDialog">
      <q-card dark style="min-width: 450px">
        <q-card-section>
          <div class="text-h6">Transfer Allocation</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-form @submit="handleTransfer">
            <q-select
              v-model="transferForm.from_token_id"
              :options="memberOptions"
              label="From"
              outlined
              rounded
              dark
              emit-value
              map-options
              option-label="label"
              option-value="value"
              :rules="[(val) => !!val || 'Required']"
              class="q-mb-md"
            />
            <q-select
              v-model="transferForm.to_token_id"
              :options="memberOptions"
              label="To"
              outlined
              rounded
              dark
              emit-value
              map-options
              option-label="label"
              option-value="value"
              :rules="[(val) => !!val || 'Required', (val) => val !== transferForm.from_token_id || 'Must differ from source']"
              class="q-mb-md"
            />
            <q-input
              v-model="transferForm.amount"
              label="Amount (USD)"
              outlined
              rounded
              dark
              type="text"
              :rules="[(val) => !!val || 'Required']"
              class="q-mb-md"
            />
            <div class="row justify-end q-gutter-sm">
              <q-btn label="Cancel" flat v-close-popup />
              <q-btn
                label="Transfer"
                type="submit"
                color="grey-8"
                :loading="transferring"
                unelevated
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Batch Create Members Dialog -->
    <q-dialog v-model="showBatchDialog">
      <q-card dark style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">Batch Create Members</div>
          <div class="text-caption text-grey-7 q-mt-xs">
            Unallocated pool: ${{ selectedTeam?.unallocated_pool_usd }}
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-form @submit="handleBatchCreate">
            <q-input
              v-model="batchForm.names"
              label="Names"
              outlined
              rounded
              dark
              type="textarea"
              autogrow
              :rules="[(val) => !!val?.trim() || 'Required']"
              hint="Separate with comma or newline"
              class="q-mb-md"
            />
            <q-input
              :model-value="computedPerMemberAllocation"
              label="Allocation per Member (USD)"
              outlined
              rounded
              dark
              readonly
              hint="Auto-calculated: unallocated pool / member count"
              class="q-mb-md"
            />
            <q-input
              v-if="selectedTeam?.daily_limit_enabled"
              :model-value="computedPerMemberDaily"
              label="Daily Limit per Member (USD)"
              outlined
              rounded
              dark
              readonly
              :hint="`= ${computedPerMemberAllocation} / ${daysInMonth} days`"
              class="q-mb-md"
            />
            <q-select
              v-model="batchForm.model_names"
              :options="availableModelOptions"
              label="Models (optional)"
              outlined
              rounded
              dark
              multiple
              use-chips
              option-label="label"
              option-value="value"
              emit-value
              map-options
              :loading="modelsLoading"
              class="q-mb-md"
            />
            <div class="row justify-end q-gutter-sm">
              <q-btn label="Cancel" flat v-close-popup />
              <q-btn
                label="Create"
                type="submit"
                color="grey-8"
                :loading="batchCreating"
                unelevated
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useTeamsStore } from 'src/stores/teams';
import { useTokensStore } from 'src/stores/tokens';
import { useModelsStore } from 'src/stores/models';
import { Dialog } from 'quasar';
import type { TeamListItem, TeamMember } from 'src/stores/teams';

const teamsStore = useTeamsStore();
const tokensStore = useTokensStore();
const modelsStore = useModelsStore();

const selectedTeam = computed(() => teamsStore.currentTeam);
const teams = computed(() => teamsStore.teams);
const loading = computed(() => teamsStore.loading);
const modelsLoading = computed(() => modelsStore.loading);

const showCreateDialog = ref(false);
const showEditDialog = ref(false);
const showAdjustDialog = ref(false);
const showTransferDialog = ref(false);
const showBatchDialog = ref(false);

const creating = ref(false);
const updating = ref(false);
const adjusting = ref(false);
const transferring = ref(false);
const batchCreating = ref(false);

const editingTeamId = ref('');

const createForm = ref({
  name: '',
  monthly_budget_usd: '',
  monthly_reset_policy: 'reset',
  daily_limit_enabled: true,
});

const editForm = ref({
  name: '',
  monthly_budget_usd: '',
  monthly_reset_policy: 'reset',
  daily_limit_enabled: true,
});


const adjustForm = ref({
  token_id: '',
  token_name: '',
  current: '',
  new_amount: '',
});

const transferForm = ref({
  from_token_id: '',
  to_token_id: '',
  amount: '',
});

const batchForm = ref({
  names: '',
  model_names: [] as string[],
});

const policyOptions = [
  { label: 'Reset (clear each month)', value: 'reset' },
  { label: 'Rollover (accumulate unused)', value: 'rollover' },
];

const teamColumns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left' as const, sortable: true },
  { name: 'budget', label: 'Monthly Budget', field: 'monthly_budget_usd', align: 'left' as const },
  { name: 'used', label: 'Used', field: 'total_used_usd', align: 'left' as const },
  { name: 'unallocated', label: 'Unallocated', field: 'unallocated_pool_usd', align: 'left' as const },
  { name: 'policy', label: 'Policy', field: 'monthly_reset_policy', align: 'center' as const },
  { name: 'actions', label: 'Actions', field: 'id', align: 'center' as const },
];

const memberColumns = computed(() => {
  const cols: { name: string; label: string; field: string; align: 'left' | 'center' | 'right'; sortable?: boolean }[] = [
    { name: 'name', label: 'Name', field: 'token_name', align: 'left', sortable: true },
    { name: 'allocation', label: 'Allocation', field: 'allocated_usd', align: 'left' },
    { name: 'used', label: 'Used / Allocation', field: 'used_usd', align: 'left' },
    { name: 'remaining', label: 'Remaining', field: 'remaining_usd', align: 'left' },
  ];
  if (selectedTeam.value?.daily_limit_enabled) {
    cols.push({ name: 'daily', label: 'Daily', field: 'daily_limit_usd', align: 'left' });
  }
  cols.push(
    { name: 'status', label: 'Status', field: 'is_active', align: 'center' },
    { name: 'actions', label: 'Actions', field: 'token_id', align: 'center' },
  );
  return cols;
});

const memberOptions = computed(() => {
  return (selectedTeam.value?.members || []).map((m) => ({
    label: `${m.token_name} ($${m.allocated_usd})`,
    value: m.token_id,
  }));
});

const availableModelOptions = computed(() =>
  modelsStore.availableModels.map((m) => ({
    label: `${m.friendly_name} (${m.model_id})`,
    value: m.model_id,
  }))
);

const computedPerMemberAllocation = computed(() => {
  const pool = parseFloat(selectedTeam.value?.unallocated_pool_usd || '0');
  const names = batchForm.value.names.trim();
  if (!names) return '--';
  const count = names.split(/[,\n]+/).filter((n) => n.trim()).length;
  if (count === 0) return '--';
  return (pool / count).toFixed(2);
});

const computedPerMemberDaily = computed(() => {
  if (computedPerMemberAllocation.value === '--') return '--';
  const allocation = parseFloat(computedPerMemberAllocation.value);
  if (allocation <= 0) return '--';
  return (allocation / daysInMonth.value).toFixed(2);
});

const daysInMonth = computed(() => {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
});

const teamDailyBudget = computed(() => {
  if (!selectedTeam.value) return '0.00';
  const monthly = parseFloat(selectedTeam.value.monthly_budget_usd);
  return (monthly / daysInMonth.value).toFixed(2);
});

function getBudgetProgress(team: TeamListItem) {
  const used = parseFloat(team.total_used_usd);
  const budget = parseFloat(team.monthly_budget_usd);
  return budget > 0 ? used / budget : 0;
}

function getBudgetColor(team: TeamListItem) {
  const p = getBudgetProgress(team);
  if (p >= 0.9) return 'negative';
  if (p >= 0.7) return 'warning';
  return 'positive';
}

function getMemberProgress(member: TeamMember) {
  const used = parseFloat(member.used_usd);
  const allocated = parseFloat(member.allocated_usd);
  return allocated > 0 ? used / allocated : 0;
}

function getMemberColor(member: TeamMember) {
  const p = getMemberProgress(member);
  if (p >= 0.9) return 'negative';
  if (p >= 0.7) return 'warning';
  return 'positive';
}

async function selectTeam(teamId: string) {
  await teamsStore.fetchTeamDashboard(teamId);
}

function editTeam(team: TeamListItem) {
  editingTeamId.value = team.id;
  editForm.value = {
    name: team.name,
    monthly_budget_usd: team.monthly_budget_usd,
    monthly_reset_policy: team.monthly_reset_policy,
    daily_limit_enabled: team.daily_limit_enabled,
  };
  showEditDialog.value = true;
}

function confirmDeleteTeam(team: TeamListItem) {
  Dialog.create({
    title: 'Delete Team',
    message: `Are you sure you want to delete team "${team.name}"? Members will become standalone tokens.`,
    cancel: { label: 'Cancel', color: 'grey-7', flat: true },
    ok: { label: 'Delete', color: 'negative', unelevated: true },
    persistent: true,
    dark: true,
  }).onOk(() => {
    void teamsStore.deleteTeam(team.id);
  });
}

function openAdjustDialog(member: TeamMember) {
  adjustForm.value = {
    token_id: member.token_id,
    token_name: member.token_name,
    current: member.allocated_usd,
    new_amount: member.allocated_usd,
  };
  showAdjustDialog.value = true;
}

function confirmRemoveMember(member: TeamMember) {
  Dialog.create({
    title: 'Remove Member',
    message: `Remove "${member.token_name}" from this team? Allocation will return to the pool.`,
    cancel: { label: 'Cancel', color: 'grey-7', flat: true },
    ok: { label: 'Remove', color: 'negative', unelevated: true },
    persistent: true,
    dark: true,
  }).onOk(() => {
    if (selectedTeam.value) {
      void teamsStore.removeMember(selectedTeam.value.id, member.token_id).then(() => {
        void tokensStore.fetchTokens(false, true);
      });
    }
  });
}

async function handleCreateTeam() {
  creating.value = true;
  try {
    await teamsStore.createTeam(createForm.value);
    showCreateDialog.value = false;
    createForm.value = { name: '', monthly_budget_usd: '', monthly_reset_policy: 'reset', daily_limit_enabled: true };
  } finally {
    creating.value = false;
  }
}

async function handleUpdateTeam() {
  updating.value = true;
  try {
    await teamsStore.updateTeam(editingTeamId.value, editForm.value);
    showEditDialog.value = false;
  } finally {
    updating.value = false;
  }
}



async function handleAdjust() {
  if (!selectedTeam.value) return;
  adjusting.value = true;
  try {
    await teamsStore.adjustMember(
      selectedTeam.value.id,
      adjustForm.value.token_id,
      adjustForm.value.new_amount,
    );
    showAdjustDialog.value = false;
  } finally {
    adjusting.value = false;
  }
}

async function handleTransfer() {
  if (!selectedTeam.value) return;
  transferring.value = true;
  try {
    await teamsStore.transferAllocation(
      selectedTeam.value.id,
      transferForm.value.from_token_id,
      transferForm.value.to_token_id,
      transferForm.value.amount,
    );
    showTransferDialog.value = false;
    transferForm.value = { from_token_id: '', to_token_id: '', amount: '' };
  } finally {
    transferring.value = false;
  }
}

async function handleBatchCreate() {
  if (!selectedTeam.value) return;
  batchCreating.value = true;
  try {
    const batchData: { names: string; per_member_allocation: string; model_names?: string[] } = {
      names: batchForm.value.names,
      per_member_allocation: computedPerMemberAllocation.value,
    };
    if (batchForm.value.model_names.length > 0) {
      batchData.model_names = batchForm.value.model_names;
    }
    await teamsStore.batchCreateMembers(selectedTeam.value.id, batchData);
    void tokensStore.fetchTokens(false, true);
    showBatchDialog.value = false;
    batchForm.value = { names: '', model_names: [] };
  } finally {
    batchCreating.value = false;
  }
}

onMounted(async () => {
  await teamsStore.fetchTeams();
  void modelsStore.fetchAvailableModels();
});
</script>
