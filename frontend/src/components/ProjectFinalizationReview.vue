<script setup lang="ts">
import { computed } from "vue";

import type {
  EvaluationAggregationPayload,
  FinalApprovalPayload,
  FinalExportPayload,
  FinalReviewPayload,
  SyntheticFindingPayload,
} from "@/types/finalization";

type Locale = "en" | "it";
type Gate8Action = "APPROVE" | "REJECT" | "REQUEST_REVISION" | "PAUSE" | "CANCEL";

const props = withDefaults(
  defineProps<{
    findings?: SyntheticFindingPayload[];
    aggregation?: EvaluationAggregationPayload | null;
    review?: FinalReviewPayload | null;
    approval?: FinalApprovalPayload | null;
    exportBundle?: FinalExportPayload | null;
    locale?: Locale;
    busy?: boolean;
  }>(),
  {
    findings: () => [],
    aggregation: null,
    review: null,
    approval: null,
    exportBundle: null,
    locale: "en",
    busy: false,
  },
);

const emit = defineEmits<{
  submitGate8: [];
  decideGate8: [action: Gate8Action];
  createExport: [];
  downloadExport: [];
}>();

const messages = {
  en: {
    eyebrow: "Synthetic evaluation and final governance",
    title: "Final review, Gate 8, and export",
    disclaimer:
      "User Twin findings are simulated feedback and design hypotheses. They are not empirical evidence of real-user behaviour.",
    deterministic: "Deterministic findings",
    model: "Model-generated findings",
    noFindings: "No findings are available in this category.",
    originDeterministic: "Origin: deterministic test or inspection",
    originModel: "Origin: User Twin model evaluation",
    validationRequired: "Human validation required",
    confidence: "Model self-assessed confidence",
    conflicts: "Multi-twin conflicts and trade-offs",
    noConflicts: "No direct conflict has been recorded.",
    tradeoffs: "Unresolved trade-offs",
    evidenceGaps: "Evidence gaps",
    questions: "Questions for human validation",
    review: "Versioned final review",
    noReview: "No final review is available.",
    ready: "Ready for Gate 8",
    blocked: "Blocked from Gate 8",
    capability: "Capability status",
    validation: "Human-validation status",
    checks: "Definition of Done and final checks",
    issues: "Unresolved issues",
    limitations: "Accepted limitations",
    none: "None recorded.",
    blocking: "Blocks Gate 8",
    nonBlocking: "Does not block Gate 8",
    gate8: "Gate 8 — final output approval",
    gateStatus: "Gate status",
    notSubmitted: "Not submitted",
    submit: "Submit exact review to Gate 8",
    approve: "Approve final output",
    reject: "Reject final output",
    revise: "Request revision",
    pause: "Pause workflow",
    cancel: "Cancel workflow",
    ownerBoundary:
      "Owner approval is a governance decision. It does not constitute empirical validation by target users.",
    export: "Deterministic final export",
    noExport: "No final export archive has been assembled.",
    createExport: "Create export from approved Gate 8",
    download: "Download final ZIP",
    archiveHash: "Archive SHA-256",
    archiveSize: "Archive size",
    manifestHash: "Manifest SHA-256",
    manifestEntries: "Manifest entries",
    manifestOmissions: "Explicit omissions",
    required: "Required",
    optional: "Optional",
    textualAlternative: "Textual finalization summary",
  },
  it: {
    eyebrow: "Valutazione sintetica e governance finale",
    title: "Revisione finale, Gate 8 ed esportazione",
    disclaimer:
      "I finding dei User Twin sono feedback simulati e ipotesi progettuali. Non costituiscono evidenza empirica del comportamento di utenti reali.",
    deterministic: "Finding deterministici",
    model: "Finding generati dal modello",
    noFindings: "Non sono disponibili finding in questa categoria.",
    originDeterministic: "Origine: test o ispezione deterministica",
    originModel: "Origine: valutazione del modello User Twin",
    validationRequired: "Richiede validazione umana",
    confidence: "Confidenza autovalutata dal modello",
    conflicts: "Conflitti e trade-off tra User Twin",
    noConflicts: "Non è stato registrato alcun conflitto diretto.",
    tradeoffs: "Trade-off irrisolti",
    evidenceGaps: "Lacune nelle evidenze",
    questions: "Domande per la validazione umana",
    review: "Revisione finale versionata",
    noReview: "Non è disponibile alcuna revisione finale.",
    ready: "Pronta per Gate 8",
    blocked: "Bloccata prima di Gate 8",
    capability: "Stato della capacità",
    validation: "Stato della validazione umana",
    checks: "Definition of Done e controlli finali",
    issues: "Problemi irrisolti",
    limitations: "Limitazioni accettate",
    none: "Nessun elemento registrato.",
    blocking: "Blocca Gate 8",
    nonBlocking: "Non blocca Gate 8",
    gate8: "Gate 8 — approvazione dell'output finale",
    gateStatus: "Stato del gate",
    notSubmitted: "Non inviato",
    submit: "Invia la revisione esatta a Gate 8",
    approve: "Approva output finale",
    reject: "Rifiuta output finale",
    revise: "Richiedi revisione",
    pause: "Metti in pausa il workflow",
    cancel: "Annulla workflow",
    ownerBoundary:
      "L'approvazione del proprietario è una decisione di governance. Non equivale a validazione empirica da parte degli utenti target.",
    export: "Esportazione finale deterministica",
    noExport: "Non è stato assemblato alcun archivio finale.",
    createExport: "Crea export dal Gate 8 approvato",
    download: "Scarica ZIP finale",
    archiveHash: "SHA-256 archivio",
    archiveSize: "Dimensione archivio",
    manifestHash: "SHA-256 manifest",
    manifestEntries: "Elementi del manifest",
    manifestOmissions: "Omissioni esplicite",
    required: "Obbligatorio",
    optional: "Opzionale",
    textualAlternative: "Riepilogo testuale della finalizzazione",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const deterministicFindings = computed(() =>
  props.findings.filter((finding) => finding.origin === "DETERMINISTIC"),
);
const modelFindings = computed(() =>
  props.findings.filter((finding) => finding.origin !== "DETERMINISTIC"),
);
const canSubmitGate8 = computed(
  () => props.review?.ready_for_gate8 === true && props.approval === null,
);
const canDecideGate8 = computed(() => props.approval?.status === "PENDING_APPROVAL");
const canCreateExport = computed(
  () => props.approval?.status === "APPROVED" && props.exportBundle === null,
);
const canDownloadExport = computed(() => props.exportBundle !== null);

function formatBytes(value: number): string {
  return new Intl.NumberFormat(props.locale, {
    style: "unit",
    unit: "byte",
    unitDisplay: "short",
    maximumFractionDigits: 0,
  }).format(value);
}

function findingOrigin(finding: SyntheticFindingPayload): string {
  return finding.origin === "DETERMINISTIC"
    ? copy.value.originDeterministic
    : copy.value.originModel;
}
</script>

<template>
  <section class="grid gap-8" aria-labelledby="project-finalization-title">
    <header class="grid gap-3">
      <p class="m-0 text-sm font-bold tracking-wide text-violet-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="project-finalization-title" class="m-0 text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p
        class="m-0 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
        role="note"
        data-testid="synthetic-feedback-disclaimer"
      >
        {{ copy.disclaimer }}
      </p>
    </header>

    <div class="grid gap-6 lg:grid-cols-2">
      <section class="grid content-start gap-3" aria-labelledby="deterministic-findings-title">
        <h3 id="deterministic-findings-title" class="m-0 text-xl font-black">
          {{ copy.deterministic }}
        </h3>
        <p v-if="deterministicFindings.length === 0">{{ copy.noFindings }}</p>
        <ol v-else class="m-0 grid list-decimal gap-3 pl-6">
          <li
            v-for="finding in deterministicFindings"
            :key="finding.finding_id"
            class="rounded-xl border border-slate-300 bg-white p-4"
            data-finding-origin="DETERMINISTIC"
          >
            <strong>{{ finding.summary }}</strong>
            <span class="mt-1 block text-sm text-slate-700">{{ findingOrigin(finding) }}</span>
            <span class="block text-sm text-slate-700">
              {{ finding.severity }} · {{ finding.criterion }}
            </span>
          </li>
        </ol>
      </section>

      <section class="grid content-start gap-3" aria-labelledby="model-findings-title">
        <h3 id="model-findings-title" class="m-0 text-xl font-black">{{ copy.model }}</h3>
        <p v-if="modelFindings.length === 0">{{ copy.noFindings }}</p>
        <ol v-else class="m-0 grid list-decimal gap-3 pl-6">
          <li
            v-for="finding in modelFindings"
            :key="finding.finding_id"
            class="rounded-xl border border-violet-200 bg-violet-50 p-4"
            data-finding-origin="MODEL_GENERATED"
          >
            <strong>{{ finding.summary }}</strong>
            <span class="mt-1 block text-sm text-violet-950">{{ findingOrigin(finding) }}</span>
            <span class="block text-sm text-violet-950">
              {{ finding.severity }} · {{ finding.criterion }} · {{ finding.epistemic_status }}
            </span>
            <span class="block text-sm text-violet-950">
              {{ copy.confidence }}: {{ finding.confidence }}
            </span>
            <strong v-if="finding.requires_human_validation" class="mt-2 block text-sm">
              {{ copy.validationRequired }}
            </strong>
          </li>
        </ol>
      </section>
    </div>

    <section class="grid gap-4" aria-labelledby="evaluation-conflicts-title">
      <h3 id="evaluation-conflicts-title" class="m-0 text-xl font-black">
        {{ copy.conflicts }}
      </h3>
      <p v-if="!aggregation || aggregation.direct_conflicts.length === 0">
        {{ copy.noConflicts }}
      </p>
      <ul v-else class="m-0 grid list-disc gap-3 pl-6">
        <li
          v-for="conflict in aggregation.direct_conflicts"
          :key="conflict.conflict_id"
          class="rounded-xl border border-orange-300 bg-orange-50 p-4"
          data-testid="direct-conflict"
        >
          <strong>{{ conflict.summary }}</strong>
          <span class="block text-sm">{{ conflict.finding_ids.join(", ") }}</span>
        </li>
      </ul>

      <div v-if="aggregation" class="grid gap-4 md:grid-cols-3">
        <section aria-labelledby="tradeoff-list-title">
          <h4 id="tradeoff-list-title" class="m-0 font-black">{{ copy.tradeoffs }}</h4>
          <p v-if="aggregation.unresolved_trade_offs.length === 0">{{ copy.none }}</p>
          <ul v-else class="pl-5">
            <li v-for="item in aggregation.unresolved_trade_offs" :key="item">{{ item }}</li>
          </ul>
        </section>
        <section aria-labelledby="evidence-gap-list-title">
          <h4 id="evidence-gap-list-title" class="m-0 font-black">{{ copy.evidenceGaps }}</h4>
          <p v-if="aggregation.evidence_gaps.length === 0">{{ copy.none }}</p>
          <ul v-else class="pl-5">
            <li v-for="item in aggregation.evidence_gaps" :key="item">{{ item }}</li>
          </ul>
        </section>
        <section aria-labelledby="human-question-list-title">
          <h4 id="human-question-list-title" class="m-0 font-black">{{ copy.questions }}</h4>
          <p v-if="aggregation.human_validation_questions.length === 0">{{ copy.none }}</p>
          <ul v-else class="pl-5">
            <li v-for="item in aggregation.human_validation_questions" :key="item">{{ item }}</li>
          </ul>
        </section>
      </div>
    </section>

    <section class="grid gap-4" aria-labelledby="final-review-title">
      <h3 id="final-review-title" class="m-0 text-xl font-black">{{ copy.review }}</h3>
      <p v-if="!review">{{ copy.noReview }}</p>
      <template v-else>
        <dl class="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 sm:grid-cols-3">
          <div>
            <dt class="font-bold">Version</dt>
            <dd class="m-0">{{ review.version_number }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.capability }}</dt>
            <dd class="m-0">{{ review.capability_status ?? "—" }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.validation }}</dt>
            <dd class="m-0">{{ review.human_validation_status }}</dd>
          </div>
        </dl>

        <p
          class="m-0 rounded-xl border p-4 font-bold"
          :class="
            review.ready_for_gate8 ? 'border-emerald-300 bg-emerald-50' : 'border-red-300 bg-red-50'
          "
          aria-live="polite"
          data-testid="gate8-readiness"
        >
          {{ review.ready_for_gate8 ? copy.ready : copy.blocked }}
        </p>

        <div class="grid gap-5 lg:grid-cols-3">
          <section aria-labelledby="final-check-list-title">
            <h4 id="final-check-list-title" class="m-0 font-black">{{ copy.checks }}</h4>
            <p v-if="review.checks.length === 0">{{ copy.none }}</p>
            <ul v-else class="grid gap-2 pl-5">
              <li v-for="check in review.checks" :key="check.check_id">
                <strong>{{ check.summary }}</strong>
                <span class="block text-sm">
                  {{ check.status }} · {{ check.blocks_gate8 ? copy.blocking : copy.nonBlocking }}
                </span>
              </li>
            </ul>
          </section>
          <section aria-labelledby="final-issue-list-title">
            <h4 id="final-issue-list-title" class="m-0 font-black">{{ copy.issues }}</h4>
            <p v-if="review.unresolved_issues.length === 0">{{ copy.none }}</p>
            <ul v-else class="grid gap-2 pl-5">
              <li v-for="issue in review.unresolved_issues" :key="issue.issue_id">
                <strong>{{ issue.summary }}</strong>
                <span class="block text-sm">
                  {{ issue.severity }} · {{ issue.blocks_gate8 ? copy.blocking : copy.nonBlocking }}
                </span>
              </li>
            </ul>
          </section>
          <section aria-labelledby="accepted-limitation-list-title">
            <h4 id="accepted-limitation-list-title" class="m-0 font-black">
              {{ copy.limitations }}
            </h4>
            <p v-if="review.accepted_limitations.length === 0">{{ copy.none }}</p>
            <ul v-else class="grid gap-2 pl-5">
              <li v-for="limitation in review.accepted_limitations" :key="limitation.limitation_id">
                <strong>{{ limitation.summary }}</strong>
                <span class="block text-sm">{{ limitation.rationale }}</span>
              </li>
            </ul>
          </section>
        </div>
      </template>
    </section>

    <section class="grid gap-4" aria-labelledby="gate8-controls-title">
      <h3 id="gate8-controls-title" class="m-0 text-xl font-black">{{ copy.gate8 }}</h3>
      <p class="m-0 rounded-xl border border-violet-200 bg-violet-50 p-4 text-violet-950">
        {{ copy.ownerBoundary }}
      </p>
      <p aria-live="polite" data-testid="gate8-status">
        <strong>{{ copy.gateStatus }}:</strong> {{ approval?.status ?? copy.notSubmitted }}
      </p>
      <div class="flex flex-wrap gap-3">
        <button
          type="button"
          class="rounded-lg border border-violet-300 bg-violet-50 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canSubmitGate8"
          @click="emit('submitGate8')"
        >
          {{ copy.submit }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canDecideGate8"
          @click="emit('decideGate8', 'APPROVE')"
        >
          {{ copy.approve }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-red-300 bg-red-50 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canDecideGate8"
          @click="emit('decideGate8', 'REJECT')"
        >
          {{ copy.reject }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-orange-300 bg-orange-50 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canDecideGate8"
          @click="emit('decideGate8', 'REQUEST_REVISION')"
        >
          {{ copy.revise }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-slate-300 bg-white px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canDecideGate8"
          @click="emit('decideGate8', 'PAUSE')"
        >
          {{ copy.pause }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-slate-500 bg-slate-100 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canDecideGate8"
          @click="emit('decideGate8', 'CANCEL')"
        >
          {{ copy.cancel }}
        </button>
      </div>
    </section>

    <section class="grid gap-4" aria-labelledby="final-export-title">
      <h3 id="final-export-title" class="m-0 text-xl font-black">{{ copy.export }}</h3>
      <p v-if="!exportBundle">{{ copy.noExport }}</p>
      <template v-else>
        <dl class="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 sm:grid-cols-3">
          <div>
            <dt class="font-bold">{{ copy.archiveHash }}</dt>
            <dd class="m-0 font-mono text-xs break-all">{{ exportBundle.archive_hash }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.archiveSize }}</dt>
            <dd class="m-0">{{ formatBytes(exportBundle.archive_size_bytes) }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.manifestHash }}</dt>
            <dd class="m-0 font-mono text-xs break-all">{{ exportBundle.manifest_hash }}</dd>
          </div>
        </dl>

        <div v-if="exportBundle.manifest" class="grid gap-5 lg:grid-cols-2">
          <section aria-labelledby="manifest-entry-list-title">
            <h4 id="manifest-entry-list-title" class="m-0 font-black">
              {{ copy.manifestEntries }}
            </h4>
            <ol class="grid gap-2 pl-6">
              <li v-for="entry in exportBundle.manifest.entries" :key="entry.path">
                <code>{{ entry.path }}</code>
                <span class="block text-sm">
                  {{ entry.category }} · {{ entry.required ? copy.required : copy.optional }}
                </span>
              </li>
            </ol>
          </section>
          <section aria-labelledby="manifest-omission-list-title">
            <h4 id="manifest-omission-list-title" class="m-0 font-black">
              {{ copy.manifestOmissions }}
            </h4>
            <p v-if="exportBundle.manifest.omissions.length === 0">{{ copy.none }}</p>
            <ul v-else class="grid gap-2 pl-5">
              <li v-for="omission in exportBundle.manifest.omissions" :key="omission.category">
                <strong>{{ omission.category }}</strong>
                <span class="block text-sm">{{ omission.reason }}</span>
              </li>
            </ul>
          </section>
        </div>
      </template>

      <div class="flex flex-wrap gap-3">
        <button
          type="button"
          class="rounded-lg border border-violet-300 bg-violet-50 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canCreateExport"
          @click="emit('createExport')"
        >
          {{ copy.createExport }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-slate-300 bg-white px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canDownloadExport"
          @click="emit('downloadExport')"
        >
          {{ copy.download }}
        </button>
      </div>
    </section>

    <p class="sr-only" data-testid="finalization-text-alternative">
      {{ copy.textualAlternative }}. {{ review?.ready_for_gate8 ? copy.ready : copy.blocked }}.
      {{ copy.gateStatus }}: {{ approval?.status ?? copy.notSubmitted }}.
    </p>
  </section>
</template>
