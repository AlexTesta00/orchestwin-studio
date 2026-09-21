<script setup lang="ts">
import { computed } from "vue";
import type { ExecutionJourney } from "@/api/executionLaunch";
import type {
  WebBrowserEvidencePayload,
  WebExecutionAttemptPayload,
  WebExecutionPhase,
  WebExecutionReportPayload,
  WebFailureSignaturePayload,
  WebNormalizedFindingPayload,
  WebPhaseResultPayload,
} from "@/types/webExecution";
import { journeySentence } from "./journeyText";

type Locale = "it" | "en";

const props = withDefaults(
  defineProps<{
    locale?: Locale;
    execution: WebExecutionAttemptPayload | null;
    report: WebExecutionReportPayload | null;
    browserEvidence: WebBrowserEvidencePayload | null;
    journey: ExecutionJourney | null;
  }>(),
  { locale: "en" },
);
defineSlots<{ repair(props: { signature: WebFailureSignaturePayload }): unknown }>();

const messages = {
  it: {
    passedTitle: "Esecuzione superata",
    passedBody:
      "Tutte le fasi sono passate, compreso l’audit di accessibilità. Ora puoi approvare il risultato finale.",
    failedChip: "Controllo non superato",
    failedTitle: "L’esecuzione si è fermata",
    phases: "Fasi dell’esecuzione",
    journey: "Percorso nel browser",
    journeyNote: "Quello che il browser ha provato davvero, frase per frase.",
    journeyDone: "Percorso completato",
    journeyStopped: "Un passaggio del percorso non è andato come previsto",
    happened: "Cosa è successo",
    where: "Dove",
    change: "Cosa cambia la riparazione",
    repairHint: "Prepari la riparazione ora e poi decidi se applicarla.",
    rule: "regola",
    page: "l’intera pagina",
    entry: "la pagina iniziale",
    element: "elemento",
    unknown: "non indicato",
    incomplete: "Esecuzione incompleta: aggiorna lo stato o riprova.",
    phase: {
      VALIDATE: "Controllo dei file",
      SETUP: "Installazione delle dipendenze",
      STATIC_CHECK: "Controlli statici",
      BUILD: "Compilazione",
      TEST: "Test automatici",
      RUN: "Avvio dell’applicazione",
      HEALTH_CHECK: "Verifica di risposta",
      BROWSER_EVIDENCE: "Browser e accessibilità",
      COLLECT_ARTIFACTS: "Raccolta delle prove",
    } as Record<WebExecutionPhase, string>,
    status: {
      PASSED: "superato",
      FAILED: "fallito",
      SKIPPED: "non previsto",
      NOT_RUN: "non eseguito",
      TIMED_OUT: "tempo scaduto",
      RESOURCE_LIMIT_EXCEEDED: "limite di risorse superato",
      CANCELLED: "annullato",
      RUNTIME_ERROR: "errore di esecuzione",
      POLICY_BLOCKED: "bloccato dalla policy",
    } as Record<string, string>,
    generic: {
      TEST: "I test automatici non passano",
      BROWSER_EVIDENCE: "Il percorso nel browser non è andato come previsto",
      default: "Una fase non è riuscita",
    } as Record<string, string>,
    genericHappened: "La fase «{phase}» si è chiusa con esito negativo.",
    genericChange: "Corregge il codice generato in base alle prove raccolte.",
    codes: {
      AXE_COLOR_CONTRAST: {
        title: "Testo poco leggibile",
        happened:
          "Il contrasto tra testo e sfondo è sotto il minimo di accessibilità (WCAG AA, 4.5:1).",
        change:
          "Cambia i colori dell’elemento fino a un contrasto sufficiente, senza toccare il resto.",
      },
      AXE_PAGE_HAS_HEADING_ONE: {
        title: "Manca il titolo principale",
        happened: "La pagina non mostra un titolo di primo livello (h1) nello stato osservato.",
        change: "Aggiunge un titolo principale sempre visibile, in ogni schermata.",
      },
      INTERACTION_FAILED: {
        title: "Un passaggio del percorso non è riuscito",
        happened: "Un’azione del percorso non ha prodotto il risultato atteso.",
        change: "Corregge il comportamento della pagina per quel passaggio.",
      },
      INTERACTION_PLAN_REQUIRED: {
        title: "Percorso nel browser mancante",
        happened: "Per questa pagina non è stato eseguito alcun percorso di verifica.",
        change: "Definisce un percorso a partire dal design approvato.",
      },
      TEXT_ASSERTION_FAILED: {
        title: "Un testo atteso non è comparso",
        happened: "Dopo un’azione, il testo verificato non corrispondeva a quello atteso.",
        change: "Corregge il comportamento della pagina per quel passaggio.",
      },
    } as Record<string, { title: string; happened: string; change: string }>,
    axeTitle: "Controllo di accessibilità non superato",
    axeChange: "Corregge l’elemento indicato secondo la regola di accessibilità.",
  },
  en: {
    passedTitle: "Execution passed",
    passedBody:
      "Every phase passed, including the accessibility audit. You can now approve the final result.",
    failedChip: "Check not passed",
    failedTitle: "The execution stopped",
    phases: "Execution phases",
    journey: "Browser journey",
    journeyNote: "What the browser really tried, sentence by sentence.",
    journeyDone: "Journey completed",
    journeyStopped: "One step of the journey did not go as expected",
    happened: "What happened",
    where: "Where",
    change: "What the repair changes",
    repairHint: "Prepare the repair now, then decide whether to apply it.",
    rule: "rule",
    page: "the whole page",
    entry: "the entry page",
    element: "element",
    unknown: "not stated",
    incomplete: "Incomplete execution: refresh the state or retry.",
    phase: {
      VALIDATE: "File checks",
      SETUP: "Dependency installation",
      STATIC_CHECK: "Static checks",
      BUILD: "Build",
      TEST: "Automated tests",
      RUN: "Application start",
      HEALTH_CHECK: "Response check",
      BROWSER_EVIDENCE: "Browser and accessibility",
      COLLECT_ARTIFACTS: "Evidence collection",
    } as Record<WebExecutionPhase, string>,
    status: {
      PASSED: "passed",
      FAILED: "failed",
      SKIPPED: "not applicable",
      NOT_RUN: "not run",
      TIMED_OUT: "timed out",
      RESOURCE_LIMIT_EXCEEDED: "resource limit exceeded",
      CANCELLED: "cancelled",
      RUNTIME_ERROR: "runtime error",
      POLICY_BLOCKED: "blocked by policy",
    } as Record<string, string>,
    generic: {
      TEST: "The automated tests do not pass",
      BROWSER_EVIDENCE: "The browser journey did not go as expected",
      default: "A phase did not succeed",
    } as Record<string, string>,
    genericHappened: "The phase “{phase}” ended with a negative outcome.",
    genericChange: "Corrects the generated code based on the collected evidence.",
    codes: {
      AXE_COLOR_CONTRAST: {
        title: "Text is hard to read",
        happened:
          "The contrast between text and background is below the accessibility minimum (WCAG AA, 4.5:1).",
        change:
          "Changes the element colours until the contrast is sufficient, leaving the rest untouched.",
      },
      AXE_PAGE_HAS_HEADING_ONE: {
        title: "The main heading is missing",
        happened: "The page shows no level-one heading (h1) in the observed state.",
        change: "Adds an always visible main heading, on every screen.",
      },
      INTERACTION_FAILED: {
        title: "A journey step did not succeed",
        happened: "One action of the journey did not produce the expected result.",
        change: "Corrects the page behaviour for that step.",
      },
      INTERACTION_PLAN_REQUIRED: {
        title: "Browser journey missing",
        happened: "No verification journey ran on this page.",
        change: "Defines a journey from the approved design.",
      },
      TEXT_ASSERTION_FAILED: {
        title: "An expected text did not appear",
        happened: "After an action, the checked text did not match the expected one.",
        change: "Corrects the page behaviour for that step.",
      },
    } as Record<string, { title: string; happened: string; change: string }>,
    axeTitle: "Accessibility check not passed",
    axeChange: "Corrects the indicated element according to the accessibility rule.",
  },
};

const copy = computed(() => messages[props.locale]);
const failedStatuses = new Set([
  "FAILED",
  "TIMED_OUT",
  "RESOURCE_LIMIT_EXCEEDED",
  "RUNTIME_ERROR",
  "POLICY_BLOCKED",
]);
const phases = computed(() =>
  (props.report?.phase_results ?? []).map((phase) => ({
    key: phase.phase,
    name: copy.value.phase[phase.phase] ?? phase.phase,
    status: copy.value.status[phase.status] ?? phase.status,
    tone:
      phase.status === "PASSED"
        ? "passed"
        : failedStatuses.has(phase.status)
          ? "failed"
          : "neutral",
  })),
);
const failedPhase = computed<WebPhaseResultPayload | null>(
  () => props.report?.phase_results.find((phase) => failedStatuses.has(phase.status)) ?? null,
);
const journeyForExecution = computed(() => {
  const journey = props.journey;
  if (journey?.status !== "DERIVED" || !journey.steps) return null;
  if (props.execution && journey.source_revision_id !== props.execution.source_revision.revision_id)
    return null;
  return journey;
});
const journeyOutcome = computed(() => {
  const route = props.browserEvidence?.routes[0];
  if (!route) return null;
  return route.status === "COLLECTED" && route.failure_code === null
    ? copy.value.journeyDone
    : copy.value.journeyStopped;
});
const signature = computed<WebFailureSignaturePayload | null>(
  () => props.report?.failure_signatures[0] ?? null,
);

function locationLabel(location: string | null): string {
  if (!location) return copy.value.unknown;
  if (location === "html") return copy.value.page;
  if (location === "/" || location === "/index.html") return copy.value.entry;
  const code = location.startsWith("#") ? location.slice(1) : location;
  const step = journeyForExecution.value?.steps?.find((item) => item.element_code === code);
  if (step) return `«${step.element_label}» (${step.screen_code})`;
  return `${copy.value.element} ${code}`;
}

function card(finding: WebNormalizedFindingPayload) {
  const known = copy.value.codes[finding.code];
  const axe = finding.source_tool === "axe-core";
  return {
    key: `${finding.code}:${finding.location ?? ""}`,
    code: finding.code,
    title: known?.title ?? (axe ? copy.value.axeTitle : finding.code),
    happened: known?.happened ?? finding.message,
    where: locationLabel(finding.location),
    change: known?.change ?? (axe ? copy.value.axeChange : copy.value.genericChange),
  };
}

const cards = computed(() => {
  const phase = failedPhase.value;
  if (!phase) return [];
  if (phase.findings.length > 0) return phase.findings.map(card);
  const name = copy.value.phase[phase.phase] ?? phase.phase;
  return [
    {
      key: phase.phase,
      code: phase.failure_code ?? phase.phase,
      title: copy.value.generic[phase.phase] ?? copy.value.generic.default,
      happened: copy.value.genericHappened.replace("{phase}", name),
      where: name,
      change: copy.value.genericChange,
    },
  ];
});
</script>

<template>
  <section v-if="report" class="grid gap-4" aria-labelledby="web-outcome-title">
    <div
      v-if="report.status === 'PASSED'"
      class="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-emerald-950"
    >
      <h3 id="web-outcome-title" class="m-0 text-xl font-black">{{ copy.passedTitle }}</h3>
      <p class="mt-1 mb-0">{{ copy.passedBody }}</p>
    </div>
    <div v-else-if="report.status === 'FAILED'" class="grid gap-3">
      <h3 id="web-outcome-title" class="m-0 text-xl font-black text-slate-950">
        {{ copy.failedTitle }}
      </h3>
      <article
        v-for="item in cards"
        :key="item.key"
        class="grid gap-2 rounded-2xl border border-red-200 bg-red-50 p-5"
      >
        <p class="m-0 flex flex-wrap items-center gap-2 text-sm">
          <span
            class="rounded-full border border-red-300 bg-white px-3 py-1 font-bold text-red-900"
          >
            {{ copy.failedChip }}
          </span>
          <code class="text-xs text-red-900">{{ copy.rule }}: {{ item.code }}</code>
        </p>
        <h4 class="m-0 text-lg font-black text-red-950">{{ item.title }}</h4>
        <dl class="m-0 grid gap-1 text-sm text-red-950">
          <div class="grid gap-0.5 sm:grid-cols-[160px_minmax(0,1fr)]">
            <dt class="font-bold">{{ copy.happened }}</dt>
            <dd class="m-0">{{ item.happened }}</dd>
          </div>
          <div class="grid gap-0.5 sm:grid-cols-[160px_minmax(0,1fr)]">
            <dt class="font-bold">{{ copy.where }}</dt>
            <dd class="m-0">{{ item.where }}</dd>
          </div>
          <div class="grid gap-0.5 sm:grid-cols-[160px_minmax(0,1fr)]">
            <dt class="font-bold">{{ copy.change }}</dt>
            <dd class="m-0">{{ item.change }}</dd>
          </div>
        </dl>
      </article>
      <div v-if="signature" class="grid gap-1">
        <slot name="repair" :signature="signature" />
        <p class="m-0 text-sm text-slate-700">{{ copy.repairHint }}</p>
      </div>
    </div>
    <p v-else class="m-0 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950">
      {{ copy.incomplete }}
    </p>
    <section class="grid gap-2">
      <h4 class="m-0 font-bold text-slate-950">{{ copy.phases }}</h4>
      <ul class="m-0 grid gap-1 pl-0" style="list-style: none">
        <li
          v-for="phase in phases"
          :key="phase.key"
          class="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
        >
          <span>{{ phase.name }}</span>
          <span
            :class="
              phase.tone === 'passed'
                ? 'font-bold text-emerald-800'
                : phase.tone === 'failed'
                  ? 'font-bold text-red-800'
                  : 'text-slate-600'
            "
          >
            {{ phase.tone === "passed" ? "✓ " : phase.tone === "failed" ? "! " : ""
            }}{{ phase.status }}
          </span>
        </li>
      </ul>
    </section>
    <section v-if="journeyForExecution" class="grid gap-2">
      <h4 class="m-0 font-bold text-slate-950">{{ copy.journey }}</h4>
      <p class="m-0 text-sm text-slate-700">{{ copy.journeyNote }}</p>
      <ol class="m-0 grid gap-1 pl-6 text-sm">
        <li v-for="(step, index) in journeyForExecution.steps" :key="index">
          {{ journeySentence(step, locale) }}
        </li>
      </ol>
      <p v-if="journeyOutcome" class="m-0 text-sm font-bold text-slate-900">{{ journeyOutcome }}</p>
    </section>
  </section>
</template>
