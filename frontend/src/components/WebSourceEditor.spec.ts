import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WebSourceEditor from "./WebSourceEditor.vue";
import type { PreviewContent } from "./webPreview";

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    withAccessToken: (_api: unknown, operation: (token: string) => unknown) => operation("token"),
  }),
}));

const CONTENT: PreviewContent = {
  revision_id: "base-revision",
  content_hash: "exact-base-hash",
  files: [
    { path: "index.html", media_type: "text/html", base64: btoa("<h1>Calculator</h1>") },
    { path: "app.js", media_type: "text/javascript", base64: btoa("const result = 1;") },
  ],
};

describe("owner source editor", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  function setup() {
    return mount(WebSourceEditor, {
      props: { projectId: "project", content: CONTENT, locale: "en" },
    });
  }

  it("requires both changed files and a reason, then submits the exact original base and all file bytes", async () => {
    const snapshot = { id: "owner-revision", project_id: "project", version_number: 2 };
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ snapshot })));
    vi.stubGlobal("fetch", fetch);
    const wrapper = setup();
    expect(wrapper.get('[type="submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get("input").setValue("  Add keyboard support  ");
    expect(wrapper.get('[type="submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get("textarea").setValue("<h1>Calcolatrice · accessibile</h1>");
    expect(wrapper.get('[type="submit"]').attributes("disabled")).toBeUndefined();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const [url, options] = fetch.mock.calls[0]!;
    expect(url).toBe("/api/v1/projects/project/web-source-revisions/base-revision/edits");
    expect(options.method).toBe("POST");
    expect(options.headers.Authorization).toBe("Bearer token");
    expect(options.credentials).toBe("include");
    expect(JSON.parse(options.body)).toEqual({
      base_revision_content_hash: "exact-base-hash",
      rationale: "Add keyboard support",
      files: [
        {
          normalized_path: "index.html",
          media_type: "text/html",
          content: "<h1>Calcolatrice · accessibile</h1>",
        },
        { normalized_path: "app.js", media_type: "text/javascript", content: "const result = 1;" },
      ],
    });
    expect(atob(CONTENT.files[0]!.base64)).toBe("<h1>Calculator</h1>");
    expect(wrapper.emitted("saved")).toEqual([[snapshot]]);
    wrapper.unmount();
  });

  it("retains edits and rationale when the server rejects a stale base", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 409 })));
    const wrapper = setup();
    await wrapper.get("textarea").setValue("<h1>My unsaved edit</h1>");
    await wrapper.get("input").setValue("Fix buttons");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "base revision or architecture has changed",
    );
    expect(wrapper.get("textarea").element.value).toBe("<h1>My unsaved edit</h1>");
    expect(wrapper.get("input").element.value).toBe("Fix buttons");
    expect(wrapper.emitted("saved")).toBeUndefined();
    expect(wrapper.get('[type="submit"]').attributes("disabled")).toBeUndefined();
    wrapper.unmount();
  });

  it("keeps files and allows retry after a request failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    const wrapper = setup();
    await wrapper.get("textarea").setValue("<h1>Ready for retry</h1>");
    await wrapper.get("input").setValue("Fix interaction");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("Revision was not saved");
    expect(wrapper.get("textarea").element.value).toBe("<h1>Ready for retry</h1>");
    expect(wrapper.attributes("aria-busy")).toBe("false");
    expect(wrapper.get('[type="submit"]').attributes("disabled")).toBeUndefined();
    wrapper.unmount();
  });

  it("explains a rejected mockup change without discarding edits or exposing raw server text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "WEB_SOURCE_MOCKUP_STRUCTURE_MISMATCH",
              message: "private server detail",
            },
          }),
          { status: 409 },
        ),
      ),
    );
    const wrapper = setup();
    await wrapper.get("textarea").setValue("<h1>Unsaved redesign</h1>");
    await wrapper.get("input").setValue("Change layout");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "no longer match the selected screen design",
    );
    expect(wrapper.text()).not.toContain("private server detail");
    expect(wrapper.get("textarea").element.value).toContain("Unsaved redesign");
    expect(wrapper.emitted("saved")).toBeUndefined();
    wrapper.unmount();
  });

  it("does not publish a late response after the editor was unmounted", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
      ),
    );
    const wrapper = setup();
    await wrapper.get("textarea").setValue("<h1>Edited</h1>");
    await wrapper.get("input").setValue("Repair");
    await wrapper.get("form").trigger("submit");
    wrapper.unmount();
    finish(new Response(JSON.stringify({ snapshot: { id: "late", project_id: "project" } })));
    await flushPromises();
    expect(wrapper.emitted("saved")).toBeUndefined();
  });
});
