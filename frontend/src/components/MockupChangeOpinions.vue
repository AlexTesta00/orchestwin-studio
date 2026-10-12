<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from "vue";

import { changeOpinionCopy } from "./changeOpinionCopy";
import { fill, plural } from "./textFormat";
import UiButton from "./UiButton.vue";
import UiStateBlock from "./UiStateBlock.vue";
import { VERDICT_STYLES } from "./verdictStyles";
import type {
  ChangeOpinion,
  ChangeOpinionRun,
  ChangeOpinionVerdict,
} from "../types/designOpinions";

const props = withDefaults(
  defineProps<{
    run: ChangeOpinionRun | null;
    busy: boolean;
    stale: boolean;
    canApply: boolean;
    locale: "en" | "it";
    focusOnArrival?: boolean | undefined;
  }>(),
  { focusOnArrival: true },
);

const emit = defineEmits<{
  apply: [];
  change: [];
  cancel: [];
  try: [text: string];
}>();

const VERDICTS: readonly ChangeOpinionVerdict[] = ["HELPS", "SLOWS", "BLOCKS"];

const copy = computed(() => changeOpinionCopy[props.locale]);

const titleId = useId();
const title = ref<HTMLElement | null>(null);
const announcement = ref("");

function suggestion(opinion: ChangeOpinion): string {
  return opinion.try_this ?? opinion.what_to_do;
}

function partId(index: number, part: "action" | "suggestion"): string {
  return `${titleId}-${index}-${part}`;
}

function arrivalText(run: ChangeOpinionRun): string {
  const verdicts = VERDICTS.flatMap((verdict) => {
    const count = run.opinions.filter((opinion) => opinion.verdict === verdict).length;
    return count === 0 ? [] : [plural(count, copy.value.counts[verdict])];
  });
  return fill(copy.value.arrived, {
    twins: plural(run.opinions.length, copy.value.twins),
    verdicts: verdicts.join(", "),
  });
}

watch(
  () => props.run?.run_id ?? null,
  async () => {
    const run = props.run;
    announcement.value = run === null ? "" : arrivalText(run);
    if (run !== null && props.focusOnArrival) {
      await nextTick();
      title.value?.focus();
    }
  },
);
</script>

<template>
  <section
    v-if="busy || run !== null"
    class="grid gap-3"
    :aria-labelledby="titleId"
    data-testid="mockup-change-opinions"
  >
    <div class="grid gap-1">
      <h5 :id="titleId" ref="title" tabindex="-1" class="text-sm font-semibold">
        {{ copy.title }}
      </h5>
      <p class="text-xs leading-normal text-violet-on-night-2">{{ copy.note }}</p>
    </div>
    <UiStateBlock
      v-if="busy"
      kind="loading"
      :title="copy.busy"
      :text="copy.busyTime"
      data-testid="mockup-opinions-busy"
    />
    <template v-else-if="run !== null">
      <ul class="grid list-none gap-2" data-testid="mockup-opinions">
        <li
          v-for="(opinion, index) in run.opinions"
          :key="opinion.twin_id"
          class="grid gap-1.5 rounded-[14px] border-[1.5px] border-dashed border-violet-on-night/70 bg-on-night/3 p-3"
          :data-verdict="opinion.verdict"
          data-testid="mockup-opinion"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-semibold text-on-night" data-testid="mockup-opinion-twin">
              {{ opinion.twin_name }}
            </span>
            <span
              :class="[
                'inline-flex min-h-6 items-center rounded-pill px-[9px] text-xs font-semibold',
                VERDICT_STYLES[opinion.verdict],
              ]"
              data-testid="mockup-opinion-verdict"
            >
              {{ copy.verdicts[opinion.verdict] }}
            </span>
          </div>
          <p class="text-sm leading-normal text-on-night" data-testid="mockup-opinion-why">
            {{ opinion.why }}
          </p>
          <p
            :id="partId(index, 'action')"
            class="text-sm leading-normal text-on-night-2"
            data-testid="mockup-opinion-action"
          >
            <strong class="font-semibold text-on-night">{{ copy.todo }}</strong>
            {{ opinion.what_to_do }}
          </p>
          <p
            v-if="opinion.try_this !== null"
            :id="partId(index, 'suggestion')"
            class="text-sm leading-normal text-on-night-2"
            data-testid="mockup-opinion-suggestion"
          >
            {{ fill(copy.suggestion, { text: opinion.try_this }) }}
          </p>
          <button
            v-if="suggestion(opinion).length > 0"
            type="button"
            class="inline-flex min-h-11 items-center self-start text-left text-[13px] font-medium text-petrol-on-night-2 underline underline-offset-4 transition-colors duration-150 hover:text-on-night"
            :aria-describedby="partId(index, opinion.try_this === null ? 'action' : 'suggestion')"
            data-testid="mockup-opinion-try"
            @click="emit('try', suggestion(opinion))"
          >
            {{ copy.tryThis }}
          </button>
        </li>
      </ul>
      <p
        v-if="stale"
        class="text-[13px] leading-normal text-warn-on-night"
        data-testid="mockup-opinion-stale"
      >
        {{ copy.stale }}
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <UiButton
          v-if="canApply && !stale"
          data-testid="mockup-apply-anyway"
          @click="emit('apply')"
        >
          {{ copy.applyAnyway }}
        </UiButton>
        <UiButton variant="secondary" data-testid="mockup-change-request" @click="emit('change')">
          {{ copy.change }}
        </UiButton>
        <UiButton variant="quiet" data-testid="mockup-cancel-request" @click="emit('cancel')">
          {{ copy.cancel }}
        </UiButton>
      </div>
    </template>
    <p class="sr-only" role="status" aria-live="polite" data-testid="mockup-opinions-announcement">
      {{ announcement }}
    </p>
  </section>
</template>
