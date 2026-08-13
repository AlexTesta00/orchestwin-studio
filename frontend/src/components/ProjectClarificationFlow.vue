<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import {
  BRIEF_FIELDS,
  type BriefAssumptionResponse,
  type BriefField,
  type ClarificationAnswerInput,
  type ClarificationQuestionResponse,
  type ProjectBriefGateDecisionAction,
  type ProjectWorkflowApi,
} from "@/api/workflow-contracts";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedRequest, useClarificationStore } from "@/stores/clarification";

interface AnswerDraft {
  text: string;
  items: string;
  unknown: boolean;
}

const props = defineProps<{
  projectId: string;
  api?: ProjectWorkflowApi;
  authorize?: AuthorizedRequest;
}>();

const auth = useAuthStore();
const store = useClarificationStore();

const { t, locale } = useI18n({
  useScope: "local",
  messages: {
    en: {
      flow: {
        title: "Clarification and Project Brief approval",
        intro:
          "Resolve missing information, keep assumptions explicit, and approve the exact Project Brief version.",
        loading: "Updating project workflow…",
        refresh: "Refresh workflow",
        startRound: "Start clarification round",
        noOpenRound: "There is no open clarification round.",
        roundTitle: "Clarification round {number}",
        markUnknown: "This information is currently unknown",
        textPlaceholder: "Enter a focused answer",
        listPlaceholder: "Enter one item per line",
        submitAnswers: "Save clarification answers",
        answerRequired: "Provide at least one answer or mark one field as unknown.",
        nextStep: "Next step: {step}",
        historyTitle: "Clarification history",
        noHistory: "No clarification round has been created.",
        assumptionsTitle: "Explicit assumptions",
        assumptionsIntro:
          "Assumptions remain separate until they are explicitly accepted or rejected.",
        assumptionField: "Project Brief field",
        assumptionStatement: "Assumption",
        assumptionPlaceholder: "Describe the assumption and its intended meaning.",
        createAssumption: "Create assumption",
        noAssumptions: "No assumptions have been proposed.",
        decisionReason: "Decision rationale",
        accept: "Accept assumption",
        reject: "Reject assumption",
        rejectionReasonRequired: "A rejection rationale is required.",
        gateTitle: "Gate 1 — Project Brief",
        noGate: "The Project Brief has not been submitted for approval.",
        submitGate: "Submit current brief for approval",
        gateReason: "Decision rationale",
        approve: "Approve",
        requestRevision: "Request revision",
        pause: "Pause",
        resume: "Resume",
        cancel: "Cancel",
        gateReasonRequired: "Reject and request-revision actions require a rationale.",
        missingForApproval: "Approval is blocked by these missing fields:",
        eventHistory: "Gate audit history",
        noEvents: "No Gate 1 event has been recorded.",
        versionLabel: "Version {version}",
        statusLabel: "Status: {status}",
        error: "Workflow error: {detail}",
        fields: {
          name: "Name",
          description: "Description",
          problem: "Problem",
          goals: "Goals",
          target_users: "Target users",
          domain: "Domain",
          technical_constraints: "Technical constraints",
          temporal_constraints: "Temporal constraints",
          budget: "Budget",
          functional_requirements: "Functional requirements",
          non_functional_requirements: "Non-functional requirements",
          risks: "Risks",
          stakeholders: "Stakeholders",
          available_artifacts: "Available artifacts",
          definition_of_done: "Definition of Done",
        },
        statuses: {
          OPEN: "Open",
          ANSWERED: "Answered",
          PROPOSED: "Proposed",
          ACCEPTED: "Accepted",
          REJECTED: "Rejected",
          DRAFT: "Draft",
          PENDING_APPROVAL: "Pending approval",
          APPROVED: "Approved",
          REVISION_REQUESTED: "Revision requested",
          PAUSED: "Paused",
          CANCELLED: "Cancelled",
          STALE: "Stale",
          PAUSED_NEEDS_HUMAN: "Paused — human intervention required",
          STARTED: "Round started",
          OPEN_ROUND_EXISTS: "An open round already exists",
          BRIEF_NOT_FOUND: "Project Brief not found",
          BRIEF_COMPLETE: "The Project Brief has no missing fields",
          LIMIT_REACHED: "Clarification limit reached",
          APPLIED: "Applied",
          ROUND_NOT_FOUND: "Round not found",
          ROUND_NOT_OPEN: "Round is not open",
          ROUND_STALE: "Round is stale",
          NO_ANSWERS: "No answers supplied",
          INVALID_ANSWERS: "Invalid answers",
          VERSION_UNCHANGED: "No new version was required",
          CREATED: "Created",
          FIELD_ALREADY_PROVIDED: "The field already contains owner-provided information",
          ASSUMPTION_NOT_FOUND: "Assumption not found",
          ASSUMPTION_NOT_PROPOSED: "The assumption has already been decided",
          ASSUMPTION_STALE: "The assumption refers to an older brief",
          SUBMITTED: "Submitted",
          ALREADY_PENDING: "Already pending",
          ALREADY_APPROVED: "Already approved",
          BRIEF_INCOMPLETE: "Brief incomplete",
          NEW_BRIEF_REQUIRED: "A new brief version is required",
          GATE_BLOCKED: "Gate blocked",
          ITERATION_LIMIT_REACHED: "Gate iteration limit reached",
          TRANSITION_REJECTED: "Transition rejected",
          ARTIFACT_STALE: "Artifact is stale",
        },
        nextSteps: {
          CLARIFICATION_REQUIRED: "Another clarification round is required",
          BRIEF_READY_FOR_APPROVAL: "The Project Brief is ready for Gate 1",
          PAUSED_NEEDS_HUMAN: "Automatic clarification stopped; human intervention is required",
        },
        errors: {
          unexpected_error: "An unexpected error occurred.",
          unexpected_api_error: "The API returned an unexpected response.",
          clarification_round_not_found: "No open clarification round was found.",
          clarification_service_unavailable: "The clarification service is unavailable.",
          brief_gate_service_unavailable: "The Project Brief gate service is unavailable.",
        },
      },
      clarification: {
        questions: {
          name: {
            prompt: "What is the project name?",
            hint: "Provide a short and recognizable project name.",
          },
          description: {
            prompt: "How would you describe the requested system?",
            hint: "Summarize its purpose and main behavior.",
          },
          problem: {
            prompt: "Which problem should the project solve?",
            hint: "Describe the current difficulty or unmet need.",
          },
          goals: {
            prompt: "What outcomes should the project achieve?",
            hint: "Enter one measurable or observable goal per line.",
          },
          target_users: {
            prompt: "Who are the intended users?",
            hint: "Enter one user group or role per line.",
          },
          domain: {
            prompt: "Which domain does the project belong to?",
            hint: "Describe the business, educational, technical, or social context.",
          },
          technical_constraints: {
            prompt: "Which technical constraints must be respected?",
            hint: "Enter one stack, platform, integration, or deployment constraint per line.",
          },
          temporal_constraints: {
            prompt: "Are there deadlines or timing constraints?",
            hint: "Describe important dates, milestones, or operating-time requirements.",
          },
          budget: {
            prompt: "What budget constraints apply?",
            hint: "Provide the available budget or mark it as unknown.",
          },
          functional_requirements: {
            prompt: "Which functions must the system provide?",
            hint: "Enter one required capability per line.",
          },
          non_functional_requirements: {
            prompt: "Which quality requirements must be satisfied?",
            hint: "Enter one performance, security, accessibility, or reliability requirement per line.",
          },
          risks: {
            prompt: "Which risks are already known?",
            hint: "Enter one project, technical, legal, or usability risk per line.",
          },
          stakeholders: {
            prompt: "Who are the relevant stakeholders?",
            hint: "Enter one stakeholder or stakeholder group per line.",
          },
          available_artifacts: {
            prompt: "Which existing artifacts are available?",
            hint: "Enter one document, design, repository, dataset, or prototype per line.",
          },
          definition_of_done: {
            prompt: "How will the owner determine that the project is complete?",
            hint: "Enter one completion criterion per line.",
          },
        },
      },
    },
    it: {
      flow: {
        title: "Chiarificazione e approvazione del Project Brief",
        intro:
          "Risolvi le informazioni mancanti, mantieni esplicite le assunzioni e approva la versione esatta del Project Brief.",
        loading: "Aggiornamento del workflow…",
        refresh: "Aggiorna workflow",
        startRound: "Avvia round di chiarificazione",
        noOpenRound: "Non è presente un round di chiarificazione aperto.",
        roundTitle: "Round di chiarificazione {number}",
        markUnknown: "Questa informazione è attualmente sconosciuta",
        textPlaceholder: "Inserisci una risposta mirata",
        listPlaceholder: "Inserisci un elemento per riga",
        submitAnswers: "Salva risposte di chiarificazione",
        answerRequired: "Fornisci almeno una risposta oppure marca un campo come sconosciuto.",
        nextStep: "Passo successivo: {step}",
        historyTitle: "Cronologia chiarificazioni",
        noHistory: "Non è stato ancora creato alcun round di chiarificazione.",
        assumptionsTitle: "Assunzioni esplicite",
        assumptionsIntro:
          "Le assunzioni restano separate finché non vengono accettate o rifiutate esplicitamente.",
        assumptionField: "Campo del Project Brief",
        assumptionStatement: "Assunzione",
        assumptionPlaceholder: "Descrivi l'assunzione e il significato previsto.",
        createAssumption: "Crea assunzione",
        noAssumptions: "Non sono state proposte assunzioni.",
        decisionReason: "Motivazione della decisione",
        accept: "Accetta assunzione",
        reject: "Rifiuta assunzione",
        rejectionReasonRequired: "Per rifiutare è richiesta una motivazione.",
        gateTitle: "Gate 1 — Project Brief",
        noGate: "Il Project Brief non è ancora stato sottoposto ad approvazione.",
        submitGate: "Sottoponi il brief corrente ad approvazione",
        gateReason: "Motivazione della decisione",
        approve: "Approva",
        requestRevision: "Richiedi revisione",
        pause: "Metti in pausa",
        resume: "Riprendi",
        cancel: "Annulla",
        gateReasonRequired: "Rifiuto e richiesta di revisione richiedono una motivazione.",
        missingForApproval: "L'approvazione è bloccata dai seguenti campi mancanti:",
        eventHistory: "Cronologia audit del gate",
        noEvents: "Non è stato ancora registrato alcun evento Gate 1.",
        versionLabel: "Versione {version}",
        statusLabel: "Stato: {status}",
        error: "Errore del workflow: {detail}",
        fields: {
          name: "Nome",
          description: "Descrizione",
          problem: "Problema",
          goals: "Obiettivi",
          target_users: "Utenti target",
          domain: "Dominio",
          technical_constraints: "Vincoli tecnici",
          temporal_constraints: "Vincoli temporali",
          budget: "Budget",
          functional_requirements: "Requisiti funzionali",
          non_functional_requirements: "Requisiti non funzionali",
          risks: "Rischi",
          stakeholders: "Stakeholder",
          available_artifacts: "Artefatti disponibili",
          definition_of_done: "Definition of Done",
        },
        statuses: {
          OPEN: "Aperto",
          ANSWERED: "Risposto",
          PROPOSED: "Proposta",
          ACCEPTED: "Accettata",
          REJECTED: "Rifiutata",
          DRAFT: "Bozza",
          PENDING_APPROVAL: "In attesa di approvazione",
          APPROVED: "Approvato",
          REVISION_REQUESTED: "Revisione richiesta",
          PAUSED: "In pausa",
          CANCELLED: "Annullato",
          STALE: "Obsoleto",
          PAUSED_NEEDS_HUMAN: "In pausa — intervento umano richiesto",
          STARTED: "Round avviato",
          OPEN_ROUND_EXISTS: "Esiste già un round aperto",
          BRIEF_NOT_FOUND: "Project Brief non trovato",
          BRIEF_COMPLETE: "Il Project Brief non contiene campi mancanti",
          LIMIT_REACHED: "Limite di chiarificazione raggiunto",
          APPLIED: "Applicato",
          ROUND_NOT_FOUND: "Round non trovato",
          ROUND_NOT_OPEN: "Il round non è aperto",
          ROUND_STALE: "Il round è obsoleto",
          NO_ANSWERS: "Nessuna risposta fornita",
          INVALID_ANSWERS: "Risposte non valide",
          VERSION_UNCHANGED: "Non è stata necessaria una nuova versione",
          CREATED: "Creata",
          FIELD_ALREADY_PROVIDED: "Il campo contiene già informazioni fornite dall'owner",
          ASSUMPTION_NOT_FOUND: "Assunzione non trovata",
          ASSUMPTION_NOT_PROPOSED: "L'assunzione è già stata valutata",
          ASSUMPTION_STALE: "L'assunzione appartiene a una versione precedente",
          SUBMITTED: "Sottoposto",
          ALREADY_PENDING: "Già in attesa",
          ALREADY_APPROVED: "Già approvato",
          BRIEF_INCOMPLETE: "Brief incompleto",
          NEW_BRIEF_REQUIRED: "È richiesta una nuova versione del brief",
          GATE_BLOCKED: "Gate bloccato",
          ITERATION_LIMIT_REACHED: "Limite di iterazioni del gate raggiunto",
          TRANSITION_REJECTED: "Transizione rifiutata",
          ARTIFACT_STALE: "Artefatto obsoleto",
        },
        nextSteps: {
          CLARIFICATION_REQUIRED: "È necessario un altro round di chiarificazione",
          BRIEF_READY_FOR_APPROVAL: "Il Project Brief è pronto per Gate 1",
          PAUSED_NEEDS_HUMAN:
            "La chiarificazione automatica è terminata; è richiesto un intervento umano",
        },
        errors: {
          unexpected_error: "Si è verificato un errore inatteso.",
          unexpected_api_error: "L'API ha restituito una risposta inattesa.",
          clarification_round_not_found: "Non è stato trovato un round di chiarificazione aperto.",
          clarification_service_unavailable: "Il servizio di chiarificazione non è disponibile.",
          brief_gate_service_unavailable: "Il servizio Gate 1 non è disponibile.",
        },
      },
      clarification: {
        questions: {
          name: {
            prompt: "Qual è il nome del progetto?",
            hint: "Fornisci un nome breve e riconoscibile.",
          },
          description: {
            prompt: "Come descriveresti il sistema richiesto?",
            hint: "Riassumi il suo scopo e il comportamento principale.",
          },
          problem: {
            prompt: "Quale problema deve risolvere il progetto?",
            hint: "Descrivi la difficoltà attuale o il bisogno non soddisfatto.",
          },
          goals: {
            prompt: "Quali risultati deve raggiungere il progetto?",
            hint: "Inserisci un obiettivo misurabile o osservabile per riga.",
          },
          target_users: {
            prompt: "Chi sono gli utenti previsti?",
            hint: "Inserisci un gruppo o ruolo utente per riga.",
          },
          domain: {
            prompt: "A quale dominio appartiene il progetto?",
            hint: "Descrivi il contesto aziendale, educativo, tecnico o sociale.",
          },
          technical_constraints: {
            prompt: "Quali vincoli tecnici devono essere rispettati?",
            hint: "Inserisci uno stack, piattaforma, integrazione o vincolo di distribuzione per riga.",
          },
          temporal_constraints: {
            prompt: "Sono presenti scadenze o vincoli temporali?",
            hint: "Descrivi date, milestone o requisiti temporali rilevanti.",
          },
          budget: {
            prompt: "Quali vincoli di budget si applicano?",
            hint: "Indica il budget disponibile oppure marcalo come sconosciuto.",
          },
          functional_requirements: {
            prompt: "Quali funzioni deve fornire il sistema?",
            hint: "Inserisci una funzionalità richiesta per riga.",
          },
          non_functional_requirements: {
            prompt: "Quali requisiti di qualità devono essere soddisfatti?",
            hint: "Inserisci un requisito di prestazioni, sicurezza, accessibilità o affidabilità per riga.",
          },
          risks: {
            prompt: "Quali rischi sono già noti?",
            hint: "Inserisci un rischio progettuale, tecnico, legale o di usabilità per riga.",
          },
          stakeholders: {
            prompt: "Chi sono gli stakeholder rilevanti?",
            hint: "Inserisci uno stakeholder o gruppo di stakeholder per riga.",
          },
          available_artifacts: {
            prompt: "Quali artefatti esistenti sono disponibili?",
            hint: "Inserisci un documento, design, repository, dataset o prototipo per riga.",
          },
          definition_of_done: {
            prompt: "Come verrà stabilito che il progetto è completo?",
            hint: "Inserisci un criterio di completamento per riga.",
          },
        },
      },
    },
  },
});

const resolvedApi = computed(() => props.api ?? apiClient);

const answerDrafts = ref<Record<string, AnswerDraft>>({});
const assumptionField = ref<BriefField>("description");
const assumptionStatement = ref("");
const assumptionReasons = ref<Record<string, string>>({});
const gateReason = ref("");
const localError = ref<string | null>(null);

function executeAuthorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }

  return auth.withAccessToken(apiClient, operation);
}

async function load(): Promise<void> {
  localError.value = null;

  await store.load(props.projectId, resolvedApi.value, executeAuthorized);
}

watch(
  () => store.currentRound,
  (round) => {
    const drafts: Record<string, AnswerDraft> = {};

    for (const question of round?.questions ?? []) {
      drafts[question.question_id] = {
        text: "",
        items: "",
        unknown: false,
      };
    }

    answerDrafts.value = drafts;
  },
  {
    immediate: true,
  },
);

watch(
  () => props.projectId,
  async () => {
    await load();
  },
);

onMounted(load);

function draftFor(questionId: string): AnswerDraft {
  const existing = answerDrafts.value[questionId];

  if (existing !== undefined) {
    return existing;
  }

  const created: AnswerDraft = {
    text: "",
    items: "",
    unknown: false,
  };

  answerDrafts.value[questionId] = created;

  return created;
}

function translatedOrFallback(key: string, fallback: string): string {
  const translated = t(key);

  return translated === key ? fallback : translated;
}

function questionPrompt(question: ClarificationQuestionResponse): string {
  return translatedOrFallback(question.prompt_key, t(`flow.fields.${question.field}`));
}

function questionHint(question: ClarificationQuestionResponse): string {
  return translatedOrFallback(question.hint_key, t(`flow.fields.${question.field}`));
}

function statusText(statusValue: string): string {
  return translatedOrFallback(`flow.statuses.${statusValue}`, statusValue);
}

function nextStepText(nextStep: string): string {
  return translatedOrFallback(`flow.nextSteps.${nextStep}`, nextStep);
}

function errorText(detail: string): string {
  return translatedOrFallback(`flow.errors.${detail}`, detail);
}

function fieldText(field: BriefField): string {
  return t(`flow.fields.${field}`);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function startRound(): Promise<void> {
  localError.value = null;

  await store.startRound(props.projectId, resolvedApi.value, executeAuthorized);
}

function answerPayload(): readonly ClarificationAnswerInput[] {
  const round = store.currentRound;

  if (round === null) {
    return [];
  }

  const answers: ClarificationAnswerInput[] = [];

  for (const question of round.questions) {
    const draft = draftFor(question.question_id);

    if (draft.unknown) {
      answers.push({
        question_id: question.question_id,
        kind: "unknown",
      });

      continue;
    }

    if (question.answer_type === "text") {
      const value = draft.text.trim();

      if (value) {
        answers.push({
          question_id: question.question_id,
          kind: "text",
          text_value: value,
        });
      }

      continue;
    }

    const items = draft.items
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);

    if (items.length > 0) {
      answers.push({
        question_id: question.question_id,
        kind: "item_list",
        item_values: items,
      });
    }
  }

  return answers;
}

async function submitAnswers(): Promise<void> {
  localError.value = null;

  const answers = answerPayload();

  if (answers.length === 0) {
    localError.value = t("flow.answerRequired");

    return;
  }

  await store.answerRound(props.projectId, answers, resolvedApi.value, executeAuthorized);
}

async function createAssumption(): Promise<void> {
  localError.value = null;

  const statement = assumptionStatement.value.trim();

  if (!statement) {
    localError.value = t("flow.assumptionPlaceholder");

    return;
  }

  const result = await store.createAssumption(
    props.projectId,
    {
      field: assumptionField.value,
      statement,
    },
    resolvedApi.value,
    executeAuthorized,
  );

  if (result !== null) {
    assumptionStatement.value = "";
  }
}

function assumptionReason(assumption: BriefAssumptionResponse): string {
  return (assumptionReasons.value[assumption.id] ?? "").trim();
}

async function acceptAssumption(assumption: BriefAssumptionResponse): Promise<void> {
  localError.value = null;

  await store.acceptAssumption(
    props.projectId,
    assumption.id,
    assumptionReason(assumption) || null,
    resolvedApi.value,
    executeAuthorized,
  );
}

async function rejectAssumption(assumption: BriefAssumptionResponse): Promise<void> {
  localError.value = null;

  const reason = assumptionReason(assumption);

  if (!reason) {
    localError.value = t("flow.rejectionReasonRequired");

    return;
  }

  await store.rejectAssumption(
    props.projectId,
    assumption.id,
    reason,
    resolvedApi.value,
    executeAuthorized,
  );
}

async function submitGate(): Promise<void> {
  localError.value = null;

  await store.submitGate(props.projectId, resolvedApi.value, executeAuthorized);
}

async function decideGate(action: ProjectBriefGateDecisionAction): Promise<void> {
  localError.value = null;

  const reason = gateReason.value.trim();

  if (["REJECT", "REQUEST_REVISION"].includes(action) && !reason) {
    localError.value = t("flow.gateReasonRequired");

    return;
  }

  const result = await store.decideGate(
    props.projectId,
    action,
    reason || null,
    resolvedApi.value,
    executeAuthorized,
  );

  if (result !== null) {
    gateReason.value = "";
  }
}
</script>

<template>
  <section class="grid gap-8" aria-labelledby="clarification-flow-title">
    <header class="grid gap-2">
      <h2 id="clarification-flow-title" class="text-2xl font-black text-slate-950">
        {{ t("flow.title") }}
      </h2>

      <p class="m-0 max-w-3xl text-slate-600">
        {{ t("flow.intro") }}
      </p>
    </header>

    <div class="min-h-6" aria-live="polite" aria-atomic="true">
      <p v-if="store.busy" class="m-0 text-sm font-semibold text-slate-700">
        {{ t("flow.loading") }}
      </p>

      <p
        v-else-if="localError !== null || store.errorDetail !== null"
        class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-800"
        role="alert"
      >
        {{
          t("flow.error", {
            detail: localError ?? errorText(store.errorDetail ?? "unexpected_error"),
          })
        }}
      </p>

      <p
        v-else-if="store.lastRoundAnswer?.next_step"
        class="m-0 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-800"
      >
        {{
          t("flow.nextStep", {
            step: nextStepText(store.lastRoundAnswer.next_step),
          })
        }}
      </p>
    </div>

    <div class="flex flex-wrap gap-3">
      <button
        type="button"
        class="min-h-11 rounded-xl border border-slate-300 bg-white px-4 py-2 font-bold text-slate-900 hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none disabled:opacity-60"
        :disabled="store.busy"
        @click="load"
      >
        {{ t("flow.refresh") }}
      </button>

      <button
        v-if="store.currentRound === null"
        type="button"
        class="min-h-11 rounded-xl bg-slate-950 px-4 py-2 font-bold text-white hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
        :disabled="store.busy"
        @click="startRound"
      >
        {{ t("flow.startRound") }}
      </button>
    </div>

    <section
      class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="current-round-title"
    >
      <template v-if="store.currentRound !== null">
        <header class="grid gap-1">
          <h3 id="current-round-title" class="text-xl font-black text-slate-950">
            {{
              t("flow.roundTitle", {
                number: store.currentRound.round_number,
              })
            }}
          </h3>

          <p class="m-0 text-sm text-slate-600">
            {{
              t("flow.versionLabel", {
                version: store.currentRound.source_brief_version_number,
              })
            }}
            ·
            {{
              t("flow.statusLabel", {
                status: statusText(store.currentRound.status),
              })
            }}
          </p>
        </header>

        <form
          class="grid gap-5"
          data-testid="clarification-answer-form"
          @submit.prevent="submitAnswers"
        >
          <fieldset
            v-for="question in store.currentRound.questions"
            :key="question.question_id"
            class="grid gap-3 rounded-xl border border-slate-200 p-4"
          >
            <legend class="px-1 font-black text-slate-900">
              {{ questionPrompt(question) }}
            </legend>

            <p class="m-0 text-sm text-slate-600">
              {{ questionHint(question) }}
            </p>

            <textarea
              v-if="question.answer_type === 'text'"
              v-model="draftFor(question.question_id).text"
              :data-testid="`question-${question.field}-text`"
              class="min-h-28 rounded-xl border border-slate-300 px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none disabled:bg-slate-100"
              :placeholder="t('flow.textPlaceholder')"
              :disabled="draftFor(question.question_id).unknown"
            ></textarea>

            <textarea
              v-else
              v-model="draftFor(question.question_id).items"
              :data-testid="`question-${question.field}-items`"
              class="min-h-32 rounded-xl border border-slate-300 px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none disabled:bg-slate-100"
              :placeholder="t('flow.listPlaceholder')"
              :disabled="draftFor(question.question_id).unknown"
            ></textarea>

            <label
              v-if="question.unknown_allowed"
              class="flex min-h-11 items-center gap-3 rounded-lg p-2 text-sm font-semibold text-slate-700"
            >
              <input
                v-model="draftFor(question.question_id).unknown"
                type="checkbox"
                :data-testid="`question-${question.field}-unknown`"
              />

              {{ t("flow.markUnknown") }}
            </label>
          </fieldset>

          <button
            type="submit"
            class="min-h-12 rounded-xl bg-slate-950 px-5 py-3 font-bold text-white hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
            :disabled="store.busy"
          >
            {{ t("flow.submitAnswers") }}
          </button>
        </form>
      </template>

      <p v-else id="current-round-title" class="m-0 text-slate-600">
        {{ t("flow.noOpenRound") }}
      </p>
    </section>

    <section
      class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="clarification-history-title"
    >
      <h3 id="clarification-history-title" class="text-xl font-black text-slate-950">
        {{ t("flow.historyTitle") }}
      </h3>

      <ol v-if="store.roundHistory.length > 0" class="grid gap-3">
        <li
          v-for="round in store.roundHistory"
          :key="round.id"
          class="rounded-xl border border-slate-200 p-4"
        >
          <p class="m-0 font-bold text-slate-900">
            {{
              t("flow.roundTitle", {
                number: round.round_number,
              })
            }}
          </p>

          <p class="m-0 mt-1 text-sm text-slate-600">
            {{ statusText(round.status) }}
            ·
            {{ formatDate(round.created_at) }}
          </p>

          <p
            v-if="round.resulting_brief_version_number !== null"
            class="m-0 mt-1 text-sm text-slate-600"
          >
            {{
              t("flow.versionLabel", {
                version: round.resulting_brief_version_number,
              })
            }}
          </p>
        </li>
      </ol>

      <p v-else class="m-0 text-slate-600">
        {{ t("flow.noHistory") }}
      </p>
    </section>

    <section
      class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="assumptions-title"
    >
      <header class="grid gap-1">
        <h3 id="assumptions-title" class="text-xl font-black text-slate-950">
          {{ t("flow.assumptionsTitle") }}
        </h3>

        <p class="m-0 text-sm text-slate-600">
          {{ t("flow.assumptionsIntro") }}
        </p>
      </header>

      <form class="grid gap-4 md:grid-cols-2" @submit.prevent="createAssumption">
        <label class="grid gap-2 font-bold text-slate-800">
          {{ t("flow.assumptionField") }}

          <select
            v-model="assumptionField"
            class="min-h-11 rounded-xl border border-slate-300 bg-white px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none"
          >
            <option v-for="field in BRIEF_FIELDS" :key="field" :value="field">
              {{ fieldText(field) }}
            </option>
          </select>
        </label>

        <label class="grid gap-2 font-bold text-slate-800">
          {{ t("flow.assumptionStatement") }}

          <textarea
            v-model="assumptionStatement"
            class="min-h-28 rounded-xl border border-slate-300 px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none"
            :placeholder="t('flow.assumptionPlaceholder')"
          ></textarea>
        </label>

        <button
          type="submit"
          class="min-h-11 rounded-xl bg-slate-950 px-4 py-2 font-bold text-white hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60 md:col-span-2"
          :disabled="store.busy"
        >
          {{ t("flow.createAssumption") }}
        </button>
      </form>

      <ul v-if="store.assumptions.length > 0" class="grid gap-4">
        <li
          v-for="assumption in store.assumptions"
          :key="assumption.id"
          class="grid gap-3 rounded-xl border border-slate-200 p-4"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="grid gap-1">
              <p class="m-0 font-black text-slate-900">
                {{ fieldText(assumption.field) }}
              </p>

              <p class="m-0 text-slate-700">
                {{ assumption.statement }}
              </p>
            </div>

            <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-700">
              {{ statusText(assumption.status) }}
            </span>
          </div>

          <template v-if="assumption.status === 'PROPOSED'">
            <label class="grid gap-2 text-sm font-bold text-slate-800">
              {{ t("flow.decisionReason") }}

              <textarea
                v-model="assumptionReasons[assumption.id]"
                class="min-h-20 rounded-xl border border-slate-300 px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none"
              ></textarea>
            </label>

            <div class="flex flex-wrap gap-3">
              <button
                type="button"
                class="min-h-11 rounded-xl bg-emerald-700 px-4 py-2 font-bold text-white hover:bg-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
                :disabled="store.busy"
                @click="acceptAssumption(assumption)"
              >
                {{ t("flow.accept") }}
              </button>

              <button
                type="button"
                class="min-h-11 rounded-xl border border-red-300 bg-white px-4 py-2 font-bold text-red-800 hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
                :disabled="store.busy"
                @click="rejectAssumption(assumption)"
              >
                {{ t("flow.reject") }}
              </button>
            </div>
          </template>

          <p v-else-if="assumption.decision_reason" class="m-0 text-sm text-slate-600">
            {{ assumption.decision_reason }}
          </p>
        </li>
      </ul>

      <p v-else class="m-0 text-slate-600">
        {{ t("flow.noAssumptions") }}
      </p>
    </section>

    <section
      class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="brief-gate-title"
    >
      <header class="grid gap-1">
        <h3 id="brief-gate-title" class="text-xl font-black text-slate-950">
          {{ t("flow.gateTitle") }}
        </h3>

        <template v-if="store.gate !== null">
          <p class="m-0 text-sm text-slate-600">
            {{
              t("flow.statusLabel", {
                status: statusText(store.gate.status),
              })
            }}
          </p>

          <p class="m-0 text-sm text-slate-600">
            {{
              t("flow.versionLabel", {
                version: store.gate.artifact.version,
              })
            }}
            ·
            <code>
              {{ store.gate.artifact.content_hash.slice(0, 12) }}
            </code>
          </p>
        </template>

        <p v-else class="m-0 text-sm text-slate-600">
          {{ t("flow.noGate") }}
        </p>
      </header>

      <div
        v-if="store.lastGateSubmission?.missing_fields.length"
        class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900"
      >
        <p class="m-0 font-bold">
          {{ t("flow.missingForApproval") }}
        </p>

        <ul class="mt-2 list-disc pl-5">
          <li v-for="field in store.lastGateSubmission.missing_fields" :key="field">
            {{ fieldText(field) }}
          </li>
        </ul>
      </div>

      <button
        type="button"
        class="min-h-11 rounded-xl bg-slate-950 px-4 py-2 font-bold text-white hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
        :disabled="store.busy"
        @click="submitGate"
      >
        {{ t("flow.submitGate") }}
      </button>

      <template v-if="store.gate !== null">
        <label class="grid gap-2 font-bold text-slate-800">
          {{ t("flow.gateReason") }}

          <textarea
            v-model="gateReason"
            class="min-h-24 rounded-xl border border-slate-300 px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none"
          ></textarea>
        </label>

        <div v-if="store.gate.status === 'PENDING_APPROVAL'" class="flex flex-wrap gap-3">
          <button
            type="button"
            class="min-h-11 rounded-xl bg-emerald-700 px-4 py-2 font-bold text-white hover:bg-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('APPROVE')"
          >
            {{ t("flow.approve") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-red-300 px-4 py-2 font-bold text-red-800 hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('REJECT')"
          >
            {{ t("flow.reject") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-amber-300 px-4 py-2 font-bold text-amber-900 hover:bg-amber-50 focus-visible:ring-2 focus-visible:ring-amber-700 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('REQUEST_REVISION')"
          >
            {{ t("flow.requestRevision") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-slate-300 px-4 py-2 font-bold text-slate-800 hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:outline-none disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('PAUSE')"
          >
            {{ t("flow.pause") }}
          </button>
        </div>

        <div v-else-if="store.gate.status === 'PAUSED'" class="flex flex-wrap gap-3">
          <button
            type="button"
            class="min-h-11 rounded-xl bg-slate-950 px-4 py-2 font-bold text-white hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('RESUME')"
          >
            {{ t("flow.resume") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-red-300 px-4 py-2 font-bold text-red-800 hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('CANCEL')"
          >
            {{ t("flow.cancel") }}
          </button>
        </div>

        <button
          v-else-if="['REVISION_REQUESTED', 'PAUSED_NEEDS_HUMAN'].includes(store.gate.status)"
          type="button"
          class="min-h-11 rounded-xl border border-red-300 px-4 py-2 font-bold text-red-800 hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
          :disabled="store.busy"
          @click="decideGate('CANCEL')"
        >
          {{ t("flow.cancel") }}
        </button>
      </template>

      <div class="grid gap-3">
        <h4 class="text-lg font-black text-slate-900">
          {{ t("flow.eventHistory") }}
        </h4>

        <ol v-if="store.gateEvents.length > 0" class="grid gap-3">
          <li
            v-for="event in store.gateEvents"
            :key="event.id"
            class="rounded-xl border border-slate-200 p-4"
          >
            <p class="m-0 font-bold text-slate-900">
              {{ statusText(event.kind) }}
            </p>

            <p class="m-0 mt-1 text-sm text-slate-600">
              {{ statusText(event.previous_status) }}
              →
              {{ statusText(event.resulting_status) }}
              ·
              {{ formatDate(event.occurred_at) }}
            </p>

            <p v-if="event.reason" class="m-0 mt-2 text-sm text-slate-700">
              {{ event.reason }}
            </p>
          </li>
        </ol>

        <p v-else class="m-0 text-slate-600">
          {{ t("flow.noEvents") }}
        </p>
      </div>
    </section>
  </section>
</template>
