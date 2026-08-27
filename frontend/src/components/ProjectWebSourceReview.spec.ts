import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ExecutionApi } from "@/api/execution";
import type { WebExecutionApi } from "@/api/webExecution";
import type { ExecutionProfilePayload } from "@/types/execution";
import type { WebExecutionAttemptPayload, WebSourceRevisionPayload } from "@/types/webExecution";
import ProjectWebSourceReview from "./ProjectWebSourceReview.vue";

const PROJECT_ID = "00000000-0000-4000-8000-00000000d101";
const OWNER_ID = "00000000-0000-4000-8000-00000000d102";
const CREATED_AT = "2026-08-27T14:00:00+00:00";

function sourceFile(path: string, digest: string) {
  return {
    normalized_path: path,
    sha256_digest: digest,
    size_bytes: 12,
    storage_key: `sha256/${digest.slice(0, 2)}/${digest}`,
    media_type: path.endsWith(".css") ? "text/css" : "text/html",
  };
}

function revision(version: number): WebSourceRevisionPayload {
  const previousHash = "a".repeat(64);
  const currentHash = "b".repeat(64);
  return {
    id: `00000000-0000-4000-8000-00000000d10${version + 2}`,
    project_id: PROJECT_ID,
    created_by_user_id: OWNER_ID,
    version_number: version,
    based_on:
      version === 1
        ? null
        : {
            revision_id: "00000000-0000-4000-8000-00000000d103",
            project_id: PROJECT_ID,
            version_number: 1,
            content_hash: "c".repeat(64),
            source_tree_hash: "d".repeat(64),
          },
    target_selection: {
      target: "WEB_STATIC",
      language_configuration: { frontend: "STATIC_ASSETS", backend: null },
      layout: "SINGLE_ROOT",
    },
    validation_scope_hash: "e".repeat(64),
    origin: version === 1 ? "GENERATED_PLAN" : "REPAIR_CHANGE_SET",
    files:
      version === 1
        ? [sourceFile("index.html", previousHash)]
        : [sourceFile("assets/site.css", "f".repeat(64)), sourceFile("index.html", currentHash)],
    provenance_references: [
      {
        kind: version === 1 ? "SOURCE_PLAN" : "FAILURE_SIGNATURE",
        reference_id: version === 1 ? "source-plan-1" : "failure-1",
        version_number: 1,
        content_hash: "1".repeat(64),
      },
    ],
    related_failure_signature: version === 1 ? null : "1".repeat(64),
    created_at: CREATED_AT,
    source_tree_hash: version === 1 ? "d".repeat(64) : "2".repeat(64),
    content_hash: version === 1 ? "c".repeat(64) : "3".repeat(64),
  };
}

const PROFILE: ExecutionProfilePayload = {
  profile_id: "web.static",
  name: "Static Web",
  version: "1.0.0",
  capability_status: "DESIGN_ONLY_LEVEL_C",
  supported_targets: ["WEB_STATIC"],
  file_indicators: ["index.html"],
  required_runners: ["node"],
  base_images: [],
  network_policy: {},
  resource_defaults: {
    cpu_count: 2,
    memory_mib: 4096,
    pids_limit: 256,
    writable_tmpfs_mib: 512,
  },
  command_schema_version: 1,
  maintainer: "OrchesTwin Studio",
  license_notes: "Validation is not yet recorded.",
  validation_evidence_refs: [],
  requires_owner_approval: false,
  content_hash: "4".repeat(64),
};

const WEB_API = {
  async sourceRevisions(): Promise<WebSourceRevisionPayload[]> {
    return [revision(1), revision(2)];
  },
  async executions(): Promise<WebExecutionAttemptPayload[]> {
    return [];
  },
} as unknown as WebExecutionApi;

const PROFILE_API = {
  async profiles(): Promise<ExecutionProfilePayload[]> {
    return [PROFILE];
  },
} as unknown as ExecutionApi;

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

describe("ProjectWebSourceReview", () => {
  it("renders capability honesty, source lineage, files, and provenance", async () => {
    const wrapper = mount(ProjectWebSourceReview, {
      props: {
        projectId: PROJECT_ID,
        authorize,
        webApi: WEB_API,
        profileApi: PROFILE_API,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Web profiles and source revisions");
    expect(wrapper.text()).toContain("DESIGN_ONLY_LEVEL_C");
    expect(wrapper.text()).toContain("No Level D evidence is recorded");
    expect(wrapper.text()).toContain("index.html");
    expect(wrapper.text()).toContain("assets/site.css");
    expect(wrapper.text()).toContain("FAILURE_SIGNATURE");
    expect(wrapper.text()).toContain("Validation-scope hash");
  });

  it("compares immutable file digests without mutating revision history", async () => {
    const wrapper = mount(ProjectWebSourceReview, {
      props: {
        projectId: PROJECT_ID,
        authorize,
        webApi: WEB_API,
        profileApi: PROFILE_API,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Added · assets/site.css");
    expect(wrapper.text()).toContain("Changed · index.html");
    expect(wrapper.findAll("ol > li")).toHaveLength(2);
  });

  it("renders the Italian review vocabulary", async () => {
    const wrapper = mount(ProjectWebSourceReview, {
      props: {
        projectId: PROJECT_ID,
        locale: "it",
        authorize,
        webApi: WEB_API,
        profileApi: PROFILE_API,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Profili Web e revisioni del sorgente");
    expect(wrapper.text()).toContain("Provenienza");
    expect(wrapper.text()).toContain("Modificato · index.html");
  });
});
