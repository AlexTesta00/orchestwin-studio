import { defineStore } from "pinia";
import { ref } from "vue";

export const useShellStore = defineStore("shell", () => {
  const isNavigationOpen = ref(false);

  function toggleNavigation(): void {
    isNavigationOpen.value = !isNavigationOpen.value;
  }

  function closeNavigation(): void {
    isNavigationOpen.value = false;
  }

  return {
    isNavigationOpen,
    toggleNavigation,
    closeNavigation,
  };
});
