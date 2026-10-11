<script setup lang="ts">
import { computed, provide, ref, watch } from "vue";

import { acceptanceTestsCopy } from "./acceptanceTestsCopy";
import AlignmentProposalsNotice from "./AlignmentProposalsNotice.vue";
import GenerationJobNotice from "./GenerationJobNotice.vue";
import { placeLabel } from "./screenNames";
import { commandParts, fill, plural } from "./textFormat";
import UiButton from "./UiButton.vue";
import UiClaimFrame from "./UiClaimFrame.vue";
import UiStatusChip from "./UiStatusChip.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";

import type { AcceptanceTestsApi } from "../api/acceptanceTests";
import type { GenerationJobsApi } from "../api/generationJobs";
import { useAuthorizedRequest } from "../composables/useAuthorizedRequest";
import { useIntlFormats } from "../composables/useIntlFormats";
import { useAcceptanceTestsStore, type AuthorizedRequest } from "../stores/acceptanceTests";
import { useDesignStore } from "../stores/design";
import { useGenerationResume } from "../stores/generationJobs";
import { useRequirementsStore } from "../stores/requirements";
import type {
  CriterionStatus,
  TestBrowserPayload,
  TestCritiquePayload,
  TestFindingPayload,
  TestRunSummaryPayload,
} from "../types/acceptanceTests";
import type { CritiqueVerdict, FindingSeverity } from "../types/codeChanges";
import type { GenerationOperation } from "../types/designMockups";

type Locale = "en" | "it";
type ChipStatus = "approved" | "pending" | "blocked" | "failed";
type CountKey = keyof TestRunSummaryPayload;

interface Subject {
  key: string;
  code: string;
  title: string | null;
}

interface Badge {
  status: ChipStatus;
  label: string;
}

interface CountChip {
  key: CountKey;
  badge: Badge;
}

interface CriterionRow {
  code: string;
  statement: string | null;
  reason: string | null;
  badge: Badge;
  paths: string;
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    authorize?: AuthorizedRequest;
    api?: AcceptanceTestsApi;
    jobsApi?: GenerationJobsApi | undefined;
  }>(),
  {
    locale: "en",
    jobsApi: undefined,
  },
);

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const CRITERION_STATUS: Readonly<Record<CriterionStatus, ChipStatus>> = {
  PASSED: "approved",
  FAILED: "failed",
  BLOCKED: "blocked",
  NOT_COVERED: "pending",
  NOT_RUN: "pending",
};

const CRITIQUE_STATUS: Readonly<Record<CritiqueVerdict, ChipStatus>> = {
  FINE: "approved",
  CONCERN: "blocked",
  DRIFT: "failed",
};

const SEVERITY_STYLES: Readonly<Record<FindingSeverity, string>> = {
  HIGH: "bg-warn-on-night/12 text-warn-on-night",
  MEDIUM: "bg-on-night/8 text-on-night-2",
  LOW: "bg-on-night/8 text-on-night-2",
};

const COUNTS: readonly { key: CountKey; status: CriterionStatus }[] = [
  { key: "passed", status: "PASSED" },
  { key: "failed", status: "FAILED" },
  { key: "blocked", status: "BLOCKED" },
  { key: "not_covered", status: "NOT_COVERED" },
  { key: "not_run", status: "NOT_RUN" },
];

const TEST_OPERATIONS: readonly GenerationOperation[] = ["TEST_PLAN", "TEST_REVIEW"];

const authorizedRequest = useAuthorizedRequest(() => props.authorize);
const design = useDesignStore();
const requirements = useRequirementsStore();
const store = useAcceptanceTestsStore();

const copy = computed(() => acceptanceTestsCopy[props.locale]);
const intlLocale = computed(() => (props.locale === "it" ? "it-IT" : "en-GB"));
const planRedo = ref(false);

const { job: runningJob, recheck } = useGenerationResume({
  projectId: () => props.projectId,
  operations: TEST_OPERATIONS,
  authorize: authorizedRequest,
  onSettled: reload,
  api: props.jobsApi,
});

const current = computed(() => store.projectId === props.projectId);
const overview = computed(() => (current.value ? store.overview : null));
const run = computed(() => (current.value ? store.latestRun : null));
const criteria = computed(() => (current.value ? store.criteria : []));
const critiques = computed(() => (current.value ? store.critiques : []));
const stale = computed(() => current.value && store.latestRunStale);
const loading = computed(() => current.value && store.pending.load);
const failure = computed(() => (current.value ? store.failure : null));

const earlierReview = computed(() => {
  const latest = run.value;
  const review = current.value ? store.latestReview : null;
  if (
    latest === null ||
    review === null ||
    critiques.value.length > 0 ||
    review.run_id === latest.id ||
    review.critiques.length === 0
  ) {
    return null;
  }
  return {
    sentence: fill(copy.value.earlierReview, { date: formatDate(review.finished_at) }),
    critiques: review.critiques,
  };
});

const shownCritiques = computed<TestCritiquePayload[]>(() =>
  critiques.value.length > 0 ? critiques.value : (earlierReview.value?.critiques ?? []),
);

const { dateFormat, listFormat } = useIntlFormats(intlLocale);

const failureText = computed(() => {
  const value = failure.value;
  if (value === null) {
    return null;
  }
  return value.code === null
    ? copy.value.loadFailed
    : fill(copy.value.loadFailedCode, { code: value.code });
});

const specification = computed(() =>
  requirements.projectId === props.projectId ? (requirements.current?.specification ?? null) : null,
);

const requirementTitles = computed<Readonly<Record<string, string>>>(() =>
  Object.fromEntries(
    (specification.value?.requirements ?? []).map((item) => [item.code, item.title]),
  ),
);

const criterionStatements = computed<Readonly<Record<string, string>>>(() =>
  Object.fromEntries(
    (specification.value?.acceptance_criteria ?? []).map((item) => [item.code, item.statement]),
  ),
);

const screenTitles = computed<Readonly<Record<string, string>>>(() => {
  const value = design.projectId === props.projectId ? (design.current?.package ?? null) : null;
  if (value === null) {
    return {};
  }
  const chosen = value.owner_selected_alternative_id;
  const generated = value.generated_mockup?.mockup ?? null;
  const screens: readonly { code: string; title: string }[] =
    generated !== null && generated.design_alternative_id === chosen && generated.screens.length > 0
      ? generated.screens
      : value.prototype !== null && value.prototype.design_alternative_id === chosen
        ? value.prototype.screens
        : [];
  return Object.fromEntries(screens.map((screen) => [screen.code, placeLabel(screen.title)]));
});

const runView = computed(() => {
  const value = run.value;
  if (value === null) {
    return null;
  }
  const code = value.reference.alternative_code;
  return {
    date: formatDate(value.finished_at),
    browsers: listFormat.value.format(value.browsers.map(browserLabel)),
    kind: copy.value.applicationKind[value.application.kind] ?? value.application.kind,
    address: value.application.address,
    reference: fill(copy.value.referenceValue, {
      requirements: value.reference.requirements_version_number,
      design: value.reference.design_version_number,
      alternative: code === null ? "" : ` (${code})`,
    }),
    counts: COUNTS.map((count): CountChip => {
      const number = value.summary[count.key];
      return {
        key: count.key,
        badge: {
          status: number === 0 ? "pending" : CRITERION_STATUS[count.status],
          label: plural(number, copy.value.counts[count.status]),
        },
      };
    }),
    reviewed:
      value.reviewed_at === null
        ? null
        : fill(copy.value.reviewedAt, { date: formatDate(value.reviewed_at) }),
  };
});

const criterionRows = computed(() => {
  const reasons: Readonly<Record<string, string>> = Object.fromEntries(
    (run.value?.not_covered ?? []).map((item) => [item.criterion, item.reason]),
  );
  return criteria.value.map((item): CriterionRow => ({
    code: item.code,
    statement: criterionStatements.value[item.code] ?? null,
    reason: item.status === "NOT_COVERED" ? (reasons[item.code] ?? null) : null,
    badge: { status: CRITERION_STATUS[item.status], label: copy.value.status[item.status] },
    paths: item.paths.join(", "),
  }));
});

const critiqueViews = computed(() =>
  shownCritiques.value.map((critique, index) => ({
    key: `${critique.twin_id}:${index}`,
    name: critique.twin_name,
    badge: {
      status: CRITIQUE_STATUS[critique.verdict],
      label: copy.value.critique[critique.verdict],
    },
    summary: critique.summary,
    findings: critique.findings.map((finding, position) => ({
      key: `${critique.twin_id}:${index}:${position}`,
      severity: copy.value.severity[finding.severity],
      style: SEVERITY_STYLES[finding.severity],
      text: finding.text,
      action: finding.action,
      subjects: findingSubjects(finding),
    })),
  })),
);

function formatDate(value: string): string {
  const time = Date.parse(value);
  return Number.isNaN(time) ? value : dateFormat.value.format(time);
}

function browserLabel(browser: TestBrowserPayload): string {
  return `${copy.value.browserName[browser.name] ?? browser.name} ${browser.version}`;
}

function findingSubjects(finding: TestFindingPayload): Subject[] {
  const about = finding.about;
  const subjects: Subject[] = [];
  if (about.criterion !== null) {
    subjects.push({ key: `criterion:${about.criterion}`, code: about.criterion, title: null });
  }
  if (about.requirement !== null) {
    subjects.push({
      key: `requirement:${about.requirement}`,
      code: about.requirement,
      title: requirementTitles.value[about.requirement] ?? null,
    });
  }
  if (about.screen !== null) {
    subjects.push({
      key: `screen:${about.screen}`,
      code: about.screen,
      title: screenTitles.value[about.screen] ?? null,
    });
  }
  return subjects;
}

function onProposalApplied(): void {
  planRedo.value = true;
}

async function load(): Promise<void> {
  planRedo.value = false;
  try {
    await store.load(props.projectId, authorizedRequest, props.api);
  } catch {
    return;
  }
}

async function reload(): Promise<void> {
  try {
    await store.reload(props.projectId, authorizedRequest, props.api);
  } catch {
    return;
  }
}

async function readAgainAndCheck(): Promise<void> {
  await Promise.all([reload(), recheck()]);
}

watch(() => props.projectId, load, { immediate: true });
</script>

<template>
  <section
    class="rounded-tile border border-night-line bg-night-raised p-6 text-on-night"
    aria-labelledby="acceptance-tests-title"
    data-surface="night"
    data-testid="acceptance-panel"
  >
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div class="min-w-[min(100%,18rem)] flex-1">
        <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
          {{ copy.eyebrow }}
        </p>
        <h2 id="acceptance-tests-title" class="m-0 mt-2 text-lg leading-tight font-semibold">
          {{ copy.title }}
        </h2>
        <p class="m-0 mt-1.5 text-sm leading-normal text-on-night-2">{{ copy.intro }}</p>
      </div>
      <UiButton
        variant="outline"
        :disabled="loading"
        aria-describedby="acceptance-tests-title"
        data-testid="acceptance-refresh"
        @click="readAgainAndCheck"
      >
        {{ copy.refresh }}
      </UiButton>
    </div>

    <div v-if="runningJob !== null" class="mt-5" data-testid="acceptance-job">
      <GenerationJobNotice :job="runningJob" :locale="locale" />
    </div>

    <div
      class="mt-5 grid grid-cols-1 gap-5"
      aria-live="polite"
      :aria-busy="loading ? 'true' : undefined"
      data-testid="acceptance-state"
    >
      <AlignmentProposalsNotice
        :project-id="projectId"
        section="TESTS"
        :locale="locale"
        :authorize="authorizedRequest"
        @applied="onProposalApplied"
      />

      <p
        v-if="planRedo"
        class="m-0 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 px-4 py-3 text-sm leading-normal text-warn-on-night"
        data-testid="acceptance-plan-redo"
      >
        <template v-for="part in commandParts(copy.planRedo)" :key="part.key">
          <code
            v-if="part.command"
            class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
            >{{ part.text }}</code
          >
          <template v-else>{{ part.text }}</template>
        </template>
      </p>

      <div
        v-if="failureText !== null"
        class="rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm text-fail-on-night"
        role="alert"
        data-testid="acceptance-error"
      >
        <p class="m-0 font-semibold wrap-anywhere">{{ failureText }}</p>
      </div>

      <p
        v-else-if="overview === null"
        class="m-0 text-sm text-on-night-3"
        data-testid="acceptance-loading"
      >
        {{ copy.loading }}
      </p>

      <template v-if="overview !== null">
        <p
          v-if="!overview.plan_available"
          class="m-0 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 px-4 py-3 text-sm leading-normal text-warn-on-night"
          data-testid="acceptance-no-model"
        >
          {{ copy.noModel }}
        </p>

        <p
          v-if="runView === null"
          class="m-0 rounded-field border border-night-line px-4 py-3 text-sm leading-normal text-on-night-2"
          data-testid="acceptance-empty"
        >
          <template v-for="part in commandParts(copy.empty)" :key="part.key">
            <code
              v-if="part.command"
              class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
              >{{ part.text }}</code
            >
            <template v-else>{{ part.text }}</template>
          </template>
        </p>

        <template v-else>
          <div class="border-t border-on-night/10 pt-4" data-testid="acceptance-run">
            <h3 class="m-0 text-base leading-tight font-semibold">{{ copy.latestRun }}</h3>
            <dl
              class="m-0 mt-3 grid grid-cols-1 gap-x-5 gap-y-1 text-sm sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-y-2"
              data-testid="acceptance-run-meta"
            >
              <dt class="text-on-night-3">{{ copy.when }}</dt>
              <dd class="m-0 mb-2 sm:mb-0" data-testid="acceptance-run-date">
                {{ runView.date }}
              </dd>
              <dt class="text-on-night-3">{{ copy.browsers }}</dt>
              <dd class="m-0 mb-2 wrap-anywhere sm:mb-0" data-testid="acceptance-run-browsers">
                {{ runView.browsers }}
              </dd>
              <dt class="text-on-night-3">{{ copy.application }}</dt>
              <dd class="m-0 mb-2 wrap-anywhere sm:mb-0" data-testid="acceptance-run-application">
                {{ runView.kind }}
                <code
                  class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                  >{{ runView.address }}</code
                >
              </dd>
              <dt class="text-on-night-3">{{ copy.reference }}</dt>
              <dd class="m-0" data-testid="acceptance-run-reference">{{ runView.reference }}</dd>
            </dl>
            <p
              v-if="stale"
              class="m-0 mt-3 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 px-4 py-3 text-sm leading-normal text-warn-on-night"
              data-testid="acceptance-stale"
            >
              <template v-for="part in commandParts(copy.stale)" :key="part.key">
                <code
                  v-if="part.command"
                  class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                  >{{ part.text }}</code
                >
                <template v-else>{{ part.text }}</template>
              </template>
            </p>
            <ul
              class="m-0 mt-4 flex list-none flex-wrap gap-2 p-0"
              :aria-label="copy.countsLabel"
              data-testid="acceptance-summary"
            >
              <li v-for="count in runView.counts" :key="count.key">
                <UiStatusChip
                  :status="count.badge.status"
                  :label="count.badge.label"
                  :data-count="count.key"
                  data-testid="acceptance-count"
                />
              </li>
            </ul>
            <p class="m-0 mt-3 text-[13px] leading-normal text-on-night-3">{{ copy.legend }}</p>
          </div>

          <div class="border-t border-on-night/10 pt-4">
            <h3 id="acceptance-criteria-title" class="m-0 text-base leading-tight font-semibold">
              {{ fill(copy.criteriaTitle, { count: criterionRows.length }) }}
            </h3>
            <div
              v-if="criterionRows.length > 0"
              class="mt-3 overflow-x-auto rounded-field border border-night-line"
              role="region"
              tabindex="0"
              aria-labelledby="acceptance-criteria-title"
              data-testid="acceptance-criteria"
            >
              <table class="w-full border-collapse text-left text-sm">
                <caption class="sr-only">
                  {{
                    copy.criteriaCaption
                  }}
                </caption>
                <thead class="border-b border-night-line bg-on-night/3">
                  <tr>
                    <th
                      scope="col"
                      class="py-3 pr-3 pl-4 align-bottom text-[13px] font-semibold whitespace-nowrap text-on-night-2"
                    >
                      {{ copy.columns.code }}
                    </th>
                    <th
                      scope="col"
                      class="px-3 py-3 align-bottom text-[13px] font-semibold whitespace-nowrap text-on-night-2"
                    >
                      {{ copy.columns.statement }}
                    </th>
                    <th
                      scope="col"
                      class="px-3 py-3 align-bottom text-[13px] font-semibold whitespace-nowrap text-on-night-2"
                    >
                      {{ copy.columns.status }}
                    </th>
                    <th
                      scope="col"
                      class="py-3 pr-4 pl-3 align-bottom text-[13px] font-semibold whitespace-nowrap text-on-night-2"
                    >
                      {{ copy.columns.paths }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in criterionRows"
                    :key="row.code"
                    class="border-t border-on-night/8 align-top first:border-t-0"
                    data-testid="acceptance-criterion"
                  >
                    <th
                      scope="row"
                      class="py-3 pr-3 pl-4 font-mono text-xs leading-6 font-medium whitespace-nowrap text-on-night"
                      data-testid="acceptance-criterion-code"
                    >
                      {{ row.code }}
                    </th>
                    <td
                      class="min-w-60 px-3 py-3 leading-normal text-on-night"
                      data-testid="acceptance-criterion-statement"
                    >
                      <template v-if="row.statement !== null">{{ row.statement }}</template>
                      <span v-else role="img" :aria-label="copy.statementMissing">—</span>
                      <p
                        v-if="row.reason !== null"
                        class="m-0 mt-1 text-[13px] text-on-night-3"
                        data-testid="acceptance-criterion-reason"
                      >
                        {{ copy.reason }}: {{ row.reason }}
                      </p>
                    </td>
                    <td class="px-3 py-3">
                      <UiStatusChip
                        :status="row.badge.status"
                        :label="row.badge.label"
                        data-testid="acceptance-criterion-status"
                      />
                    </td>
                    <td
                      class="py-3 pr-4 pl-3 font-mono text-xs leading-6 text-on-night-2"
                      data-testid="acceptance-criterion-paths"
                    >
                      <template v-if="row.paths.length > 0">{{ row.paths }}</template>
                      <span v-else role="img" :aria-label="copy.noPaths">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="m-0 mt-2 text-sm text-on-night-3" data-testid="acceptance-no-criteria">
              {{ copy.noCriteria }}
            </p>
          </div>

          <div class="border-t border-on-night/10 pt-4" data-testid="acceptance-critiques">
            <h3 class="m-0 text-base leading-tight font-semibold">{{ copy.critiquesTitle }}</h3>
            <p
              v-if="runView.reviewed !== null"
              class="m-0 mt-1 text-sm leading-normal text-on-night-3"
              data-testid="acceptance-reviewed"
            >
              {{ runView.reviewed }}
            </p>
            <p
              v-if="earlierReview !== null"
              class="m-0 mt-1 text-sm leading-normal text-on-night-3"
              data-testid="acceptance-earlier-review"
            >
              {{ earlierReview.sentence }}
            </p>
            <ul v-if="critiqueViews.length > 0" class="m-0 mt-3 grid list-none gap-3 p-0">
              <li v-for="critique in critiqueViews" :key="critique.key">
                <UiClaimFrame
                  status="hypothesis"
                  radius="tile"
                  class="grid gap-2"
                  data-testid="acceptance-critique"
                >
                  <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <h4 class="m-0 text-[15px] leading-snug font-semibold">
                      {{ critique.name }}
                    </h4>
                    <UiStatusChip
                      :status="critique.badge.status"
                      :label="critique.badge.label"
                      class="whitespace-normal!"
                      data-testid="acceptance-critique-verdict"
                    />
                  </div>
                  <p class="m-0 text-sm leading-normal text-on-night-2">{{ critique.summary }}</p>
                  <ul
                    v-if="critique.findings.length > 0"
                    class="m-0 grid list-disc gap-2 pl-5 text-sm leading-normal"
                  >
                    <li
                      v-for="finding in critique.findings"
                      :key="finding.key"
                      data-testid="acceptance-finding"
                    >
                      <span
                        :class="[
                          'mr-1 inline-flex min-h-6 items-center rounded-pill px-[9px] text-xs font-semibold',
                          finding.style,
                        ]"
                        data-testid="acceptance-finding-severity"
                        >{{ finding.severity }}</span
                      >
                      {{ " " }}
                      <span class="wrap-anywhere">{{ finding.text }}</span>
                      <div
                        v-if="finding.subjects.length > 0"
                        class="mt-1 flex flex-wrap items-baseline gap-x-2 text-[13px] text-on-night-3"
                      >
                        <span>{{ copy.about }}:</span>
                        <ul class="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0">
                          <li
                            v-for="subject in finding.subjects"
                            :key="subject.key"
                            data-testid="acceptance-subject"
                          >
                            <span class="font-mono text-xs text-on-night-2">{{
                              subject.code
                            }}</span>
                            <template v-if="subject.title"> · {{ subject.title }}</template>
                          </li>
                        </ul>
                      </div>
                      <p v-if="finding.action" class="m-0 mt-1 text-[13px] text-on-night-2">
                        <strong class="font-semibold text-on-night">{{ copy.action }}:</strong>
                        {{ finding.action }}
                      </p>
                    </li>
                  </ul>
                  <p v-else class="m-0 text-sm text-on-night-3">{{ copy.noFindings }}</p>
                </UiClaimFrame>
              </li>
            </ul>
            <p
              v-else
              class="m-0 mt-2 text-sm leading-normal text-on-night-3"
              data-testid="acceptance-no-review"
            >
              <template v-for="part in commandParts(copy.noReview)" :key="part.key">
                <code
                  v-if="part.command"
                  class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                  >{{ part.text }}</code
                >
                <template v-else>{{ part.text }}</template>
              </template>
            </p>
          </div>

          <p
            class="m-0 border-t border-on-night/10 pt-4 text-sm leading-normal text-on-night-2"
            data-testid="acceptance-terminal"
          >
            <template v-for="part in commandParts(copy.terminal)" :key="part.key">
              <code
                v-if="part.command"
                class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                >{{ part.text }}</code
              >
              <template v-else>{{ part.text }}</template>
            </template>
          </p>
        </template>
      </template>
    </div>
  </section>
</template>
