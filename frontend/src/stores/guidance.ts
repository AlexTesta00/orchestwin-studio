import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";

import { useAuthStore } from "./auth";

export type GuidanceMode = "GUIDED" | "EXPERT";

export function guidancePreferenceKey(accountId: string): string {
  return `orchestwin.guidance.v1.${encodeURIComponent(accountId)}`;
}

export function readGuidancePreference(accountId: string | null): GuidanceMode {
  if (!accountId) return "GUIDED";
  try {
    return window.localStorage.getItem(guidancePreferenceKey(accountId)) === "EXPERT"
      ? "EXPERT"
      : "GUIDED";
  } catch {
    return "GUIDED";
  }
}

export const useGuidanceStore = defineStore("guidance", () => {
  const auth = useAuthStore();
  const mode = ref<GuidanceMode>("GUIDED");
  const accountId = computed(() => auth.user?.id ?? null);
  const expert = computed(() => mode.value === "EXPERT");
  const suppressedAutomatic = new Set<string>();

  watch(
    accountId,
    (id) => {
      suppressedAutomatic.clear();
      mode.value = readGuidancePreference(id);
    },
    { immediate: true },
  );

  function suppressAutomatic(key: string): void {
    suppressedAutomatic.add(key);
  }

  function automaticAllowed(key: string): boolean {
    return !expert.value && !suppressedAutomatic.has(key);
  }

  function select(value: GuidanceMode): void {
    if (!accountId.value) return;
    mode.value = value;
    try {
      window.localStorage.setItem(guidancePreferenceKey(accountId.value), value);
    } catch {
      return;
    }
  }

  return { mode, expert, accountId, select, suppressAutomatic, automaticAllowed };
});
