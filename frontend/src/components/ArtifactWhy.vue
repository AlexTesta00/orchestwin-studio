<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import { WhyApiError } from "../api/why";
import ArtifactWhyNode from "./ArtifactWhyNode.vue";
import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";
import { whyContextKey } from "./whyContext";
import { whyGapLabel, whyMessages, whyNodeTitle, whyRelationLabel } from "./whyCopy";
import { useSurface } from "./UiSurface.vue";
import type { WhyAnswer, WhyNode, WhyPerspective } from "../types/why";

const props = withDefaults(
  defineProps<{
    code: string;
    title?: string | undefined;
    kind?: string | undefined;
    versionNumber?: number | undefined;
    artifactId?: string | undefined;
    contentHash?: string | undefined;
    contexts?: readonly string[];
    locale?: "en" | "it";
    testId?: string;
  }>(),
  { locale: "en", contexts: () => [], testId: "artifact-why" },
);
const context = inject(whyContextKey, null);
const surface = useSurface(() => undefined);
const copy = computed(() => whyMessages[props.locale]);
const answer = ref<WhyAnswer | null>(null);
const candidates = ref<WhyNode[]>([]);
const busy = ref(false);
const error = ref<string | null>(null);
const container = ref<HTMLDetailsElement | null>(null);
const SUMMARY_LIMIT = 3;
const stopReasons = computed(() => [...new Set(answer.value?.summary.stop_reasons ?? [])]);
const targetGapCodes = computed(() => [
  ...new Set(
    (answer.value?.target.gaps ?? [])
      .filter((gap) => !stopReasons.value.includes(gap.code))
      .map((gap) => gap.code),
  ),
]);
const nodeTitles = computed(
  () =>
    new Map(
      answer.value
        ? [answer.value.target, ...answer.value.upstream, ...answer.value.downstream].map(
            (node) => [node.key, whyNodeTitle(node, props.locale)],
          )
        : [],
    ),
);
let epoch = 0;

function perspectiveName(item: WhyPerspective): string {
  const key = item.key ?? "";
  return (
    item.label ??
    item.title ??
    copy.value.perspectives[key as keyof typeof copy.value.perspectives] ??
    copy.value.context
  );
}

async function load(selector?: string): Promise<void> {
  if (context === null) return;
  const project = context.projectId();
  const request = ++epoch;
  busy.value = true;
  error.value = null;
  answer.value = null;
  candidates.value = [];
  try {
    let code = selector ?? props.code;
    if (
      selector === undefined &&
      (props.kind ||
        props.versionNumber !== undefined ||
        props.artifactId ||
        props.contentHash ||
        props.contexts.length > 0)
    ) {
      const document = await context.authorize((token) => context.api.document(project, token));
      const matches = document.nodes.filter(
        (node) =>
          node.code === props.code &&
          (!props.kind || node.kind === props.kind) &&
          (props.versionNumber === undefined ||
            node.reference.version_number === props.versionNumber) &&
          (!props.artifactId || node.reference.artifact_id === props.artifactId) &&
          (!props.contentHash || node.reference.content_hash === props.contentHash) &&
          props.contexts.every((value) => node.key.includes(encodeURIComponent(value))),
      );
      if (request !== epoch || project !== context.projectId()) return;
      if (matches.length > 1) {
        candidates.value = matches;
        return;
      }
      if (matches.length === 0) {
        error.value = copy.value.notFound;
        return;
      }
      code = matches[0]!.key;
    }
    const result = await context.authorize((token) => context.api.explain(project, code, token));
    if (request === epoch && project === context.projectId()) answer.value = result;
  } catch (failure) {
    if (request !== epoch || project !== context.projectId()) return;
    if (failure instanceof WhyApiError && failure.code === "WHY_CODE_AMBIGUOUS") {
      try {
        const document = await context.authorize((token) => context.api.document(project, token));
        const payload = failure.payload as { detail?: { candidates?: string[] } } | null;
        if (request === epoch && project === context.projectId()) {
          candidates.value = document.nodes.filter((node) =>
            payload?.detail?.candidates?.includes(node.key),
          );
          if (candidates.value.length === 0) error.value = copy.value.notFound;
        }
      } catch {
        if (request === epoch) error.value = copy.value.error;
      }
    } else {
      error.value =
        failure instanceof WhyApiError && failure.code === "WHY_CODE_NOT_FOUND"
          ? copy.value.notFound
          : copy.value.error;
    }
  } finally {
    if (request === epoch) busy.value = false;
  }
}

function toggle(event: Event): void {
  if (
    event.target === event.currentTarget &&
    event.target instanceof HTMLDetailsElement &&
    event.target.open &&
    !answer.value &&
    !busy.value &&
    candidates.value.length === 0
  )
    void load();
}

watch(
  () =>
    [
      props.code,
      props.versionNumber,
      props.artifactId,
      props.contentHash,
      props.contexts.join("|"),
      context?.projectId(),
    ] as const,
  () => {
    epoch += 1;
    answer.value = null;
    candidates.value = [];
    busy.value = false;
    error.value = null;
    if (container.value?.open) void load();
  },
);
</script>

<template>
  <details
    v-if="context"
    ref="container"
    class="max-w-full min-w-0 rounded-field border border-current/15 text-sm [overflow-wrap:anywhere] whitespace-normal"
    :class="surface === 'night' ? 'bg-night-panel text-on-night-2' : 'bg-surface text-ink-2'"
    :data-testid="testId"
    :data-why-code="code"
    @toggle="toggle"
  >
    <summary
      tabindex="0"
      class="flex min-h-11 cursor-pointer items-center px-3 font-sans font-semibold"
      :aria-label="`${copy.why} ${title ?? code}`"
      data-testid="why-open"
    >
      {{ copy.why }}
    </summary>
    <div
      class="grid min-w-0 gap-3 border-t border-current/15 p-3 font-sans"
      data-testid="why-content"
    >
      <p v-if="busy" class="m-0" role="status">{{ copy.loading }}</p>
      <p v-if="error" class="m-0" role="alert">{{ error }}</p>
      <section v-if="candidates.length > 0" class="grid gap-2" data-testid="why-candidates">
        <strong>{{ copy.choose }}</strong>
        <button
          v-for="candidate in candidates"
          :key="candidate.key"
          type="button"
          class="grid min-h-11 max-w-full gap-1 rounded-field border border-current/20 p-3 text-left"
          data-testid="why-candidate"
          @click="load(candidate.key)"
        >
          <strong>{{ whyNodeTitle(candidate, locale) }}</strong>
          <span
            >{{ copy.version }} {{ candidate.reference.version_number }} ·
            {{ candidate.current ? copy.current : copy.historical }}</span
          >
          <span class="font-mono text-xs break-all">{{ candidate.reference.content_hash }}</span>
          <span class="font-mono text-xs break-all">{{ candidate.key }}</span>
        </button>
      </section>
      <template v-if="answer">
        <strong class="text-base" data-testid="why-target-title">{{
          whyNodeTitle(answer.target, locale)
        }}</strong>
        <UserModelingEpistemicBadge
          :status="answer.target.display_status"
          :show-details="false"
          :locale="locale"
        />
        <p
          v-if="answer.target.rationale"
          class="m-0 text-sm whitespace-pre-wrap"
          data-testid="why-rationale-summary"
        >
          <strong
            >{{
              answer.target.rationale.origin === "MODEL"
                ? copy.model
                : answer.target.rationale.origin === "OWNER"
                  ? copy.owner
                  : answer.target.rationale.origin === "SYSTEM"
                    ? copy.system
                    : copy.unknown
            }}
            · {{ copy.version }} {{ answer.target.rationale.version_number }}:
          </strong>
          {{
            answer.target.rationale.text.length > 240
              ? `${answer.target.rationale.text.slice(0, 240)}…`
              : answer.target.rationale.text
          }}
        </p>
        <section v-if="targetGapCodes.length > 0" class="grid gap-1" data-testid="why-target-gaps">
          <strong>{{ copy.missing }} · {{ targetGapCodes.length }}</strong>
          <p
            v-for="code in targetGapCodes.slice(0, SUMMARY_LIMIT)"
            :key="code"
            class="m-0 text-xs"
            data-testid="why-target-gap"
          >
            {{ whyGapLabel(code, locale) }}
          </p>
        </section>
        <section
          v-if="answer.target.declared_context.provided_prototype"
          class="grid gap-2"
          data-testid="why-provided-prototype-summary"
        >
          <strong>{{ copy.supplied }}</strong>
          <p
            v-if="answer.target.declared_context.provided_prototype.declared_origin"
            class="m-0 text-sm"
          >
            {{ copy.declaredOrigin }}:
            {{ answer.target.declared_context.provided_prototype.declared_origin }}
          </p>
          <p class="m-0 text-sm" data-testid="why-provided-evaluation-limit">
            {{ copy.prototypeEvaluationLimit }}
          </p>
        </section>
        <dl
          class="m-0 grid gap-1 text-xs"
          data-testid="why-summary"
          :data-why-key="answer.target.key"
        >
          <div>
            <dt class="inline font-semibold">{{ copy.twin }}:</dt>
            <dd class="m-0 inline">{{ answer.summary.complete_to_twin ? copy.yes : copy.no }}</dd>
          </div>
          <div>
            <dt class="inline font-semibold">{{ copy.evidence }}:</dt>
            <dd class="m-0 inline">
              {{ answer.summary.complete_to_evidence ? copy.yes : copy.no }}
            </dd>
          </div>
          <div>
            <dt class="inline font-semibold">{{ copy.allPaths }}:</dt>
            <dd class="m-0 inline">{{ answer.summary.all_paths_complete ? copy.yes : copy.no }}</dd>
          </div>
        </dl>
        <div v-if="stopReasons.length > 0" class="grid gap-1" data-testid="why-interrupted">
          <strong>{{ copy.interrupted }} · {{ stopReasons.length }}</strong>
          <p
            v-for="reason in stopReasons.slice(0, SUMMARY_LIMIT)"
            :key="reason"
            class="m-0 text-xs"
          >
            {{ whyGapLabel(reason, locale) }}
          </p>
        </div>
        <section
          v-for="direction in ['upstream', 'downstream'] as const"
          :key="direction"
          class="grid gap-1"
          :data-testid="`why-summary-${direction}`"
        >
          <strong>{{ copy[direction] }} · {{ answer.summary[`${direction}_count`] }}</strong>
          <p v-if="answer[direction].length === 0" class="m-0 text-xs">{{ copy.none }}</p>
          <ul v-else class="m-0 grid list-disc gap-1 pl-5">
            <li v-for="node in answer[direction].slice(0, SUMMARY_LIMIT)" :key="node.key">
              {{ whyNodeTitle(node, locale) }}
            </li>
          </ul>
        </section>
        <section
          v-if="answer.declared_context.perspectives.length > 0"
          class="grid gap-1"
          data-testid="why-declared-context"
        >
          <strong>{{ copy.context }} · {{ answer.declared_context.perspectives.length }}</strong>
          <p class="m-0 text-xs">{{ copy.declared }}</p>
          <ul class="m-0 list-disc pl-5">
            <li
              v-for="(item, index) in answer.declared_context.perspectives.slice(0, SUMMARY_LIMIT)"
              :key="index"
            >
              {{ perspectiveName(item) }}
            </li>
          </ul>
        </section>
        <section class="grid gap-1" data-testid="why-human-validation">
          <strong>{{ copy.validation }} · {{ answer.human_validation.length }}</strong>
          <p v-if="answer.human_validation.length === 0" class="m-0 text-xs">
            {{ copy.noValidation }}
          </p>
          <ul v-else class="m-0 grid list-disc gap-2 pl-5">
            <li v-for="node in answer.human_validation.slice(0, SUMMARY_LIMIT)" :key="node.key">
              <span>{{ whyNodeTitle(node, locale) }}</span>
              <UserModelingEpistemicBadge
                :status="node.display_status"
                :show-details="false"
                :locale="locale"
              />
            </li>
          </ul>
        </section>
        <details data-testid="why-details">
          <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
            {{ copy.details }}
          </summary>
          <div class="grid gap-3">
            <ArtifactWhyNode :node="answer.target" :locale="locale" />
            <section
              v-if="answer.human_validation.length > 0"
              class="grid gap-2"
              data-testid="why-details-human-validation"
            >
              <h3 class="m-0 font-semibold">
                {{ copy.validation }} · {{ answer.human_validation.length }}
              </h3>
              <ul class="m-0 grid list-disc gap-2 pl-5">
                <li
                  v-for="node in answer.human_validation"
                  :key="node.key"
                  :data-why-key="node.key"
                >
                  <span>{{ whyNodeTitle(node, locale) }}</span>
                  <UserModelingEpistemicBadge
                    :status="node.display_status"
                    :show-details="false"
                    :locale="locale"
                  />
                </li>
              </ul>
            </section>
            <section
              v-if="answer.declared_context.perspectives.length > 0"
              class="grid gap-2"
              data-testid="why-details-declared-context"
            >
              <h3 class="m-0 font-semibold">
                {{ copy.context }} · {{ answer.declared_context.perspectives.length }}
              </h3>
              <p class="m-0 text-xs">{{ copy.declared }}</p>
              <ul class="m-0 grid list-disc gap-2 pl-5">
                <li v-for="(item, index) in answer.declared_context.perspectives" :key="index">
                  {{ perspectiveName(item) }}
                  <span v-if="item.team_reference">
                    · {{ copy.version }} {{ item.team_reference.version_number }} ·
                    <span class="font-mono text-xs break-all">{{
                      item.team_reference.content_hash
                    }}</span></span
                  >
                </li>
              </ul>
            </section>
            <section
              v-if="answer.summary.stop_reasons.length > 0"
              class="grid gap-2"
              data-testid="why-details-interrupted"
            >
              <h3 class="m-0 font-semibold">
                {{ copy.interrupted }} · {{ answer.summary.stop_reasons.length }}
              </h3>
              <ul class="m-0 grid list-disc gap-1 pl-5 text-xs">
                <li v-for="(reason, index) in answer.summary.stop_reasons" :key="index">
                  {{ whyGapLabel(reason, locale) }}
                </li>
              </ul>
            </section>
            <section
              v-if="answer.gaps.length > 0"
              class="grid gap-2"
              data-testid="why-details-gaps"
            >
              <h3 class="m-0 font-semibold">{{ copy.missing }} · {{ answer.gaps.length }}</h3>
              <ul class="m-0 grid list-disc gap-2 pl-5 text-xs">
                <li v-for="(gap, index) in answer.gaps" :key="index" :data-gap-code="gap.code">
                  {{ whyGapLabel(gap.code, locale) }}
                  <span v-if="nodeTitles.has(gap.node_key)">
                    · {{ nodeTitles.get(gap.node_key) }}</span
                  >
                  <span v-if="gap.related_code" class="font-mono break-all">
                    · {{ gap.related_code }}</span
                  >
                </li>
              </ul>
            </section>
            <section v-if="answer.links.length > 0" class="grid gap-2" data-testid="why-links">
              <h3 class="m-0 font-semibold">{{ copy.links }}</h3>
              <ul class="m-0 grid list-disc gap-2 pl-5 text-xs">
                <li v-for="(link, index) in answer.links" :key="index">
                  <strong>{{ nodeTitles.get(link.source) ?? copy.missing }}</strong>
                  · {{ whyRelationLabel(link.kind, locale) }} →
                  <strong>{{ nodeTitles.get(link.target) ?? copy.missing }}</strong>
                </li>
              </ul>
            </section>
            <section
              v-for="direction in ['upstream', 'downstream'] as const"
              :key="direction"
              class="grid gap-2"
              :data-testid="`why-details-${direction}`"
            >
              <h3 class="m-0 font-semibold">{{ copy[direction] }}</h3>
              <ArtifactWhyNode
                v-for="node in answer[direction]"
                :key="node.key"
                :node="node"
                :locale="locale"
              />
            </section>
            <ul
              v-if="answer.limits.length > 0"
              class="m-0 list-disc pl-5 text-xs"
              data-testid="why-limits"
            >
              <li v-for="limit in answer.limits" :key="limit">{{ whyGapLabel(limit, locale) }}</li>
            </ul>
          </div>
        </details>
      </template>
    </div>
  </details>
</template>
