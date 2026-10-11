<script setup lang="ts">
import { computed, provide, ref, watch } from "vue";

import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import ProjectAcceptanceTestsPanel from "./ProjectAcceptanceTestsPanel.vue";
import ProjectDevelopmentPanel from "./ProjectDevelopmentPanel.vue";
import UiAgentMessage from "./UiAgentMessage.vue";
import UiButton from "./UiButton.vue";
import UiCommandLine from "./UiCommandLine.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";

import type { KnowledgePackagesApi } from "../api/knowledgePackages";
import { useAuthorizedRequest } from "../composables/useAuthorizedRequest";
import { useIntlFormats } from "../composables/useIntlFormats";
import { useAuthStore } from "../stores/auth";
import { useGuidanceStore } from "../stores/guidance";
import { useDesignStore } from "../stores/design";
import { useKnowledgePackagesStore, type AuthorizedRequest } from "../stores/knowledgePackages";
import { useUserModelingStore } from "../stores/userModeling";
import type { DeclarativePrototypePayload, DesignAlternativePayload } from "../types/design";
import type { KnowledgePackageVersionPayload, KnowledgeStage } from "../types/knowledgePackages";
import type { ProvidedPrototype } from "../types/workflowInputs";
import { designPackageCopy, designPackageSectionCopy } from "./designPackageCopy";
import { commandParts, fill } from "./textFormat";
import { whyMessages } from "./whyCopy";

type Locale = "en" | "it";
type HeroState = "complete" | "partial" | "waiting";

const HERO_IMAGE = "/home/pacchetto.webp";
const AGENT_AVATAR = "/team/fe.webp";
const STAGE_KEYS: readonly KnowledgeStage[] = ["brief", "team", "twins", "requirements", "design"];
const TWINS_STAGE = STAGE_KEYS.indexOf("twins");
const DESIGN_STAGE = STAGE_KEYS.indexOf("design");
const FOLDER_NAME_LIMIT = 40;
const COMMAND_BOX = "[&>code]:overflow-x-auto [&>code]:whitespace-pre [&>code]:contain-inline-size";
const TERMINAL_STEPS = [
  { key: "login", command: "ut login --studio {address}" },
  { key: "folder", command: "mkdir {folder}; cd {folder}" },
  { key: "link", command: "ut init --project {project} --mode design-code" },
  { key: "editor", command: "code ." },
] as const;
const DEVELOPMENT_STEPS = [
  { key: "git", command: "git init" },
  { key: "code", command: "ut code" },
  { key: "test", command: "ut test --static ." },
  { key: "verify", command: "ut verify" },
  { key: "align", command: "ut align" },
  { key: "alignDesign", command: "ut align --from-design" },
  { key: "push", command: "ut push" },
  { key: "learn", command: "ut twins update" },
  { key: "status", command: "ut status" },
] as const;

const props = withDefaults(
  defineProps<{
    projectId: string;
    stages: readonly { label: string; version: number | null; approved: boolean }[];
    locale?: Locale;
    authorize?: AuthorizedRequest;
    api?: KnowledgePackagesApi;
    saveExport?: (blob: Blob, fileName: string) => void;
    studioAddress?: string;
    sectionsMode?: boolean;
    providedPrototype?: ProvidedPrototype | null;
    providedDesignApproved?: boolean;
    active?: boolean;
  }>(),
  {
    locale: "en",
    studioAddress: () => window.location.origin,
    sectionsMode: false,
    providedPrototype: null,
    providedDesignApproved: false,
    active: true,
  },
);

const emit = defineEmits<{ "sections-changed": [] }>();

defineSlots<{
  preview?(props: {
    alternative: DesignAlternativePayload;
    prototype: DeclarativePrototypePayload | null;
  }): unknown;
}>();

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const auth = useAuthStore();
const authorizedRequest = useAuthorizedRequest(() => props.authorize);
const design = useDesignStore();
const modeling = useUserModelingStore();
const packages = useKnowledgePackagesStore();

const copy = computed(() =>
  props.sectionsMode
    ? { ...designPackageCopy[props.locale], ...designPackageSectionCopy[props.locale] }
    : designPackageCopy[props.locale],
);
const { dateFormat, listFormat } = useIntlFormats(() =>
  props.locale === "it" ? "it-IT" : "en-GB",
);
const busy = ref(false);
const error = ref<string | null>(null);
const outcome = ref<{ reused: boolean; number: number; file: string } | null>(null);

const heldCount = computed(() => {
  const missing = props.stages.findIndex((stage) => !stage.approved);
  return missing < 0 ? props.stages.length : missing;
});
const ready = computed(() => heldCount.value > 0);
const complete = computed(() => ready.value && heldCount.value === props.stages.length);
const twinsApproved = computed(() => props.stages[TWINS_STAGE]?.approved === true);
const designApproved = computed(() => props.stages[DESIGN_STAGE]?.approved === true);
const heroState = computed<HeroState>(() => {
  if (complete.value) {
    return "complete";
  }
  return ready.value ? "partial" : "waiting";
});
const hero = computed(() => {
  const text = copy.value;
  const states = {
    complete: { agent: text.agentReady, title: text.title, intro: text.intro },
    partial: { agent: text.agentPartial, title: text.titlePartial, intro: text.introPartial },
    waiting: { agent: text.agentWaiting, title: text.titleWaiting, intro: text.introWaiting },
  };
  return states[heroState.value];
});
const partialNote = computed(() => {
  if (heroState.value !== "partial") {
    return null;
  }
  const missing = props.stages.slice(heldCount.value).map((stage) => stage.label);
  const [one, many] = copy.value.partial;
  return fill(missing.length === 1 ? one : many, {
    held: heldText(heldCount.value, props.stages.length),
    steps: listFormat.value.format(missing),
  });
});
const versions = computed<KnowledgePackageVersionPayload[]>(() =>
  packages.projectId === props.projectId ? packages.versions : [],
);
const latest = computed(() => versions.value[0] ?? null);
const earlier = computed(() => versions.value.slice(1));
const folderName = computed(
  () => folderSlug(latest.value?.project_name ?? "") || copy.value.folder,
);
const guidance = useGuidanceStore();
const suppliedCopy = computed(() => whyMessages[props.locale]);
const terminalSteps = computed(() => {
  const values = {
    address: props.studioAddress,
    folder: folderName.value,
    project: props.projectId,
  };
  const steps = TERMINAL_STEPS.filter((step) => step.key !== "login" || !auth.isLocal);
  return steps.map((step) => ({
    key: step.key,
    text: copy.value.terminalSteps[step.key],
    command: fill(
      props.providedDesignApproved && step.key === "link"
        ? step.command.replace("--mode design-code", "--mode design")
        : step.command,
      values,
    ),
  }));
});
const developmentSteps = computed(() =>
  DEVELOPMENT_STEPS.map((step) => ({
    key: step.key,
    text: copy.value.developmentSteps[step.key],
    command: step.command,
  })),
);
const loadingHistory = computed(
  () => packages.projectId === props.projectId && packages.pending.load,
);
const selectedAlternative = computed(() =>
  !props.providedDesignApproved && design.projectId === props.projectId && designApproved.value
    ? design.selectedAlternative
    : null,
);
const prototype = computed(() => {
  const candidate = design.current?.package.prototype ?? null;
  return candidate && candidate.design_alternative_id === selectedAlternative.value?.id
    ? candidate
    : null;
});
const twins = computed(() => {
  const current =
    twinsApproved.value && modeling.projectId === props.projectId ? modeling.currentTwins : [];
  if (current.length > 0) {
    return current.map((twin) => ({ id: twin.id, name: twin.profile.name }));
  }
  return (latest.value?.twins ?? []).map((twin) => ({ id: twin.twin_id, name: twin.name }));
});
const counts = computed(() => {
  const version = latest.value;
  if (version === null) {
    return [];
  }
  return [
    {
      key: "diagrams",
      count: version.diagram_count,
      label: plural(version.diagram_count, "diagrams"),
    },
    { key: "tables", count: version.table_count, label: plural(version.table_count, "tables") },
    {
      key: "findings",
      count: version.feedback.findings,
      label: plural(version.feedback.findings, "findings"),
    },
  ];
});
function folderSlug(name: string): string {
  const slug = name
    .normalize("NFD")
    .replace(/\p{M}+/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
  return Array.from(slug).slice(0, FOLDER_NAME_LIMIT).join("").replace(/-+$/, "");
}

function plural(count: number, key: "twins" | "diagrams" | "tables" | "findings"): string {
  const [one, many] = copy.value[key];
  return count === 1 ? one : many;
}

function versionMeta(version: KnowledgePackageVersionPayload): string {
  return fill(copy.value.versionMeta, {
    date: dateFormat.value.format(new Date(version.created_at)),
    files: version.file_count,
  });
}

function heldText(count: number, total: number): string {
  const [one, many] = copy.value.held;
  return fill(count === 1 ? one : many, { count, total });
}

function versionProgress(version: KnowledgePackageVersionPayload): string {
  const held = heldText(version.progress.approved.length, STAGE_KEYS.length);
  const pending = version.progress.pending;
  const step = pending === null ? undefined : props.stages[STAGE_KEYS.indexOf(pending)]?.label;
  return step === undefined ? held : fill(copy.value.versionNext, { held, step });
}

function saveBlob(blob: Blob, fileName: string): void {
  if (props.saveExport !== undefined) {
    props.saveExport(blob, fileName);
    return;
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function failureMessage(fallback: string): string {
  const code = packages.error?.code ?? null;
  if (code === null) {
    return fallback;
  }
  if (code === "BRIEF_APPROVAL_REQUIRED") {
    return copy.value.notReady;
  }
  if (code === "TEAM_OUTDATED") {
    return copy.value.perspectivesBehind;
  }
  const sections: Readonly<Record<string, string>> = copy.value.outdated;
  const section = sections[code];
  if (section === undefined) {
    return fallback;
  }
  return fill(props.sectionsMode ? copy.value.behind : copy.value.behindStep, { section });
}

async function fetchVersion(number: number): Promise<string> {
  const result = await packages.download(props.projectId, number, authorizedRequest, props.api);
  saveBlob(result.blob, result.fileName);
  return result.fileName;
}

async function prepare(): Promise<void> {
  busy.value = true;
  error.value = null;
  outcome.value = null;

  try {
    const publication = await packages.publish(props.projectId, authorizedRequest, props.api);
    emit("sections-changed");
    const file = await fetchVersion(publication.version.version_number);
    outcome.value = {
      reused: publication.reused,
      number: publication.version.version_number,
      file,
    };
  } catch {
    error.value = failureMessage(copy.value.failed);
  } finally {
    busy.value = false;
  }
}

async function download(version: KnowledgePackageVersionPayload): Promise<void> {
  busy.value = true;
  error.value = null;

  try {
    await fetchVersion(version.version_number);
  } catch {
    error.value = failureMessage(copy.value.downloadFailed);
  } finally {
    busy.value = false;
  }
}

async function loadHistory(): Promise<void> {
  try {
    await packages.load(props.projectId, authorizedRequest, props.api);
  } catch {
    error.value = null;
  }
}

watch(() => props.projectId, loadHistory, { immediate: true });
</script>

<template>
  <div
    class="grid grid-cols-1 gap-4 text-on-night"
    data-surface="night"
    data-testid="design-package"
  >
    <UiAgentMessage
      v-if="!guidance.expert"
      :role-label="copy.agentRole"
      :avatar="AGENT_AVATAR"
      class="mb-1"
    >
      {{ hero.agent }}
    </UiAgentMessage>

    <section
      class="@container relative isolate overflow-hidden rounded-[20px] border border-on-night/14 bg-night"
      aria-labelledby="design-package-title"
      data-testid="package-hero"
    >
      <div class="flex flex-col @3xl:min-h-[300px] @3xl:flex-row @3xl:items-center">
        <div
          class="relative h-44 shrink-0 @3xl:absolute @3xl:inset-0 @3xl:-z-10 @3xl:h-auto"
          aria-hidden="true"
          data-testid="package-hero-image"
        >
          <img
            :src="HERO_IMAGE"
            alt=""
            decoding="async"
            class="h-full w-full object-cover object-right"
          />
          <div
            class="absolute inset-0 bg-linear-to-b from-night/0 via-night/15 to-night @3xl:bg-linear-to-r @3xl:from-night/95 @3xl:via-night/70 @3xl:via-45% @3xl:to-night/0 @3xl:to-75%"
          />
        </div>
        <div class="relative max-w-[560px] px-6 pt-1 pb-8 @3xl:p-8">
          <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
            {{ copy.eyebrow }}
          </p>
          <h2
            id="design-package-title"
            class="mt-3 mb-2.5 font-display text-[clamp(22px,2.4vw,32px)] leading-[1.12] font-extralight tracking-display text-balance uppercase"
          >
            {{ hero.title }}
          </h2>
          <p
            v-if="!guidance.expert"
            class="m-0 mb-6 text-[15px] leading-[1.55] text-on-night-2 @3xl:max-w-[calc(52cqw-2rem)]"
          >
            {{ hero.intro }}
          </p>
          <p
            v-if="!ready"
            class="m-0 mb-6 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 px-4 py-3 text-sm leading-normal text-warn-on-night"
            data-testid="package-not-ready"
          >
            {{ copy.notReady }}
          </p>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
            <UiButton
              variant="pill"
              size="lg"
              :disabled="busy || !ready"
              data-testid="download-package"
              @click="prepare"
            >
              {{ busy ? copy.preparing : copy.prepare }}
            </UiButton>
            <span
              v-if="latest"
              class="font-mono text-xs text-on-night-3"
              data-testid="package-latest"
            >
              {{ fill(copy.latest, { files: latest.file_count, number: latest.version_number }) }}
            </span>
          </div>
          <p
            v-if="partialNote"
            class="m-0 mt-4 text-sm leading-normal text-on-night-2 @3xl:max-w-[calc(52cqw-2rem)]"
            data-testid="package-partial"
          >
            {{ partialNote }} {{ copy.partialRule }}
          </p>
          <div aria-live="polite">
            <p
              v-if="outcome"
              class="m-0 mt-4 rounded-field border border-petrol-on-night/50 bg-petrol-on-night/10 px-4 py-3 text-sm leading-normal font-semibold wrap-anywhere text-petrol-on-night-2"
              data-testid="download-done"
            >
              {{
                fill(outcome.reused ? copy.reused : copy.created, {
                  number: outcome.number,
                  file: outcome.file,
                })
              }}
            </p>
          </div>
          <p
            v-if="error"
            class="m-0 mt-4 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm leading-normal font-semibold text-fail-on-night"
            role="alert"
            data-testid="download-error"
          >
            {{ error }}
          </p>
        </div>
      </div>
    </section>

    <div class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,300px),1fr))] gap-4">
      <section
        class="rounded-tile border border-night-line bg-night-raised p-6"
        aria-labelledby="package-contents-title"
        data-testid="package-summary"
      >
        <h2 id="package-contents-title" class="m-0 mb-4 text-lg leading-tight font-semibold">
          {{ copy.contents }}
        </h2>
        <ul class="m-0 list-none p-0">
          <li class="flex items-baseline gap-3.5 border-t border-on-night/10 py-2.5">
            <span class="min-w-12 font-display text-[28px] leading-none font-extralight">
              {{ twins.length }}
            </span>
            {{ " " }}
            <span class="min-w-0 text-[15px] leading-snug text-on-night-2">
              {{ plural(twins.length, "twins") }}
              <span v-if="twins.length > 0" class="mt-1 block text-[13px] text-on-night-3">
                <template v-for="(twin, index) in twins" :key="twin.id">
                  <span data-testid="package-twin">{{ twin.name }}</span>
                  <template v-if="index < twins.length - 1">, </template>
                </template>
              </span>
            </span>
          </li>
        </ul>
        <ul v-if="counts.length > 0" class="m-0 list-none p-0" data-testid="package-contents">
          <li
            v-for="row in counts"
            :key="row.key"
            class="flex items-baseline gap-3.5 border-t border-on-night/10 py-2.5"
          >
            <span class="min-w-12 font-display text-[28px] leading-none font-extralight">
              {{ row.count }}
            </span>
            {{ " " }}
            <span class="min-w-0 text-[15px] leading-snug text-on-night-2">
              {{ row.label }}
              <span
                v-if="row.key === 'findings' && latest"
                class="mt-1 block text-[13px] text-on-night-3"
              >
                {{
                  fill(copy.feedback, {
                    reviews: latest.feedback.reviews,
                    decisions: latest.feedback.decisions,
                    discussions: latest.feedback.discussions,
                  })
                }}
              </span>
            </span>
          </li>
        </ul>
        <p
          v-else
          class="m-0 border-t border-on-night/10 pt-2.5 text-sm leading-normal text-on-night-3"
          data-testid="package-counted-later"
        >
          {{ copy.countedLater }}
        </p>

        <div
          v-if="selectedAlternative"
          class="mt-4 flex flex-wrap items-center gap-3.5 rounded-field border border-night-line p-3"
          data-testid="package-design"
        >
          <div
            class="relative h-[100px] w-[160px] shrink-0 overflow-hidden rounded-lg bg-white"
            data-testid="package-preview"
          >
            <slot name="preview" :alternative="selectedAlternative" :prototype="prototype">
              <div
                v-if="prototype"
                class="pointer-events-none w-[960px] origin-top-left scale-[0.16667]"
                :inert="true"
                aria-hidden="true"
                data-testid="package-preview-default"
              >
                <DeclarativePrototypePreview
                  :prototype="prototype"
                  :visual="selectedAlternative.visual_language"
                  :locale="locale"
                />
              </div>
              <p
                v-else
                class="m-0 grid h-full place-items-center bg-surface-2 px-2 text-center text-xs text-ink-3"
                data-testid="package-preview-missing"
              >
                {{ copy.noPreview }}
              </p>
            </slot>
          </div>
          <div class="min-w-36 flex-1">
            <p class="m-0 text-xs text-on-night-3">{{ copy.design }}</p>
            <p
              class="m-0 mt-0.5 text-[15px] leading-snug font-semibold"
              data-testid="package-alternative"
            >
              {{ selectedAlternative.code }} · {{ selectedAlternative.title }}
            </p>
          </div>
        </div>
        <p
          v-else-if="providedPrototype && providedDesignApproved"
          class="m-0 mt-4 rounded-field border border-night-line p-3 text-sm leading-normal"
          data-testid="package-provided-design"
        >
          {{ suppliedCopy.supplied }} · {{ providedPrototype.code }} · {{ providedPrototype.title
          }}<span v-if="providedPrototype.declared_origin" class="mt-1 block"
            >{{ suppliedCopy.declaredOrigin }}: {{ providedPrototype.declared_origin }}</span
          ><span class="mt-2 block text-warn-on-night">{{
            suppliedCopy.prototypeEvaluationLimit
          }}</span>
        </p>
        <p
          v-else
          class="m-0 mt-4 rounded-field border border-night-line p-3 text-sm leading-normal text-on-night-3"
          data-testid="package-no-design"
        >
          {{ copy.noDesign }}
        </p>

        <details
          class="group mt-4 border-t border-on-night/10 pt-1"
          :open="!complete"
          data-testid="package-path"
        >
          <summary
            class="flex min-h-11 cursor-pointer list-none items-center gap-2.5 text-sm font-semibold text-petrol-on-night-2 [&::-webkit-details-marker]:hidden"
          >
            <span
              aria-hidden="true"
              class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-petrol-on-night-2 transition-transform duration-150 group-open:rotate-45"
            />
            {{ copy.path }}
          </summary>
          <ol class="m-0 grid list-none gap-1.5 p-0 pb-1">
            <li
              v-for="(stage, index) in stages"
              :key="stage.label"
              class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-on-night/10 py-1.5 text-sm"
              data-testid="package-stage"
            >
              <span class="font-semibold">{{ index + 1 }}. {{ stage.label }}</span>
              {{ " " }}
              <span
                :class="[
                  'font-mono text-xs',
                  stage.approved ? 'text-petrol-on-night-2' : 'text-warn-on-night',
                ]"
              >
                {{
                  stage.version === null
                    ? copy.noVersion
                    : fill(copy.stageVersion, { number: stage.version })
                }}
                · {{ stage.approved ? copy.approved : copy.pending }}
              </span>
            </li>
          </ol>
        </details>
      </section>

      <section
        class="rounded-tile border border-night-line bg-night-raised p-6"
        aria-labelledby="package-howto-title"
        data-testid="package-howto"
      >
        <h2 id="package-howto-title" class="m-0 mb-4 text-lg leading-tight font-semibold">
          {{ copy.howTo }}
        </h2>
        <h3 class="m-0 mb-3 text-[15px] leading-snug font-semibold" data-testid="package-cli-title">
          <template v-for="part in commandParts(copy.terminalWay)" :key="part.key">
            <code
              v-if="part.command"
              class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
              >{{ part.text }}</code
            >
            <template v-else>{{ part.text }}</template>
          </template>
        </h3>
        <ol class="m-0 list-none space-y-4 p-0" data-testid="package-cli-steps">
          <li
            v-for="(step, index) in terminalSteps"
            :key="step.key"
            class="flex gap-3"
            data-testid="package-cli-step"
          >
            <span
              class="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-full border-[1.5px] border-on-night/50 text-xs font-semibold text-on-night"
              aria-hidden="true"
            >
              {{ index + 1 }}
            </span>
            <div class="min-w-0 flex-1">
              <p
                class="m-0 mb-2 text-[15px] leading-normal text-on-night-2"
                data-testid="package-cli-text"
              >
                <template v-for="part in commandParts(step.text)" :key="part.key">
                  <code
                    v-if="part.command"
                    class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                    >{{ part.text }}</code
                  >
                  <template v-else>{{ part.text }}</template>
                </template>
              </p>
              <UiCommandLine
                :class="COMMAND_BOX"
                :command="step.command"
                :copy-label="copy.copyCommand"
                :copied-label="copy.commandCopied"
                :failed-label="copy.commandNotCopied"
              />
            </div>
          </li>
        </ol>
        <div
          v-if="providedDesignApproved"
          class="mt-6 grid gap-3"
          data-testid="package-provided-limits"
        >
          <p class="text-sm">{{ suppliedCopy.prototypeEvaluationLimit }}</p>
          <p class="text-sm">{{ suppliedCopy.gaps.PROVIDED_PROTOTYPE_CODE_UNAVAILABLE }}</p>
          <UiCommandLine
            :class="COMMAND_BOX"
            command="ut design show"
            :copy-label="copy.copyCommand"
            :copied-label="copy.commandCopied"
            :failed-label="copy.commandNotCopied"
          />
          <UiCommandLine
            :class="COMMAND_BOX"
            command="ut design open"
            :copy-label="copy.copyCommand"
            :copied-label="copy.commandCopied"
            :failed-label="copy.commandNotCopied"
          />
        </div>
        <template v-if="designApproved && !providedDesignApproved">
          <h3
            class="m-0 mt-6 mb-3 text-[15px] leading-snug font-semibold"
            data-testid="package-development-title"
          >
            {{ copy.developmentWay }}
          </h3>
          <ul class="m-0 list-none space-y-4 p-0" data-testid="package-development-steps">
            <li
              v-for="step in developmentSteps"
              :key="step.key"
              data-testid="package-development-step"
            >
              <p
                class="m-0 mb-2 text-[15px] leading-normal text-on-night-2"
                data-testid="package-development-text"
              >
                <template v-for="part in commandParts(step.text)" :key="part.key">
                  <code
                    v-if="part.command"
                    class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                    >{{ part.text }}</code
                  >
                  <template v-else>{{ part.text }}</template>
                </template>
              </p>
              <UiCommandLine
                :class="COMMAND_BOX"
                :command="step.command"
                :copy-label="copy.copyCommand"
                :copied-label="copy.commandCopied"
                :failed-label="copy.commandNotCopied"
              />
            </li>
          </ul>
        </template>
        <details class="group mt-6 border-t border-on-night/10 pt-1" data-testid="package-zip">
          <summary
            class="flex min-h-11 cursor-pointer list-none items-center gap-2.5 text-sm font-semibold text-petrol-on-night-2 [&::-webkit-details-marker]:hidden"
          >
            <span
              aria-hidden="true"
              class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-petrol-on-night-2 transition-transform duration-150 group-open:rotate-45"
            />
            <span>
              <template v-for="part in commandParts(copy.zipWay)" :key="part.key">
                <code
                  v-if="part.command"
                  class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                  >{{ part.text }}</code
                >
                <template v-else>{{ part.text }}</template>
              </template>
            </span>
          </summary>
          <ol class="m-0 grid list-none gap-3.5 p-0 pt-2 pb-1">
            <li
              v-for="(step, index) in copy.steps"
              :key="step"
              class="flex gap-3 text-[15px] leading-normal text-on-night-2"
              data-testid="package-step"
            >
              <span
                class="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-full border-[1.5px] border-on-night/50 text-xs font-semibold text-on-night"
                aria-hidden="true"
              >
                {{ index + 1 }}
              </span>
              <span>{{ step }}</span>
            </li>
          </ol>
        </details>
      </section>
    </div>

    <section
      class="rounded-tile border border-night-line bg-night-raised px-6 py-[18px]"
      aria-labelledby="package-history-title"
      data-testid="package-history"
    >
      <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div class="min-w-[min(100%,15rem)] flex-1">
          <h2 id="package-history-title" class="m-0 text-base leading-tight font-semibold">
            {{ copy.history }}
          </h2>
          <p
            class="m-0 mt-0.5 text-sm leading-normal text-on-night-3"
            data-testid="package-history-intro"
          >
            <template v-for="part in commandParts(copy.historyIntro)" :key="part.key">
              <code
                v-if="part.command"
                class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                >{{ part.text }}</code
              >
              <template v-else>{{ part.text }}</template>
            </template>
          </p>
        </div>
        <div
          v-if="latest"
          class="flex flex-wrap items-center gap-x-4 gap-y-2"
          data-testid="package-version"
        >
          <p class="m-0 text-sm text-on-night-2">
            <strong class="font-semibold text-on-night" data-testid="package-version-title">
              {{ fill(copy.version, { number: latest.version_number }) }}
            </strong>
            · {{ versionMeta(latest) }} ·
            <span data-testid="package-version-progress">{{ versionProgress(latest) }}</span>
          </p>
          <UiButton
            variant="outline"
            :disabled="busy"
            :aria-label="fill(copy.downloadVersion, { number: latest.version_number })"
            data-testid="download-version"
            @click="download(latest)"
          >
            {{ copy.download }}
          </UiButton>
        </div>
        <p
          v-else
          class="m-0 text-sm text-on-night-3"
          :aria-busy="loadingHistory ? 'true' : undefined"
          data-testid="package-no-history"
        >
          {{ loadingHistory ? copy.loadingHistory : copy.noHistory }}
        </p>
      </div>
      <details v-if="earlier.length > 0" class="group mt-3 border-t border-on-night/10 pt-1">
        <summary
          class="flex min-h-11 cursor-pointer list-none items-center gap-2.5 text-sm font-semibold text-petrol-on-night-2 [&::-webkit-details-marker]:hidden"
        >
          <span
            aria-hidden="true"
            class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-petrol-on-night-2 transition-transform duration-150 group-open:rotate-45"
          />
          {{ fill(copy.earlier, { count: earlier.length }) }}
        </summary>
        <ol class="m-0 grid list-none gap-2 p-0">
          <li
            v-for="version in earlier"
            :key="version.id"
            class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-on-night/10 py-2"
            data-testid="package-version"
          >
            <p class="m-0 text-sm text-on-night-2">
              <strong class="font-semibold text-on-night" data-testid="package-version-title">
                {{ fill(copy.version, { number: version.version_number }) }}
              </strong>
              · {{ versionMeta(version) }} ·
              <span data-testid="package-version-progress">{{ versionProgress(version) }}</span>
            </p>
            <UiButton
              variant="outline"
              :disabled="busy"
              :aria-label="fill(copy.downloadVersion, { number: version.version_number })"
              data-testid="download-version"
              @click="download(version)"
            >
              {{ copy.download }}
            </UiButton>
          </li>
        </ol>
      </details>
      <p
        v-if="designApproved && !providedDesignApproved"
        class="m-0 mt-3 border-t border-on-night/10 pt-3 text-sm leading-normal text-on-night-2"
        data-testid="package-terminal"
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
    </section>

    <ProjectDevelopmentPanel
      v-if="designApproved && !providedDesignApproved"
      :project-id="projectId"
      :locale="locale"
      :active="active"
      :authorize="authorizedRequest"
    />

    <ProjectAcceptanceTestsPanel
      v-if="designApproved && !providedDesignApproved"
      :project-id="projectId"
      :locale="locale"
      :authorize="authorizedRequest"
    />
  </div>
</template>
