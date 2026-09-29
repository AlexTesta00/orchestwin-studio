import { effectScope, nextTick, ref } from "vue";
import { describe, expect, it } from "vitest";

import { type UpstreamValue, watchUpstream } from "./upstreamChange";

async function follow(values: readonly UpstreamValue[], initial: UpstreamValue = null) {
  const value = ref<UpstreamValue>(initial);
  const heard: boolean[] = [];
  const scope = effectScope();
  scope.run(() =>
    watchUpstream(
      () => value.value,
      (changed) => heard.push(changed),
    ),
  );

  for (const next of values) {
    value.value = next;
    await nextTick();
  }

  scope.stop();
  return heard;
}

describe("watchUpstream", () => {
  it("takes the first known value as the starting point and not as a change", async () => {
    expect(await follow([undefined, null, "brief-1"])).toEqual([false]);
    expect(await follow([], "brief-1")).toEqual([false]);
  });

  it("does not take an unknown value, or the same known value after it, as a change", async () => {
    expect(await follow(["brief-1", null, "brief-1", undefined, "brief-1"])).toEqual([false]);
  });

  it("tells a change once for every known value that differs from the last known one", async () => {
    expect(await follow(["brief-1", "brief-2", null, "brief-2", "brief-3", undefined])).toEqual([
      false,
      true,
      true,
    ]);
  });

  it("compares with the last known value, not with the value before the unknown", async () => {
    expect(await follow(["brief-1", null, "brief-2", null, "brief-1"])).toEqual([
      false,
      true,
      true,
    ]);
  });

  it("stops listening with the scope that created it", async () => {
    const value = ref<UpstreamValue>("brief-1");
    const heard: boolean[] = [];
    const scope = effectScope();
    scope.run(() =>
      watchUpstream(
        () => value.value,
        (changed) => heard.push(changed),
      ),
    );
    scope.stop();

    value.value = "brief-2";
    await nextTick();

    expect(heard).toEqual([false]);
  });
});
