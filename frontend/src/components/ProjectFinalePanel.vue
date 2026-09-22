<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import { finalizationApi, type FinalizationApi } from "@/api/finalization";
import UiButton from "@/components/UiButton.vue";
import UiCard from "@/components/UiCard.vue";
import UiEvidenceDrawer, { type EvidenceEntry } from "@/components/UiEvidenceDrawer.vue";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedFinalizationRequest, useFinalizationStore } from "@/stores/finalization";

export interface FinaleRecapRow {
  key: string;
  label: string;
  outcome: "approved" | "generated" | "pending";
  decisions: number | null;
  max: number | null;
}

type FinaleStage =
  "loading" | "missing" | "blocked" | "review" | "decision" | "approved" | "exported" | "decided";

const props = withDefaults(
  defineProps<{
    projectId: string;
    recap: FinaleRecapRow[];
    api?: FinalizationApi | undefined;
    authorize?: AuthorizedFinalizationRequest | undefined;
  }>(),
  { api: () => finalizationApi, authorize: undefined },
);

const emit = defineEmits<{ "open-provenance": []; "open-sources": [] }>();

const { t, locale } = useI18n({ useScope: "global" });
const auth = useAuthStore();
const store = useFinalizationStore();

const approvalEventId = ref<string | null>(null);
const revisionReason = ref("");
const requestingRevision = ref(false);
const reasonMissing = ref(false);
const loaded = ref(false);

const authorize: AuthorizedFinalizationRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

const review = computed(() => store.latestReview);
const approval = computed(() => store.finalApproval);
const bundle = computed(() => store.exportBundle);
const blockingChecks = computed(
  () => review.value?.checks.filter((check) => check.blocks_gate8) ?? [],
);
const approvalEvent = computed(
  () => approval.value?.approval_event_id ?? approvalEventId.value ?? null,
);

const stage = computed<FinaleStage>(() => {
  if (!loaded.value) {
    return "loading";
  }
  if (bundle.value !== null) {
    return "exported";
  }
  if (review.value === null) {
    return "missing";
  }
  if (approval.value !== null) {
    if (approval.value.status === "PENDING_APPROVAL") {
      return "decision";
    }
    return approval.value.status === "APPROVED" ? "approved" : "decided";
  }
  return review.value.ready_for_gate8 ? "review" : "blocked";
});

const statusText = computed(() =>
  stage.value === "decided"
    ? t("finale.status.decided", { status: approval.value?.status ?? "" })
    : t(`finale.status.${stage.value}`),
);

const bundleEvidence = computed<EvidenceEntry[]>(() =>
  bundle.value === null
    ? []
    : [
        { key: t("finale.evidence.archive"), value: bundle.value.archive_hash },
        { key: t("finale.evidence.size"), value: formatSize(bundle.value.archive_size_bytes) },
        { key: t("finale.evidence.manifest"), value: bundle.value.manifest_hash },
        { key: t("finale.evidence.created"), value: bundle.value.created_at },
      ],
);

function uuid(): string {
  return crypto.randomUUID();
}

function now(): string {
  return new Date().toISOString();
}

function formatSize(bytes: number): string {
  const kilobytes = new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(
    bytes / 1024,
  );
  return `${kilobytes} KB`;
}

function decisionText(row: FinaleRecapRow): string {
  if (row.decisions === null) {
    return "—";
  }
  return row.max === null
    ? String(row.decisions)
    : t("finale.recap.count", { n: row.decisions, max: row.max });
}

async function attempt(operation: () => Promise<unknown>): Promise<void> {
  try {
    await operation();
  } catch {
    return;
  }
}

async function load(): Promise<void> {
  await attempt(() => store.loadFinalReviews(props.projectId, authorize, props.api));
  loaded.value = true;
}

async function submitReview(): Promise<void> {
  const current = review.value;
  if (current === null) {
    return;
  }
  await attempt(() =>
    store.submitGate8(
      {
        expected_version: current.version_number,
        expected_content_hash: current.content_hash,
        gate_id: uuid(),
        event_id: uuid(),
        occurred_at: now(),
      },
      authorize,
      props.api,
    ),
  );
}

async function decide(action: "APPROVE" | "REQUEST_REVISION"): Promise<void> {
  const current = review.value;
  if (current === null || approval.value === null) {
    return;
  }
  const reason = revisionReason.value.trim();
  if (action === "REQUEST_REVISION" && reason.length === 0) {
    reasonMissing.value = true;
    return;
  }
  reasonMissing.value = false;
  const eventId = uuid();
  await attempt(async () => {
    await store.decideGate8(
      {
        action,
        expected_review_id: current.review_id,
        expected_review_version: current.version_number,
        expected_review_hash: current.content_hash,
        event_id: eventId,
        occurred_at: now(),
        reason: action === "APPROVE" ? null : reason,
      },
      authorize,
      props.api,
    );
    if (action === "APPROVE") {
      approvalEventId.value = eventId;
    } else {
      requestingRevision.value = false;
      revisionReason.value = "";
    }
  });
}

async function createExport(): Promise<void> {
  const current = review.value;
  const gate = approval.value;
  const eventId = approvalEvent.value;
  if (current === null || gate === null || eventId === null) {
    return;
  }
  await attempt(() =>
    store.createExport(
      props.projectId,
      {
        export_id: uuid(),
        final_review_id: current.review_id,
        expected_review_version: current.version_number,
        expected_review_hash: current.content_hash,
        final_approval_gate_id: gate.gate_id,
        final_approval_event_id: eventId,
        occurred_at: now(),
      },
      authorize,
      props.api,
    ),
  );
}

async function download(): Promise<void> {
  await attempt(async () => {
    const { blob, filename } = await store.downloadExport(authorize, props.api);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  });
}

onMounted(load);
</script>

<template>
  <section class="grid gap-5" aria-labelledby="finale-title" data-testid="project-finale">
    <div class="rounded-card border border-ok-line bg-ok-bg p-6">
      <h2 id="finale-title" class="m-0 text-[17px] font-semibold tracking-block text-ok-dark">
        {{ t("finale.title") }}
      </h2>
      <p class="m-0 mt-2 max-w-[60ch] text-[15px] leading-relaxed text-ok-text">
        {{ t("finale.body") }}
      </p>
    </div>

    <UiCard tone="table">
      <div
        class="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_92px] gap-4 border-b border-line bg-surface-3 px-5 py-3 font-mono text-[11px] tracking-wide text-ink-3 uppercase"
      >
        <span>{{ t("finale.recap.step") }}</span>
        <span>{{ t("finale.recap.outcome") }}</span>
        <span>{{ t("finale.recap.decisions") }}</span>
      </div>
      <ol class="m-0 list-none p-0">
        <li
          v-for="row in recap"
          :key="row.key"
          class="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_92px] items-center gap-4 border-b border-line-soft px-5 py-3 last:border-b-0"
          data-testid="finale-recap-row"
        >
          <span class="text-[14.5px] font-medium text-ink">{{ row.label }}</span>
          <span
            class="inline-flex items-center gap-2 text-[13.5px]"
            :class="row.outcome === 'pending' ? 'text-ink-3' : 'text-ok-text'"
          >
            <span
              class="size-[7px] shrink-0 rounded-full"
              :class="row.outcome === 'pending' ? 'border border-line-strong bg-surface' : 'bg-ok'"
              aria-hidden="true"
            />
            {{ t(`finale.recap.${row.outcome}`) }}
          </span>
          <span class="font-mono text-[12.5px] text-ink-3">{{ decisionText(row) }}</span>
        </li>
      </ol>
    </UiCard>

    <UiCard>
      <h3 class="m-0 text-base font-semibold tracking-block text-ink">
        {{ t("finale.export.title") }}
      </h3>
      <p
        class="m-0 mt-1 text-sm leading-6 text-ink-2"
        aria-live="polite"
        data-testid="finale-status"
      >
        {{ statusText }}
      </p>
      <ul v-if="stage === 'blocked'" class="mt-3 grid list-disc gap-1 pl-5 text-sm text-ink-2">
        <li v-for="check in blockingChecks" :key="check.check_id">{{ check.summary }}</li>
      </ul>
      <p
        v-if="store.error"
        role="alert"
        class="mt-3 rounded-panel border border-fail-line bg-fail-bg px-4 py-3 text-sm font-semibold text-fail-dark"
      >
        {{ store.error }}
      </p>
      <p v-if="stage === 'approved' && approvalEvent === null" class="mt-3 text-sm text-ink-3">
        {{ t("finale.export.eventMissing") }}
      </p>

      <div class="mt-4 flex flex-wrap gap-3">
        <UiButton
          v-if="stage === 'missing' || stage === 'blocked' || stage === 'decided'"
          variant="secondary"
          :disabled="store.isBusy"
          data-testid="finale-reload"
          @click="load"
        >
          {{ t("finale.actions.reload") }}
        </UiButton>
        <UiButton
          v-if="stage === 'review'"
          :disabled="store.isBusy"
          data-testid="finale-submit"
          @click="submitReview"
        >
          {{ t("finale.actions.submit") }}
        </UiButton>
        <template v-if="stage === 'decision'">
          <UiButton
            :disabled="store.isBusy"
            data-testid="finale-approve"
            @click="decide('APPROVE')"
          >
            {{ t("finale.actions.approve") }}
          </UiButton>
          <UiButton
            variant="secondary"
            :disabled="store.isBusy"
            data-testid="finale-revise"
            @click="requestingRevision = !requestingRevision"
          >
            {{ t("finale.actions.revise") }}
          </UiButton>
        </template>
        <UiButton
          v-if="stage === 'approved'"
          :disabled="store.isBusy || approvalEvent === null"
          data-testid="finale-export"
          @click="createExport"
        >
          {{ t("finale.actions.export") }}
        </UiButton>
        <UiButton v-if="stage === 'exported'" data-testid="finale-download" @click="download">
          {{ t("finale.actions.download") }}
        </UiButton>
        <UiButton variant="secondary" data-testid="finale-sources" @click="emit('open-sources')">
          {{ t("finale.actions.sources") }}
        </UiButton>
        <UiButton
          variant="secondary"
          data-testid="finale-provenance"
          @click="emit('open-provenance')"
        >
          {{ t("finale.actions.provenance") }}
        </UiButton>
      </div>

      <form
        v-if="stage === 'decision' && requestingRevision"
        class="mt-4 grid gap-3"
        @submit.prevent="decide('REQUEST_REVISION')"
      >
        <label class="grid gap-2 text-sm font-semibold text-ink-2" for="finale-reason">
          {{ t("finale.reason.label") }}
          <textarea
            id="finale-reason"
            v-model="revisionReason"
            rows="3"
            class="rounded-control border border-field bg-surface px-3 py-2 text-sm font-normal text-ink focus-visible:outline-none"
            data-testid="finale-reason"
          ></textarea>
        </label>
        <p v-if="reasonMissing" role="alert" class="m-0 text-sm font-semibold text-fail-dark">
          {{ t("finale.reason.missing") }}
        </p>
        <div class="flex">
          <UiButton
            type="submit"
            variant="danger"
            :disabled="store.isBusy"
            data-testid="finale-send-revision"
          >
            {{ t("finale.actions.sendRevision") }}
          </UiButton>
        </div>
      </form>

      <div v-if="bundle" class="mt-4">
        <UiEvidenceDrawer :entries="bundleEvidence" />
      </div>
    </UiCard>
  </section>
</template>
