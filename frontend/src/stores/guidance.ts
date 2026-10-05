import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";

import type { GuidanceMode } from "@/api/contracts";
import { useAuthStore } from "./auth";

export type { GuidanceMode } from "@/api/contracts";

export const useGuidanceStore = defineStore("guidance", () => {
  const auth = useAuthStore();
  const lastMode = ref<GuidanceMode | null>(null);
  const accountId = computed(() => auth.user?.id ?? null);
  const mode = computed<GuidanceMode>(() => lastMode.value ?? "GUIDED");
  const chosen = computed(() => lastMode.value !== null);
  const expert = computed(() => mode.value === "EXPERT");
  const suppressedAutomatic = new Set<string>();
  let lastAccountId: string | null = null;

  watch(
    [accountId, () => auth.user?.guidance_mode ?? null],
    ([id, guidanceMode]) => {
      if (id === null) return;
      if (id !== lastAccountId) {
        lastAccountId = id;
        suppressedAutomatic.clear();
      }
      lastMode.value = guidanceMode;
    },
    { immediate: true, flush: "sync" },
  );

  function suppressAutomatic(key: string): void {
    suppressedAutomatic.add(key);
  }

  function automaticAllowed(key: string): boolean {
    return auth.user?.guidance_mode === "GUIDED" && !suppressedAutomatic.has(key);
  }

  return { mode, chosen, expert, accountId, suppressAutomatic, automaticAllowed };
});
