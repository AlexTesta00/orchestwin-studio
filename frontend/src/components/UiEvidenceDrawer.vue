<script setup lang="ts">
import { ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "./UiButton.vue";

export interface EvidenceEntry {
  key: string;
  value: string;
}

const props = withDefaults(defineProps<{ entries: EvidenceEntry[]; open?: boolean }>(), {
  open: false,
});

const { t } = useI18n({ useScope: "global" });

const expanded = ref(props.open);
const panelId = useId();
</script>

<template>
  <div data-testid="evidence-drawer">
    <UiButton
      variant="secondary"
      :aria-expanded="expanded ? 'true' : 'false'"
      :aria-controls="panelId"
      data-testid="evidence-toggle"
      @click="expanded = !expanded"
    >
      {{ expanded ? t("ui.drawer.hide") : t("ui.drawer.show") }}
    </UiButton>
    <dl
      v-if="expanded"
      :id="panelId"
      class="mt-3 grid grid-cols-[120px_minmax(0,1fr)] gap-x-4 gap-y-2 rounded-panel bg-ink p-4 font-mono text-xs"
    >
      <template v-for="entry in entries" :key="entry.key">
        <dt class="text-evidence-key">{{ entry.key }}</dt>
        <dd class="break-all text-evidence-value">{{ entry.value }}</dd>
      </template>
    </dl>
  </div>
</template>
