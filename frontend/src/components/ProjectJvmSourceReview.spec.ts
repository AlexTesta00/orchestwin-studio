import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { JvmExecutionApi } from "@/api/jvmExecution";
import type { JvmSourceRevisionPayload } from "@/types/jvmExecution";
import ProjectJvmSourceReview from "./ProjectJvmSourceReview.vue";

const PROJECT_ID = "00000000-0000-4000-8000-00000000e101";
const selection = {
  target: "JVM_KOTLIN" as const,
  language: "KOTLIN",
  build_system: "GRADLE_KOTLIN_DSL",
  layout: "SINGLE_MODULE",
  jdk_major: 21,
};

function file(path: string, digest: string) {
  return {
    normalized_path: path,
    sha256_digest: digest,
    size_bytes: 12,
    storage_key: `sha256/${digest.slice(0, 2)}/${digest}`,
    media_type: "text/x-kotlin",
  };
}
function revision(version: number): JvmSourceRevisionPayload {
  return {
    id: `00000000-0000-4000-8000-00000000e10${version + 1}`,
    project_id: PROJECT_ID,
    version_number: version,
    based_on:
      version === 1
        ? null
        : {
            revision_id: "00000000-0000-4000-8000-00000000e102",
            project_id: PROJECT_ID,
            version_number: 1,
            content_hash: "a".repeat(64),
            source_tree_hash: "b".repeat(64),
          },
    target_selection: selection,
    validation_scope_hash: "c".repeat(64),
    origin: version === 1 ? "GENERATED_PLAN" : "REPAIR_CHANGE_SET",
    files:
      version === 1
        ? [file("src/main/kotlin/Main.kt", "d".repeat(64))]
        : [
            file("src/main/kotlin/Calculator.kt", "e".repeat(64)),
            file("src/main/kotlin/Main.kt", "f".repeat(64)),
          ],
    provenance_references: [
      {
        kind: version === 1 ? "SOURCE_PLAN" : "FAILURE_SIGNATURE",
        reference_id: `reference-${version}`,
        version_number: 1,
        content_hash: "1".repeat(64),
      },
    ],
    related_failure_signature: version === 1 ? null : "2".repeat(64),
    source_tree_hash: version === 1 ? "b".repeat(64) : "3".repeat(64),
    content_hash: version === 1 ? "a".repeat(64) : "4".repeat(64),
  };
}

const api = {
  async profiles() {
    return [
      {
        profile_id: "jvm.kotlin-gradle",
        profile_version: "1.0.0",
        target: "JVM_KOTLIN",
        capability_status: "DESIGN_ONLY_LEVEL_C",
        language: "KOTLIN",
        language_version: "2.4.10",
        build_system: "GRADLE_KOTLIN_DSL",
        jdk_major: 21,
        validation_evidence_refs: [],
      },
    ];
  },
  async sourceRevisions() {
    return [revision(1), revision(2)];
  },
  async executions() {
    return [];
  },
} as unknown as JvmExecutionApi;
const authorize = async <T>(operation: (token: string) => Promise<T>): Promise<T> =>
  operation("token");

describe("ProjectJvmSourceReview", () => {
  it("renders capability honesty, toolchain, source lineage, and provenance", async () => {
    const wrapper = mount(ProjectJvmSourceReview, {
      props: { projectId: PROJECT_ID, authorize, api },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("JVM profiles and source revisions");
    expect(wrapper.text()).toContain("DESIGN_ONLY_LEVEL_C");
    expect(wrapper.text()).toContain("GRADLE_KOTLIN_DSL");
    expect(wrapper.text()).toContain("FAILURE_SIGNATURE");
    expect(wrapper.text()).toContain("Validation-scope hash");
  });

  it("compares immutable JVM file digests", async () => {
    const wrapper = mount(ProjectJvmSourceReview, {
      props: { projectId: PROJECT_ID, authorize, api },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("Added · src/main/kotlin/Calculator.kt");
    expect(wrapper.text()).toContain("Changed · src/main/kotlin/Main.kt");
  });

  it("renders Italian review vocabulary", async () => {
    const wrapper = mount(ProjectJvmSourceReview, {
      props: { projectId: PROJECT_ID, locale: "it", authorize, api },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("Profili JVM e revisioni del sorgente");
    expect(wrapper.text()).toContain("Provenienza");
    expect(wrapper.text()).toContain("Modificato · src/main/kotlin/Main.kt");
  });
});
