import { nextTick, ref, type Ref } from "vue";

export const STEP_DECISION_BAR = "step-decision-bar";
export const STEP_TECHNICAL_ROW = "step-technical-row";

interface StepTargetOptions {
  active?: () => boolean;
  firstVisible?: boolean;
  onRefresh?: () => void;
}

export function rendered(element: Element): boolean {
  return typeof element.checkVisibility !== "function" || element.checkVisibility();
}

function renderedById(id: string): HTMLElement | null {
  const element = document.getElementById(id);
  return element !== null && rendered(element) ? element : null;
}

function firstVisibleById(id: string): HTMLElement | null {
  for (const candidate of document.querySelectorAll<HTMLElement>(`#${id}`)) {
    if (rendered(candidate)) {
      return candidate;
    }
  }
  return null;
}

export function useStepTargets(root: Ref<HTMLElement | null>, options: StepTargetOptions = {}) {
  const find = options.firstVisible ? firstVisibleById : renderedById;
  const barTarget = ref<HTMLElement | null>(null);
  const rowTarget = ref<HTMLElement | null>(null);
  let observer: ResizeObserver | null = null;

  function refreshTargets(): void {
    const element = root.value;
    const shown =
      (options.active?.() ?? true) && element !== null && element.isConnected && rendered(element);
    const bar = shown ? find(STEP_DECISION_BAR) : null;
    const row = shown ? find(STEP_TECHNICAL_ROW) : null;
    if (barTarget.value !== bar) barTarget.value = bar;
    if (rowTarget.value !== row) rowTarget.value = row;
    options.onRefresh?.();
  }

  async function refreshAfterRender(): Promise<void> {
    await nextTick();
    refreshTargets();
  }

  function trackTargets(): void {
    refreshTargets();
    void refreshAfterRender();
    if (typeof ResizeObserver !== "undefined" && root.value !== null) {
      observer = new ResizeObserver(refreshTargets);
      observer.observe(root.value);
    }
  }

  function untrackTargets(): void {
    observer?.disconnect();
    observer = null;
  }

  return { barTarget, rowTarget, refreshTargets, refreshAfterRender, trackTargets, untrackTargets };
}
