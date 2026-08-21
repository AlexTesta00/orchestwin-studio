<script setup lang="ts">
import { computed } from "vue";

import type { ArchitecturePackagePayload } from "../types/architecture";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    packageValue: ArchitecturePackagePayload;
    locale?: Locale;
  }>(),
  {
    locale: "en",
  },
);

const messages = {
  en: {
    summary: "Architecture summary",
    style: "Architecture style",
    exactGrounding: "Exact approved grounding",
    design: "Design Package",
    requirements: "Requirements Specification",
    team: "Agent Team",
    userModeling: "User Modeling",
    selectedDesign: "Selected design alternative",
    prototype: "Declarative prototype",
    components: "Components",
    responsibility: "Responsibility",
    technology: "Technology",
    interfaces: "Interfaces",
    connections: "Connections",
    decisions: "Architecture decisions",
    dataEntities: "Data entities",
    apiOperations: "API operations",
    risks: "Architecture risks",
    qualityAttributes: "Quality attributes",
    deployment: "Deployment view",
    testPlan: "Test plan",
    strategy: "Strategy",
    environments: "Test environments",
    testCases: "Traceable test cases",
    qualityGates: "Quality gates",
    level: "Level",
    automation: "Automation",
    priority: "Priority",
    verifies: "Verifies",
    passRate: "Minimum pass rate",
    blocking: "Blocking",
    yes: "Yes",
    no: "No",
    openQuestions: "Open questions",
    none: "None declared.",
    methodology:
      "The architecture and test plan are proposals grounded in exact approved artifacts. Gate 6 approval governs implementation readiness; it is not empirical user validation.",
  },
  it: {
    summary: "Sintesi dell'architettura",
    style: "Stile architetturale",
    exactGrounding: "Grounding approvato esatto",
    design: "Design Package",
    requirements: "Requirements Specification",
    team: "Agent Team",
    userModeling: "User Modeling",
    selectedDesign: "Alternativa di design selezionata",
    prototype: "Prototipo dichiarativo",
    components: "Componenti",
    responsibility: "Responsabilità",
    technology: "Tecnologia",
    interfaces: "Interfacce",
    connections: "Connessioni",
    decisions: "Decisioni architetturali",
    dataEntities: "Entità dati",
    apiOperations: "Operazioni API",
    risks: "Rischi architetturali",
    qualityAttributes: "Attributi di qualità",
    deployment: "Vista di deployment",
    testPlan: "Piano di test",
    strategy: "Strategia",
    environments: "Ambienti di test",
    testCases: "Casi di test tracciabili",
    qualityGates: "Quality gate",
    level: "Livello",
    automation: "Automazione",
    priority: "Priorità",
    verifies: "Verifica",
    passRate: "Pass rate minimo",
    blocking: "Bloccante",
    yes: "Sì",
    no: "No",
    openQuestions: "Domande aperte",
    none: "Nessuna dichiarata.",
    methodology:
      "L'architettura e il piano di test sono proposte basate su artefatti approvati esatti. L'approvazione del Gate 6 governa la readiness per l'implementazione; non è validazione empirica degli utenti.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const architecture = computed(() => props.packageValue.architecture);
const testPlan = computed(() => props.packageValue.test_plan);

function referenceLabel(value: {
  artifact_id: string;
  version_number: number;
  content_hash: string;
}): string {
  return `${value.artifact_id} · v${value.version_number} · ${value.content_hash}`;
}
</script>

<template>
  <article class="grid gap-8" data-testid="architecture-plan-review">
    <section class="grid gap-4" aria-labelledby="architecture-summary-title">
      <div class="grid gap-2">
        <p class="m-0 text-xs font-black tracking-[0.18em] text-indigo-700 uppercase">
          {{ architecture.code }} · {{ copy.style }}: {{ architecture.style }}
        </p>
        <h3 id="architecture-summary-title" class="text-2xl font-black text-slate-950">
          {{ architecture.title }}
        </h3>
        <p class="m-0 text-slate-700">{{ architecture.summary }}</p>
      </div>

      <div class="grid gap-3 rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
        <h4 class="text-lg font-black text-indigo-950">{{ copy.exactGrounding }}</h4>
        <dl class="grid gap-3 text-sm">
          <div class="grid gap-1">
            <dt class="font-bold text-indigo-900">{{ copy.design }}</dt>
            <dd class="m-0 break-all text-indigo-800">
              {{ referenceLabel(packageValue.grounding.design_package_reference) }}
            </dd>
          </div>
          <div class="grid gap-1">
            <dt class="font-bold text-indigo-900">{{ copy.requirements }}</dt>
            <dd class="m-0 break-all text-indigo-800">
              {{ referenceLabel(packageValue.grounding.requirements_reference) }}
            </dd>
          </div>
          <div class="grid gap-1">
            <dt class="font-bold text-indigo-900">{{ copy.team }}</dt>
            <dd class="m-0 break-all text-indigo-800">
              {{ referenceLabel(packageValue.grounding.agent_team_reference) }}
            </dd>
          </div>
          <div class="grid gap-1">
            <dt class="font-bold text-indigo-900">{{ copy.userModeling }}</dt>
            <dd class="m-0 break-all text-indigo-800">
              {{ referenceLabel(packageValue.grounding.user_modeling_reference) }}
            </dd>
          </div>
          <div class="grid gap-1 sm:grid-cols-2">
            <div>
              <dt class="font-bold text-indigo-900">{{ copy.selectedDesign }}</dt>
              <dd class="m-0 break-all text-indigo-800">
                {{ packageValue.grounding.owner_selected_alternative_id }}
              </dd>
            </div>
            <div>
              <dt class="font-bold text-indigo-900">{{ copy.prototype }}</dt>
              <dd class="m-0 break-all text-indigo-800">
                {{ packageValue.grounding.prototype_id }}
              </dd>
            </div>
          </div>
        </dl>
      </div>
    </section>

    <section class="grid gap-4" aria-labelledby="architecture-components-title">
      <h3 id="architecture-components-title" class="text-xl font-black text-slate-950">
        {{ copy.components }}
      </h3>
      <ul class="grid gap-4 lg:grid-cols-2">
        <li
          v-for="component in architecture.components"
          :key="component.id"
          class="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div>
            <p class="m-0 text-xs font-black tracking-wide text-slate-500 uppercase">
              {{ component.code }} · {{ component.kind }}
            </p>
            <h4 class="mt-1 text-lg font-black text-slate-950">{{ component.name }}</h4>
          </div>
          <dl class="grid gap-2 text-sm text-slate-700">
            <div>
              <dt class="font-bold text-slate-900">{{ copy.responsibility }}</dt>
              <dd class="m-0">{{ component.responsibility }}</dd>
            </div>
            <div>
              <dt class="font-bold text-slate-900">{{ copy.technology }}</dt>
              <dd class="m-0">{{ component.technology }}</dd>
            </div>
            <div>
              <dt class="font-bold text-slate-900">{{ copy.interfaces }}</dt>
              <dd class="m-0">{{ component.interfaces.join(", ") || copy.none }}</dd>
            </div>
          </dl>
        </li>
      </ul>
    </section>

    <section class="grid gap-4" aria-labelledby="architecture-connections-title">
      <h3 id="architecture-connections-title" class="text-xl font-black text-slate-950">
        {{ copy.connections }}
      </h3>
      <div class="overflow-x-auto rounded-2xl border border-slate-200">
        <table class="w-full min-w-3xl border-collapse text-left text-sm">
          <thead class="bg-slate-100 text-slate-900">
            <tr>
              <th class="px-4 py-3" scope="col">ID</th>
              <th class="px-4 py-3" scope="col">{{ copy.connections }}</th>
              <th class="px-4 py-3" scope="col">{{ copy.summary }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="connection in architecture.connections"
              :key="connection.id"
              class="border-t border-slate-200"
            >
              <th class="px-4 py-3 font-black text-slate-900" scope="row">
                {{ connection.code }}
              </th>
              <td class="px-4 py-3 text-slate-700">
                {{ connection.source_component_id }} → {{ connection.target_component_id }} ·
                {{ connection.kind }}
              </td>
              <td class="px-4 py-3 text-slate-700">{{ connection.description }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="grid gap-6 lg:grid-cols-2">
      <section class="grid gap-3 rounded-2xl border border-slate-200 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.decisions }}</h3>
        <article v-for="decision in architecture.decisions" :key="decision.id" class="grid gap-2">
          <h4 class="font-black text-slate-900">{{ decision.code }} · {{ decision.title }}</h4>
          <p class="m-0 text-sm text-slate-700">{{ decision.decision }}</p>
          <ul class="list-disc pl-5 text-sm text-slate-600">
            <li v-for="consequence in decision.consequences" :key="consequence">
              {{ consequence }}
            </li>
          </ul>
        </article>
      </section>

      <section class="grid gap-3 rounded-2xl border border-slate-200 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.risks }}</h3>
        <article v-for="risk in architecture.risks" :key="risk.id" class="grid gap-2">
          <h4 class="font-black text-slate-900">
            {{ risk.code }} · {{ risk.impact }}/{{ risk.likelihood }}
          </h4>
          <p class="m-0 text-sm text-slate-700">{{ risk.summary }}</p>
          <p class="m-0 text-sm text-slate-600">{{ risk.mitigation }}</p>
        </article>
      </section>

      <section class="grid gap-3 rounded-2xl border border-slate-200 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.dataEntities }}</h3>
        <article v-for="entity in architecture.data_entities" :key="entity.id" class="grid gap-1">
          <h4 class="font-black text-slate-900">{{ entity.code }} · {{ entity.name }}</h4>
          <p class="m-0 text-sm text-slate-700">{{ entity.description }}</p>
          <code class="text-xs text-slate-600">{{ entity.fields.join(" · ") }}</code>
        </article>
      </section>

      <section class="grid gap-3 rounded-2xl border border-slate-200 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.apiOperations }}</h3>
        <article
          v-for="operation in architecture.api_operations"
          :key="operation.id"
          class="grid gap-1"
        >
          <h4 class="font-black text-slate-900">
            {{ operation.code }} · {{ operation.method }} {{ operation.path }}
          </h4>
          <p class="m-0 text-sm text-slate-700">{{ operation.summary }}</p>
        </article>
      </section>
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      <section class="grid gap-3 rounded-2xl border border-slate-200 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.qualityAttributes }}</h3>
        <ul class="list-disc pl-5 text-sm text-slate-700">
          <li v-for="attribute in architecture.quality_attributes" :key="attribute">
            {{ attribute }}
          </li>
        </ul>
      </section>
      <section class="grid gap-3 rounded-2xl border border-slate-200 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.deployment }}</h3>
        <ol class="list-decimal pl-5 text-sm text-slate-700">
          <li v-for="item in architecture.deployment_view" :key="item">{{ item }}</li>
        </ol>
      </section>
    </div>

    <section class="grid gap-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
      <div class="grid gap-2">
        <p class="m-0 text-xs font-black tracking-[0.18em] text-emerald-700 uppercase">
          {{ testPlan.code }} · {{ copy.testPlan }}
        </p>
        <h3 class="text-2xl font-black text-emerald-950">{{ testPlan.title }}</h3>
        <p class="m-0 text-emerald-900">
          <strong>{{ copy.strategy }}:</strong> {{ testPlan.strategy }}
        </p>
      </div>

      <div class="grid gap-5 lg:grid-cols-2">
        <section class="grid gap-3">
          <h4 class="text-lg font-black text-emerald-950">{{ copy.environments }}</h4>
          <article
            v-for="environment in testPlan.environments"
            :key="environment.id"
            class="rounded-xl border border-emerald-200 bg-white p-4"
          >
            <h5 class="font-black text-slate-950">
              {{ environment.code }} · {{ environment.name }} · {{ environment.kind }}
            </h5>
            <p class="mt-2 text-sm text-slate-700">{{ environment.description }}</p>
          </article>
        </section>

        <section class="grid gap-3">
          <h4 class="text-lg font-black text-emerald-950">{{ copy.qualityGates }}</h4>
          <article
            v-for="qualityGate in testPlan.quality_gates"
            :key="qualityGate.id"
            class="rounded-xl border border-emerald-200 bg-white p-4"
          >
            <h5 class="font-black text-slate-950">
              {{ qualityGate.code }} · {{ qualityGate.title }}
            </h5>
            <p class="mt-2 text-sm text-slate-700">{{ qualityGate.criterion }}</p>
            <p class="mt-2 text-sm text-slate-600">
              {{ copy.passRate }}: {{ qualityGate.minimum_pass_rate }}% · {{ copy.blocking }}:
              {{ qualityGate.blocking ? copy.yes : copy.no }}
            </p>
          </article>
        </section>
      </div>

      <section class="grid gap-3" aria-labelledby="planned-tests-title">
        <h4 id="planned-tests-title" class="text-lg font-black text-emerald-950">
          {{ copy.testCases }}
        </h4>
        <div class="overflow-x-auto rounded-xl border border-emerald-200 bg-white">
          <table class="w-full min-w-4xl border-collapse text-left text-sm">
            <thead class="bg-emerald-100 text-emerald-950">
              <tr>
                <th class="px-4 py-3" scope="col">ID</th>
                <th class="px-4 py-3" scope="col">{{ copy.summary }}</th>
                <th class="px-4 py-3" scope="col">{{ copy.level }}</th>
                <th class="px-4 py-3" scope="col">{{ copy.automation }}</th>
                <th class="px-4 py-3" scope="col">{{ copy.priority }}</th>
                <th class="px-4 py-3" scope="col">{{ copy.verifies }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="testCase in testPlan.test_cases"
                :key="testCase.id"
                class="border-t border-emerald-200"
              >
                <th class="px-4 py-3 font-black text-slate-900" scope="row">
                  {{ testCase.code }}
                </th>
                <td class="px-4 py-3 text-slate-700">{{ testCase.title }}</td>
                <td class="px-4 py-3 text-slate-700">{{ testCase.level }}</td>
                <td class="px-4 py-3 text-slate-700">{{ testCase.automation }}</td>
                <td class="px-4 py-3 text-slate-700">{{ testCase.priority }}</td>
                <td class="px-4 py-3 text-xs text-slate-600">
                  {{ testCase.requirement_ids.join(", ") }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>

    <section class="grid gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-5">
      <h3 class="text-xl font-black text-amber-950">{{ copy.openQuestions }}</h3>
      <ul v-if="packageValue.open_questions.length > 0" class="list-disc pl-5 text-amber-900">
        <li v-for="question in packageValue.open_questions" :key="question">{{ question }}</li>
      </ul>
      <p v-else class="m-0 text-amber-900">{{ copy.none }}</p>
    </section>

    <p class="m-0 rounded-2xl border border-slate-300 bg-slate-100 p-4 text-sm text-slate-700">
      {{ copy.methodology }}
    </p>
  </article>
</template>
