import { watch } from "vue";

export type UpstreamValue = string | null | undefined;

export function watchUpstream(
  source: () => UpstreamValue,
  listener: (changed: boolean) => void,
): void {
  let known: string | null = null;

  watch(
    source,
    (value) => {
      if (value === null || value === undefined || value === known) {
        return;
      }

      const changed = known !== null;
      known = value;
      listener(changed);
    },
    { immediate: true },
  );
}
