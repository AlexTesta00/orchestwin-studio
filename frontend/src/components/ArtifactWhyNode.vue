<script setup lang="ts">
import { computed } from "vue";
import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";
import { whyGapLabel, whyMessages, whyNodeTitle } from "./whyCopy";
import type { WhyNode } from "../types/why";

const props = withDefaults(defineProps<{ node: WhyNode; locale?: "en" | "it" }>(), {
  locale: "en",
});
const copy = computed(() => whyMessages[props.locale]);
const rationaleLabel = computed(() => {
  const origin = props.node.rationale?.origin;
  return origin === "MODEL"
    ? copy.value.model
    : origin === "OWNER"
      ? copy.value.owner
      : origin === "SYSTEM"
        ? copy.value.system
        : copy.value.unknown;
});
</script>

<template>
  <article
    class="grid min-w-0 gap-2 rounded-field border border-current/15 p-3 text-sm [overflow-wrap:anywhere]"
    data-testid="why-node"
    :data-why-key="node.key"
  >
    <strong class="font-semibold">{{ whyNodeTitle(node, locale) }}</strong>
    <UserModelingEpistemicBadge
      :status="node.display_status"
      :show-details="false"
      :locale="locale"
    />
    <section
      v-if="node.declared_context.observation_value"
      class="grid gap-1"
      data-testid="why-claim-value"
    >
      <strong>{{ copy.claim }}</strong>
      <p
        v-if="node.declared_context.observation_value.kind === 'TEXT'"
        class="m-0 whitespace-pre-wrap"
      >
        {{ node.declared_context.observation_value.text }}
      </p>
      <ul
        v-else-if="node.declared_context.observation_value.kind === 'ITEMS'"
        class="m-0 grid list-disc gap-1 pl-5"
      >
        <li v-for="(item, index) in node.declared_context.observation_value.items" :key="index">
          {{ item }}
        </li>
      </ul>
      <p v-else class="m-0">
        {{
          node.declared_context.observation_value.kind === "ABSTAINED"
            ? copy.abstainedValue
            : copy.unknownValue
        }}
      </p>
      <p v-if="node.declared_context.observation_value.reason" class="m-0 whitespace-pre-wrap">
        {{ node.declared_context.observation_value.reason }}
      </p>
    </section>
    <p class="m-0 text-xs">
      {{ node.current ? copy.current : copy.historical }} · {{ copy.version }}
      {{ node.reference.version_number ?? "—" }}
    </p>
    <p v-if="node.reference.content_hash" class="m-0 font-mono text-xs break-all">
      {{ copy.hash }}: {{ node.reference.content_hash }}
    </p>
    <div
      v-if="node.declared_context.base_reference"
      class="grid gap-1 text-xs"
      data-testid="why-base-reference"
    >
      <strong>{{ copy.base }}: {{ node.declared_context.base_reference.version_number }}</strong>
      <p class="m-0 font-mono break-all">
        {{ copy.hash }}: {{ node.declared_context.base_reference.content_hash }}
      </p>
    </div>
    <div
      v-if="node.declared_context.audit_reference"
      class="grid gap-1 text-xs"
      data-testid="why-audit-reference"
    >
      <strong>{{ copy.audit }}</strong>
      <p class="m-0 font-mono break-all">
        {{ copy.hash }}: {{ node.declared_context.audit_reference.content_hash }}
      </p>
    </div>
    <div v-if="node.rationale" class="grid gap-1" data-testid="why-rationale">
      <strong>{{ rationaleLabel }}</strong>
      <p class="m-0 whitespace-pre-wrap">{{ node.rationale.text }}</p>
      <p class="m-0 text-xs">{{ copy.version }} {{ node.rationale.version_number ?? "—" }}</p>
      <p v-if="node.rationale.content_hash" class="m-0 font-mono text-xs break-all">
        {{ copy.hash }}: {{ node.rationale.content_hash }}
      </p>
    </div>
    <section
      v-for="(item, index) in node.citations"
      :key="index"
      class="grid gap-1 border-t border-current/15 pt-2"
      data-testid="why-citation"
    >
      <strong
        >{{ copy.source }}:
        {{ item.source?.title ?? item.source?.code ?? item.citation.source_id }}</strong
      >
      <p class="m-0 text-xs">
        {{
          item.effect === "CONTRADICTS"
            ? copy.contradicts
            : item.effect === "ADDS"
              ? copy.adds
              : copy.supports
        }}
      </p>
      <p
        v-if="item.status === 'RETIRED' || item.source?.status === 'RETIRED'"
        class="m-0 font-semibold"
        data-testid="why-retired-source"
      >
        {{ copy.retired }}
      </p>
      <p v-if="item.source?.text_available === false" class="m-0 text-xs">
        {{ copy.sourceUnavailable }}
      </p>
      <p class="m-0 text-xs">
        {{ copy.version }} {{ item.citation.source_version }} · {{ copy.lines }}
        {{ item.citation.start_line }}–{{ item.citation.end_line }} · {{ copy.offsets }}
        {{ item.citation.start }}–{{ item.citation.end }}
      </p>
      <p class="m-0 font-mono text-xs break-all">
        {{ copy.hash }}: {{ item.citation.content_hash }}
      </p>
      <blockquote
        class="m-0 border-l-2 border-current/30 pl-3 whitespace-pre-wrap"
        data-testid="why-quote"
      >
        {{ item.citation.quote }}
      </blockquote>
      <p v-if="item.source?.method" class="m-0 text-xs">{{ item.source.method }}</p>
      <p v-if="item.source?.context" class="m-0 text-xs">{{ item.source.context }}</p>
      <p v-if="item.source?.limitations" class="m-0 text-xs">{{ item.source.limitations }}</p>
    </section>
    <ul v-if="node.gaps.length > 0" class="m-0 grid list-disc gap-1 pl-5 text-xs">
      <li v-for="(gap, index) in node.gaps" :key="index">{{ whyGapLabel(gap.code, locale) }}</li>
    </ul>
    <details class="text-xs">
      <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center">
        {{ node.code }}
      </summary>
      <p class="m-0 font-mono break-all">{{ node.reference.artifact_id }}</p>
    </details>
  </article>
</template>
