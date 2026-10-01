<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import { PROJECT_STAGES, type ProjectMode, type ProjectResponse } from "@/api/contracts";
import ProjectImportDialog from "@/components/ProjectImportDialog.vue";
import UiButton from "@/components/UiButton.vue";
import UiStateBlock from "@/components/UiStateBlock.vue";
import UiSurface from "@/components/UiSurface.vue";
import { useAuthStore } from "@/stores/auth";
import { useProjectsStore } from "@/stores/projects";
import type { ProjectImportPayload } from "@/types/projectImports";

type Start = ProjectMode | "folder";

const LIST_LIMIT = 12;
const STEP_COUNT = PROJECT_STAGES.length;
const SEGMENT_COLORS = {
  done: "bg-petrol-on-night",
  current: "bg-on-night",
  pending: "bg-on-night/14",
} as const;
const picture = "/home/bento.webp";
const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";

const messages = {
  it: {
    workspace: "Area di lavoro",
    count: ["{n} progetto", "{n} progetti"],
    stepPosition: "Passo {n} di {total}",
    yourTurn: "Tocca a te:",
    stages: {
      BRIEF: "Brief",
      TEAM: "Prospettive",
      USER_TWINS: "User Twin",
      REQUIREMENTS: "Definizione",
      DESIGN: "Design e valutazione",
      PACKAGE: "Dossier",
    },
    actions: {
      DESCRIBE_IDEA: "Racconta la tua idea",
      APPROVE_BRIEF: "Approva il brief",
      APPROVE_TEAM: "Approva le prospettive",
      CONFIRM_TWINS: "Conferma i twin",
      APPROVE_REQUIREMENTS: "Approva i requisiti",
      APPROVE_DESIGN: "Scegli e approva il design",
      DOWNLOAD_FOLDER: "Scarica la cartella",
    },
    updated: "Aggiornato il",
    open: "Continua",
    openLabel: "Continua il progetto {name}",
    showMore: ["Mostra l'altro progetto", "Mostra gli altri {n} progetti"],
    dialogTitle: "Nuovo progetto",
    folder: "Una cartella di conoscenza",
    starts: {
      GREENFIELD_GENERATION: "La racconti in un dialogo: lo Studio ti fa una domanda alla volta.",
      BROWNFIELD_ASSESSMENT:
        "Parti da un prodotto che esiste già: lo Studio ne tiene conto quando prepara le prospettive.",
      folder:
        "Carichi l'archivio di un altro progetto: i passi arrivano compilati, tu li rivedi uno per uno.",
    },
    nameLabel: "Come si chiama?",
    namePlaceholder: "Per esempio: Promemoria restituzioni",
    create: "Crea il progetto",
  },
  en: {
    workspace: "Workspace",
    count: ["{n} project", "{n} projects"],
    stepPosition: "Step {n} of {total}",
    yourTurn: "Your turn:",
    stages: {
      BRIEF: "Brief",
      TEAM: "Perspectives",
      USER_TWINS: "User Twin",
      REQUIREMENTS: "Definition",
      DESIGN: "Design & Evaluation",
      PACKAGE: "Dossier",
    },
    actions: {
      DESCRIBE_IDEA: "Tell your idea",
      APPROVE_BRIEF: "Approve the brief",
      APPROVE_TEAM: "Approve the perspectives",
      CONFIRM_TWINS: "Confirm the twins",
      APPROVE_REQUIREMENTS: "Approve the requirements",
      APPROVE_DESIGN: "Choose and approve the design",
      DOWNLOAD_FOLDER: "Download the folder",
    },
    updated: "Updated on",
    open: "Continue",
    openLabel: "Continue the project {name}",
    showMore: ["Show the other project", "Show the other {n} projects"],
    dialogTitle: "New project",
    folder: "A knowledge folder",
    starts: {
      GREENFIELD_GENERATION:
        "You tell it in a conversation: the Studio asks you one question at a time.",
      BROWNFIELD_ASSESSMENT:
        "Start from a product that already exists: the Studio takes it into account when it prepares the perspectives.",
      folder:
        "You load the archive of another project: the steps arrive filled in, and you review them one by one.",
    },
    nameLabel: "What is it called?",
    namePlaceholder: "For example: Book return reminders",
    create: "Create the project",
  },
} as const;

const { t, te, locale } = useI18n({
  useScope: "global",
});
const router = useRouter();
const auth = useAuthStore();
const projectStore = useProjectsStore();

const { projects, loading, errorDetail } = storeToRefs(projectStore);

const copy = computed(() => messages[locale.value === "it" ? "it" : "en"]);
const dialogOpen = ref(false);
const start = ref<Start>("GREENFIELD_GENERATION");
const displayName = ref("");
const showingAll = ref(false);
const imageShown = ref(false);
const dialog = ref<HTMLElement | null>(null);
const list = ref<HTMLElement | null>(null);
const importDialog = ref<InstanceType<typeof ProjectImportDialog> | null>(null);
const dialogTitleId = `new-project-title-${useId()}`;
let opener: HTMLElement | null = null;

const importing = computed(() => dialogOpen.value && start.value === "folder");
const visibleProjects = computed(() =>
  showingAll.value ? projects.value : projects.value.slice(0, LIST_LIMIT),
);
const visibleRows = computed(() =>
  visibleProjects.value.map((project) => ({ project, progress: progressOf(project) })),
);
const hiddenCount = computed(() => projects.value.length - visibleProjects.value.length);
const workspace = computed(() =>
  projects.value.length === 0
    ? copy.value.workspace
    : `${copy.value.workspace} · ${plural(copy.value.count, projects.value.length)}`,
);
const errorTitle = computed(() =>
  t(
    te(`projects.errors.${errorDetail.value}`)
      ? `projects.errors.${errorDetail.value}`
      : "projects.errors.unexpected_error",
  ),
);
const startOptions = computed(() => [
  {
    value: "GREENFIELD_GENERATION" as const,
    key: "idea",
    title: t("projects.modes.greenfield"),
    text: copy.value.starts.GREENFIELD_GENERATION,
  },
  {
    value: "BROWNFIELD_ASSESSMENT" as const,
    key: "existing",
    title: t("projects.modes.brownfield"),
    text: copy.value.starts.BROWNFIELD_ASSESSMENT,
  },
  {
    value: "folder" as const,
    key: "folder",
    title: copy.value.folder,
    text: copy.value.starts.folder,
  },
]);

onMounted(() => {
  void projectStore.loadProjects(apiClient, auth);
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(() => {
      imageShown.value = true;
    });
    return;
  }
  imageShown.value = true;
});

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function plural(forms: readonly [string, string], count: number): string {
  return fill(count === 1 ? forms[0] : forms[1], { n: count });
}

function progressOf(project: ProjectResponse): {
  step: number;
  stage: string;
  action: string | null;
} | null {
  const stage = project.current_stage;
  if (stage === undefined) return null;
  const action = project.next_action;
  return {
    step: PROJECT_STAGES.indexOf(stage) + 1,
    stage: copy.value.stages[stage],
    action: action === undefined ? null : copy.value.actions[action],
  };
}

function segmentState(segment: number, step: number): "done" | "current" | "pending" {
  if (segment === step) return "current";
  return segment < step ? "done" : "pending";
}

async function openDialog(choice: Start): Promise<void> {
  start.value = choice;
  if (!dialogOpen.value) {
    opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }
  dialogOpen.value = true;
  await nextTick();
  dialog.value?.focus();
}

function closeDialog(): void {
  dialogOpen.value = false;
  opener?.focus();
  opener = null;
}

function tabbable(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (element) =>
      !(element instanceof HTMLInputElement && element.type === "radio" && !element.checked),
  );
}

function onDialogKeydown(event: KeyboardEvent): void {
  const container = dialog.value;
  if (container === null) return;
  if (event.key === "Escape") {
    if (importDialog.value?.busy) return;
    event.preventDefault();
    closeDialog();
    return;
  }
  if (event.key !== "Tab") return;
  const items = tabbable(container);
  const first = items[0];
  const last = items[items.length - 1];
  if (first === undefined || last === undefined) return;
  const active = document.activeElement;
  if (event.shiftKey && (active === first || active === container)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

async function showAll(): Promise<void> {
  showingAll.value = true;
  await nextTick();
  list.value?.querySelectorAll<HTMLElement>("[data-project-link]")[LIST_LIMIT]?.focus();
}

async function onImported(payload: ProjectImportPayload): Promise<void> {
  closeDialog();
  await projectStore.loadProjects(apiClient, auth);
  await router.push({
    name: "project-detail",
    params: {
      projectId: payload.project.id,
    },
  });
}

function updatedOn(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(locale.value, { dateStyle: "medium" }).format(parsed);
}

async function createProject(): Promise<void> {
  const mode = start.value;
  if (mode === "folder") return;
  const project = await projectStore.createProject(apiClient, auth, {
    display_name: displayName.value,
    mode,
  });

  if (project !== null) {
    displayName.value = "";
    dialogOpen.value = false;
    opener = null;

    await router.push({
      name: "project-detail",
      params: {
        projectId: project.id,
      },
    });
  }
}
</script>

<template>
  <div>
    <UiSurface
      as="section"
      tone="night"
      :padded="false"
      class="overflow-hidden"
      aria-labelledby="projects-title"
      data-testid="projects-screen"
    >
      <div
        class="absolute top-0 right-0 -z-1 h-[420px] w-[62%] overflow-hidden max-sm:w-full max-sm:opacity-35"
        aria-hidden="true"
      >
        <img
          :src="picture"
          alt=""
          :class="[
            'block h-full w-full object-cover object-right motion-safe:transition-[opacity,scale] motion-safe:duration-[1200ms,2400ms] motion-safe:ease-[ease,cubic-bezier(0.16,0.8,0.2,1)]',
            imageShown ? 'scale-100 opacity-100' : 'motion-safe:scale-110 motion-safe:opacity-0',
          ]"
        />
        <div
          class="absolute inset-0 bg-[linear-gradient(90deg,#0f1112_0%,rgba(15,17,18,0.3)_45%,rgba(15,17,18,0)_70%),linear-gradient(0deg,#0f1112_0%,rgba(15,17,18,0)_45%)]"
        />
      </div>

      <header
        class="flex min-h-[360px] flex-wrap items-end gap-6 px-[clamp(24px,5vw,64px)] pt-[clamp(40px,5vw,64px)] pb-10"
      >
        <div class="flex-[1_1_340px]">
          <p
            class="m-0 mb-[18px] font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase motion-safe:animate-reveal"
            data-testid="projects-count"
          >
            {{ workspace }}
          </p>
          <h1
            id="projects-title"
            class="m-0 mb-4 font-display text-[clamp(30px,3.8vw,54px)] leading-[1.06] font-extralight tracking-display uppercase motion-safe:animate-reveal motion-safe:[animation-delay:100ms]"
          >
            {{ t("projects.listTitle") }}
          </h1>
          <p
            class="m-0 max-w-[420px] border-l border-on-night/40 pl-4 text-[17px] leading-[1.55] text-on-night-2 motion-safe:animate-reveal motion-safe:[animation-delay:200ms]"
          >
            {{ t("projects.description") }}
          </p>
        </div>
        <div
          class="flex flex-wrap gap-2.5 motion-safe:animate-reveal motion-safe:[animation-delay:300ms]"
        >
          <UiButton
            variant="outline"
            size="lg"
            class="backdrop-blur-[10px]"
            aria-haspopup="dialog"
            data-testid="import-project"
            @click="openDialog('folder')"
          >
            {{ t("projects.import") }}
          </UiButton>
          <UiButton
            variant="pill"
            size="lg"
            aria-haspopup="dialog"
            data-testid="new-project"
            @click="openDialog('GREENFIELD_GENERATION')"
          >
            {{ t("projects.new") }}
          </UiButton>
        </div>
      </header>

      <div class="border-t border-night-line px-[clamp(24px,5vw,64px)] pb-[clamp(32px,4vw,56px)]">
        <UiStateBlock
          v-if="errorDetail && !dialogOpen"
          kind="error"
          class="mt-6"
          :title="errorTitle"
        />

        <UiStateBlock v-if="loading && projects.length === 0" kind="loading" class="mt-6" />
        <UiStateBlock
          v-else-if="projects.length === 0 && !errorDetail"
          kind="empty"
          class="mt-6"
          :title="t('projects.emptyTitle')"
          :text="t('projects.emptyDescription')"
        />
        <ul
          v-else-if="projects.length > 0"
          ref="list"
          class="m-0 list-none p-0"
          data-testid="project-rows"
        >
          <li
            v-for="({ project, progress }, index) in visibleRows"
            :key="project.id"
            :class="[
              'grid gap-y-4 border-b border-night-line py-5 motion-safe:animate-reveal sm:items-center sm:gap-x-6',
              progress
                ? 'grid-cols-[auto_minmax(0,1fr)] gap-x-4 sm:grid-cols-[auto_minmax(0,1fr)_auto]'
                : 'sm:grid-cols-[minmax(0,1fr)_auto]',
            ]"
            :style="{ animationDelay: `${Math.min(index % LIST_LIMIT, 8) * 60}ms` }"
            data-testid="project-row"
            :data-project-stage="project.current_stage"
          >
            <div
              v-if="progress"
              class="flex min-w-[84px] items-baseline gap-1 self-start max-sm:row-span-2 sm:self-center"
              aria-hidden="true"
              data-testid="project-step-number"
            >
              <span
                class="font-display text-[34px] leading-none font-extralight tracking-[-0.02em]"
              >
                {{ String(progress.step).padStart(2, "0") }}
              </span>
              <span class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                /{{ String(STEP_COUNT).padStart(2, "0") }}
              </span>
            </div>
            <div class="flex min-w-0 flex-col gap-2.5">
              <p class="m-0 text-[17px] leading-[1.3] font-semibold break-words">
                {{ project.display_name }}
              </p>
              <div class="flex flex-wrap items-center gap-x-5 gap-y-2">
                <template v-if="progress">
                  <span
                    class="font-mono text-[11px] tracking-label text-on-night-3 uppercase"
                    data-testid="project-stage"
                  >
                    {{ progress.stage }}
                  </span>
                  <span class="flex w-[150px] gap-1" data-testid="project-step-track">
                    <span class="sr-only">
                      {{ fill(copy.stepPosition, { n: progress.step, total: STEP_COUNT }) }}
                    </span>
                    <span
                      v-for="segment in STEP_COUNT"
                      :key="segment"
                      :class="[
                        'h-1 flex-1 rounded-[2px]',
                        SEGMENT_COLORS[segmentState(segment, progress.step)],
                      ]"
                      :data-step-state="segmentState(segment, progress.step)"
                      aria-hidden="true"
                    />
                  </span>
                  <span
                    v-if="progress.action"
                    class="text-sm text-on-night-2"
                    data-testid="project-next"
                  >
                    {{ copy.yourTurn }} {{ progress.action }}
                  </span>
                </template>
                <span
                  v-if="project.mode === 'BROWNFIELD_ASSESSMENT'"
                  class="font-mono text-[11px] tracking-label text-on-night-3 uppercase"
                >
                  {{ t("projects.modes.brownfield") }}
                </span>
                <span class="font-mono text-xs text-on-night-3">
                  <span class="sr-only">{{ copy.updated }} </span>
                  <time :datetime="project.updated_at">{{ updatedOn(project.updated_at) }}</time>
                </span>
              </div>
            </div>
            <UiButton
              variant="outline"
              :class="['justify-self-start', progress ? 'max-sm:col-start-2' : '']"
              :to="{
                name: 'project-detail',
                params: {
                  projectId: project.id,
                },
              }"
              :aria-label="fill(copy.openLabel, { name: project.display_name })"
              data-project-link
            >
              {{ copy.open }}
            </UiButton>
          </li>
        </ul>

        <div v-if="hiddenCount > 0" class="pt-6">
          <UiButton variant="outline" data-testid="show-all-projects" @click="showAll">
            {{ plural(copy.showMore, hiddenCount) }}
          </UiButton>
        </div>
      </div>
    </UiSurface>

    <div
      v-if="dialogOpen"
      class="fixed inset-0 z-50 flex overflow-y-auto overscroll-contain bg-ink/40 p-4 sm:p-6"
      data-testid="new-project-dialog"
    >
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="dialogTitleId"
        tabindex="-1"
        class="m-auto flex w-full max-w-[640px] flex-col gap-5 rounded-[20px] bg-surface p-6 text-ink shadow-dialog outline-none sm:p-8"
        @keydown="onDialogKeydown"
      >
        <h2
          :id="dialogTitleId"
          class="m-0 text-[26px] leading-tight font-semibold tracking-[-0.02em]"
        >
          {{ copy.dialogTitle }}
        </h2>

        <fieldset class="m-0 flex min-w-0 flex-col border-0 p-0">
          <legend class="mb-2 p-0 text-sm font-semibold">{{ t("projects.create.mode") }}</legend>
          <div class="grid gap-3 sm:grid-cols-3">
            <label
              v-for="option in startOptions"
              :key="option.value"
              class="flex cursor-pointer flex-col gap-1.5 rounded-panel border border-line-strong bg-surface p-4 transition-colors duration-150 hover:border-action/60 has-checked:border-action has-checked:bg-action-soft has-checked:ring-1 has-checked:ring-action has-focus-visible:outline-3 has-focus-visible:outline-offset-2 has-focus-visible:outline-action sm:min-h-[120px]"
              :data-testid="`project-start-${option.key}`"
            >
              <input
                v-model="start"
                class="sr-only"
                type="radio"
                name="project-start"
                :value="option.value"
              />
              <span class="text-base leading-snug font-semibold">{{ option.title }}</span>
              <span class="text-sm leading-[1.45] text-ink-3">{{ option.text }}</span>
            </label>
          </div>
        </fieldset>

        <ProjectImportDialog
          v-if="importing"
          ref="importDialog"
          :locale="locale === 'it' ? 'it' : 'en'"
          @imported="onImported"
          @cancel="closeDialog"
        />

        <form v-else class="flex flex-col gap-5" @submit.prevent="createProject">
          <UiStateBlock v-if="errorDetail" kind="error" :title="errorTitle" />
          <div class="flex flex-col gap-2">
            <label class="text-sm font-semibold" for="project-name">{{ copy.nameLabel }}</label>
            <input
              id="project-name"
              v-model="displayName"
              class="h-12 rounded-control border border-field bg-surface px-3.5 text-base text-ink placeholder:text-ink-3"
              maxlength="120"
              autocomplete="off"
              :placeholder="copy.namePlaceholder"
              required
            />
          </div>
          <div class="flex flex-wrap justify-end gap-2.5">
            <UiButton variant="secondary" data-testid="create-project-cancel" @click="closeDialog">
              {{ t("projects.cancel") }}
            </UiButton>
            <UiButton type="submit" :disabled="loading" data-testid="create-project-submit">
              {{ copy.create }}
            </UiButton>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
