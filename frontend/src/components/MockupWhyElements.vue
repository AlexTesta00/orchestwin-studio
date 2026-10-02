<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import { whyContextKey } from "./whyContext";
import { whyMessages, whyNodeTitle } from "./whyCopy";
import type { WhyNode } from "../types/why";

const props = defineProps<{
  alternativeId: string;
  documentHash: string;
  screenCode: string;
  locale: "en" | "it";
}>();
const context = inject(whyContextKey, null);
const nodes = ref<WhyNode[]>([]);
const busy = ref(false);
const failed = ref(false);
const opened = ref(false);
const copy = computed(() => whyMessages[props.locale]);
const screenNodes = computed(() =>
  nodes.value.filter((node) => node.declared_context.mockup?.screen_code === props.screenCode),
);
let epoch = 0;

async function load(): Promise<void> {
  if (!context) return;
  const request = ++epoch;
  const project = context.projectId();
  busy.value = true;
  failed.value = false;
  nodes.value = [];
  try {
    const document = await context.authorize((token) => context.api.document(project, token));
    if (request !== epoch || project !== context.projectId()) return;
    nodes.value = document.nodes.filter((node) => {
      const mockup = node.declared_context.mockup;
      return (
        node.kind === "PROTOTYPE_ELEMENT" &&
        mockup?.alternative_id === props.alternativeId &&
        Object.values(mockup.document_hashes).includes(props.documentHash)
      );
    });
  } catch {
    if (request === epoch) failed.value = true;
  } finally {
    if (request === epoch) busy.value = false;
  }
}

function toggle(event: Event): void {
  if (event.target !== event.currentTarget) return;
  if (!(event.target instanceof HTMLDetailsElement)) return;
  opened.value = event.target.open;
  if (opened.value && !busy.value && nodes.value.length === 0) void load();
}

watch(
  () => [props.documentHash, props.alternativeId, context?.projectId()] as const,
  () => {
    epoch += 1;
    nodes.value = [];
    busy.value = false;
    if (opened.value) void load();
  },
);
</script>

<template>
  <details
    v-if="context"
    class="min-w-0 border-t border-night-line p-4 xl:max-h-[40dvh] xl:overflow-y-auto"
    data-testid="mockup-why-elements"
    @toggle="toggle"
  >
    <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center text-base font-semibold">
      {{ locale === "it" ? "Elementi della schermata" : "Screen elements" }}
    </summary>
    <div class="grid min-w-0 gap-3 pt-2">
      <p v-if="busy" class="m-0 text-sm" role="status">{{ copy.loading }}</p>
      <p v-else-if="failed" class="m-0 text-sm" role="alert">{{ copy.error }}</p>
      <p v-else-if="screenNodes.length === 0" class="m-0 text-sm" data-testid="mockup-why-missing">
        {{ copy.missing }}
      </p>
      <div
        v-for="node in screenNodes"
        :key="node.key"
        class="grid min-w-0 gap-1"
        :data-element-code="node.code"
        data-testid="mockup-why-element"
      >
        <strong class="text-sm [overflow-wrap:anywhere]">{{ whyNodeTitle(node, locale) }}</strong>
        <p class="m-0 text-xs">
          {{ copy.version }} {{ node.reference.version_number }} ·
          {{ node.current ? copy.current : copy.historical }}
        </p>
        <ArtifactWhy
          :code="node.key"
          :title="whyNodeTitle(node, locale)"
          :locale="locale"
          test-id="mockup-element-why"
        />
      </div>
    </div>
  </details>
</template>
