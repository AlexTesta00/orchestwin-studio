<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import { finalizationApi, type FinalizationApi } from "@/api/finalization";
import UiButton from "@/components/UiButton.vue";
import UiCard from "@/components/UiCard.vue";
import UiClaimLabel from "@/components/UiClaimLabel.vue";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedFinalizationRequest, useFinalizationStore } from "@/stores/finalization";
import { useUserModelingStore } from "@/stores/userModeling";
import type { SyntheticFindingPayload } from "@/types/finalization";

const props = withDefaults(
  defineProps<{
    projectId: string;
    executionId: string;
    api?: FinalizationApi | undefined;
    authorize?: AuthorizedFinalizationRequest | undefined;
  }>(),
  { api: () => finalizationApi, authorize: undefined },
);

const { t, locale } = useI18n({ useScope: "global" });
const auth = useAuthStore();
const store = useFinalizationStore();
const modeling = useUserModelingStore();

const authorize: AuthorizedFinalizationRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

interface TwinGroup {
  twinId: string;
  name: string;
  findings: SyntheticFindingPayload[];
}

const run = computed(() => store.evaluationRun);
const aggregation = computed(() => store.aggregation);
const busy = computed(() => store.isBusy);

const twinNames = computed(() => {
  const names = new Map<string, string>();
  for (const twin of modeling.currentTwins) {
    names.set(twin.twin_id, twin.profile.name);
  }
  return names;
});

const groups = computed<TwinGroup[]>(() => {
  const grouped = new Map<string, TwinGroup>();
  for (const finding of store.findings) {
    const group = grouped.get(finding.twin_id) ?? {
      twinId: finding.twin_id,
      name: twinNames.value.get(finding.twin_id) ?? t("evaluation.unknownTwin"),
      findings: [],
    };
    group.findings.push(finding);
    grouped.set(finding.twin_id, group);
  }
  return [...grouped.values()];
});

function severityClass(severity: string): string {
  if (severity === "critical" || severity === "major") {
    return "border-fail-line bg-fail-bg text-fail-dark";
  }
  if (severity === "moderate") {
    return "border-hypothesis-line bg-hypothesis-bg text-hypothesis";
  }
  return "border-line bg-surface-3 text-ink-2";
}

function confidenceText(finding: SyntheticFindingPayload): string {
  return new Intl.NumberFormat(locale.value, { style: "percent", maximumFractionDigits: 0 }).format(
    finding.confidence,
  );
}

function twinName(twinId: string): string {
  return twinNames.value.get(twinId) ?? t("evaluation.unknownTwin");
}

function completedText(): string {
  if (run.value === null) {
    return "";
  }
  return new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(run.value.completed_at),
  );
}

async function attempt(operation: () => Promise<unknown>): Promise<void> {
  try {
    await operation();
  } catch {
    return;
  }
}

async function load(): Promise<void> {
  await attempt(() => store.loadEvaluationRuns(props.projectId, authorize, props.api));
}

async function ask(): Promise<void> {
  await attempt(() =>
    store.createEvaluationRun(props.projectId, props.executionId, authorize, props.api),
  );
}

onMounted(load);
</script>

<template>
  <section class="grid gap-5" aria-labelledby="evaluation-title" data-testid="synthetic-evaluation">
    <div class="rounded-card border border-hypothesis-line bg-hypothesis-bg p-6">
      <div class="flex flex-wrap items-center gap-3">
        <h2 id="evaluation-title" class="m-0 text-[17px] font-semibold tracking-block text-ink">
          {{ t("evaluation.title") }}
        </h2>
        <UiClaimLabel kind="hypothesis" />
      </div>
      <p class="m-0 mt-2 max-w-[64ch] text-[15px] leading-relaxed text-ink-2">
        {{ t("evaluation.body") }}
      </p>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <UiButton :disabled="busy" data-testid="evaluation-ask" @click="ask">
          {{ run ? t("evaluation.askAgain") : t("evaluation.ask") }}
        </UiButton>
        <p
          v-if="busy"
          class="m-0 text-sm text-ink-3"
          aria-live="polite"
          data-testid="evaluation-busy"
        >
          {{ t("evaluation.busy") }}
        </p>
        <p v-else-if="run" class="m-0 text-sm text-ink-3" data-testid="evaluation-meta">
          {{
            t("evaluation.meta", {
              twins: run.response_count,
              findings: run.finding_count,
              when: completedText(),
            })
          }}
        </p>
        <p v-else class="m-0 text-sm text-ink-3" data-testid="evaluation-empty">
          {{ t("evaluation.empty") }}
        </p>
      </div>
      <p
        v-if="store.error"
        role="alert"
        class="mt-3 rounded-panel border border-fail-line bg-fail-bg px-4 py-3 text-sm font-semibold text-fail-dark"
      >
        {{ store.error }}
      </p>
    </div>

    <UiCard v-for="group in groups" :key="group.twinId" data-testid="evaluation-twin">
      <div class="flex flex-wrap items-center gap-3">
        <h3 class="m-0 text-base font-semibold tracking-block text-ink">{{ group.name }}</h3>
        <span class="text-sm text-ink-3">
          {{ t("evaluation.findingCount", { n: group.findings.length }) }}
        </span>
      </div>
      <ul class="m-0 mt-4 grid list-none gap-3 p-0">
        <li
          v-for="finding in group.findings"
          :key="finding.finding_id"
          class="grid gap-2 rounded-panel border border-line-soft px-4 py-3"
          data-testid="evaluation-finding"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="inline-flex items-center rounded-pill border px-2 py-0.5 text-xs font-semibold"
              :class="severityClass(finding.severity)"
            >
              {{ t(`evaluation.severity.${finding.severity}`) }}
            </span>
            <span
              class="inline-flex items-center rounded-pill border border-line bg-surface-3 px-2 py-0.5 text-xs font-semibold text-ink-2"
            >
              {{ t(`evaluation.criterion.${finding.criterion}`) }}
            </span>
            <span class="font-mono text-xs text-ink-3">
              {{ t("evaluation.confidence", { value: confidenceText(finding) }) }}
            </span>
            <UiClaimLabel kind="hypothesis" />
          </div>
          <p class="m-0 text-[15px] leading-relaxed text-ink">{{ finding.summary }}</p>
          <p class="m-0 font-mono text-xs text-ink-3">{{ finding.location }}</p>
          <details class="text-sm text-ink-2">
            <summary class="cursor-pointer font-semibold">{{ t("evaluation.why") }}</summary>
            <p class="m-0 mt-2 leading-6">{{ finding.rationale }}</p>
          </details>
          <p class="m-0 text-sm leading-6 text-ink-2">
            <span class="font-semibold text-ink">{{ t("evaluation.action") }}</span>
            {{ finding.recommended_action }}
          </p>
        </li>
      </ul>
    </UiCard>

    <UiCard v-if="aggregation" data-testid="evaluation-aggregation">
      <h3 class="m-0 text-base font-semibold tracking-block text-ink">
        {{ t("evaluation.aggregation.title") }}
      </h3>
      <p class="m-0 mt-1 text-sm leading-6 text-ink-2">{{ t("evaluation.aggregation.body") }}</p>
      <dl class="m-0 mt-4 grid gap-4">
        <div>
          <dt class="font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t("evaluation.aggregation.shared", { n: aggregation.shared_findings.length }) }}
          </dt>
          <dd v-if="aggregation.shared_findings.length === 0" class="m-0 mt-1 text-sm text-ink-3">
            {{ t("evaluation.aggregation.none") }}
          </dd>
          <dd
            v-for="group in aggregation.shared_findings"
            :key="group.group_id"
            class="m-0 mt-1 text-sm text-ink-2"
          >
            {{ group.findings[0]?.summary }}
            <span class="text-ink-3">
              ({{ group.findings.map((item) => twinName(item.twin_id)).join(", ") }})
            </span>
          </dd>
        </div>
        <div>
          <dt class="font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t("evaluation.aggregation.conflicts", { n: aggregation.direct_conflicts.length }) }}
          </dt>
          <dd v-if="aggregation.direct_conflicts.length === 0" class="m-0 mt-1 text-sm text-ink-3">
            {{ t("evaluation.aggregation.none") }}
          </dd>
          <dd
            v-for="conflict in aggregation.direct_conflicts"
            :key="conflict.declaration.conflict_id"
            class="m-0 mt-1 text-sm text-ink-2"
            data-testid="evaluation-conflict"
          >
            {{ conflict.declaration.summary }}
            <span class="block text-ink-3">{{ conflict.declaration.owner_decision_question }}</span>
          </dd>
        </div>
        <div v-if="aggregation.evidence_gaps.length > 0">
          <dt class="font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t("evaluation.aggregation.gaps") }}
          </dt>
          <dd
            v-for="(gap, index) in aggregation.evidence_gaps"
            :key="index"
            class="m-0 mt-1 text-sm text-ink-2"
          >
            <span class="font-semibold text-ink">{{ twinName(gap.twin_id) }}:</span> {{ gap.gap }}
          </dd>
        </div>
        <div v-if="aggregation.human_validation_questions.length > 0">
          <dt class="font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t("evaluation.aggregation.questions") }}
          </dt>
          <dd
            v-for="question in aggregation.human_validation_questions"
            :key="question.question_id"
            class="m-0 mt-1 text-sm text-ink-2"
          >
            {{ question.question }}
          </dd>
        </div>
      </dl>
    </UiCard>
  </section>
</template>
