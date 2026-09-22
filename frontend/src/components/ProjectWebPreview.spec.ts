import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWebExecutionStore } from "@/stores/webExecution";
import type { WebSourceRevisionPayload } from "@/types/webExecution";
import ProjectWebPreview from "./ProjectWebPreview.vue";
import WebSourceEditor from "./WebSourceEditor.vue";
import type { PreviewContent } from "./webPreview";
import { expectAccessible } from "@/test/axe";

const authorize = vi.hoisted(() => vi.fn());
const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ withAccessToken: authorize }),
}));

function revision(id = "source", projectId = "project", version = 1): WebSourceRevisionPayload {
  return {
    id,
    project_id: projectId,
    version_number: version,
    content_hash: `${id}-hash`,
    target_selection: { target: "WEB_STATIC" },
    origin: version === 1 ? "GENERATED_PLAN" : "OWNER_EDIT",
  } as WebSourceRevisionPayload;
}
function content(source = revision()): PreviewContent {
  return {
    revision_id: source.id,
    content_hash: source.content_hash,
    files: [{ path: "index.html", media_type: "text/html", base64: btoa("<h1>Calculator</h1>") }],
  };
}
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function setup() {
  const pinia = createPinia();
  const store = useWebExecutionStore(pinia);
  store.$patch({ activeProjectId: "project", sourceRevisions: [revision()] });
  const wrapper = mount(ProjectWebPreview, {
    props: { projectId: "project" },
    global: { plugins: [pinia] },
  });
  const button = (label: string) =>
    wrapper.findAll("button").find((item) => item.text() === label)!;
  return { store, wrapper, button };
}

describe("project source preview", () => {
  beforeEach(() => {
    authorize.mockImplementation((_api, operation) => operation("token"));
  });
  afterEach(() => {
    vi.useRealTimers();
    for (const [name, descriptor] of [
      ["createObjectURL", originalCreateObjectURL],
      ["revokeObjectURL", originalRevokeObjectURL],
    ] as const) {
      if (descriptor) Object.defineProperty(URL, name, descriptor);
      else Reflect.deleteProperty(URL, name);
    }
  });

  it("opens exact source bytes in an isolated frame and supports a mobile viewport", async () => {
    const fetch = vi.fn().mockResolvedValue(response(content()));
    vi.stubGlobal("fetch", fetch);
    const { wrapper, button } = setup();
    await button("Open preview").trigger("click");
    await flushPromises();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/projects/project/web-source-revisions/source/content",
      {
        credentials: "include",
        headers: { Authorization: "Bearer token" },
      },
    );
    expect(wrapper.get("iframe").attributes("sandbox")).toBe("allow-scripts allow-forms");
    expect(wrapper.get("iframe").attributes("referrerpolicy")).toBe("no-referrer");
    expect(wrapper.get("iframe").attributes("srcdoc")).toContain("<h1>Calculator</h1>");
    expect(wrapper.get("iframe").attributes("srcdoc")).toContain("connect-src 'none'");
    expect(wrapper.get("iframe").attributes("srcdoc")).toContain("form-action 'none'");
    expect(wrapper.get("iframe").attributes("srcdoc")).toContain("frame-src 'none'");
    await button("Mobile").trigger("click");
    expect(button("Mobile").attributes("aria-pressed")).toBe("true");
    expect(wrapper.get("iframe").classes()).toContain("max-w-[375px]");
    wrapper.unmount();
  });

  it.each(["revision_id", "content_hash"])("rejects content with mismatched %s", async (field) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ ...content(), [field]: "different" })),
    );
    const { wrapper, button } = setup();
    await button("Open preview").trigger("click");
    await flushPromises();
    expect(wrapper.find("iframe").exists()).toBe(false);
    expect(wrapper.get('[role="alert"]').text()).toContain("Could not open");
    wrapper.unmount();
  });

  it("ignores late content from a previously selected project", async () => {
    let finish!: (result: Response) => void;
    const first = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const next = revision("next", "second");
    const nextContent = content(next);
    nextContent.files[0]!.base64 = btoa("<h1>Second project</h1>");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValueOnce(first).mockResolvedValueOnce(response(nextContent)),
    );
    const { wrapper, button, store } = setup();
    await button("Open preview").trigger("click");
    store.$patch({ activeProjectId: "second", sourceRevisions: [next] });
    await wrapper.setProps({ projectId: "second" });
    await button("Open preview").trigger("click");
    await flushPromises();
    finish(response(content()));
    await flushPromises();
    expect(wrapper.get("iframe").attributes("srcdoc")).toContain("Second project");
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.attributes("aria-busy")).toBe("false");
    wrapper.unmount();
  });

  it("keeps the request bound to its original project during token refresh", async () => {
    let resume!: () => void;
    authorize.mockImplementationOnce(
      (_api, operation) =>
        new Promise((resolve) => {
          resume = () => resolve(operation("refreshed-token"));
        }),
    );
    const fetch = vi.fn().mockResolvedValue(response(content()));
    vi.stubGlobal("fetch", fetch);
    const { wrapper, button, store } = setup();
    await button("Open preview").trigger("click");
    store.$patch({ activeProjectId: "second", sourceRevisions: [revision("next", "second")] });
    await wrapper.setProps({ projectId: "second" });
    resume();
    await flushPromises();
    expect(fetch.mock.calls[0]?.[0]).toBe(
      "/api/v1/projects/project/web-source-revisions/source/content",
    );
    expect(wrapper.find("iframe").exists()).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("handles binary source assets without mounting a broken text editor", async () => {
    const source = content();
    source.files.push({ path: "image.png", media_type: "image/png", base64: btoa("\x89PNG\xff") });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(source)));
    const { wrapper, button } = setup();
    await button("Edit sources").trigger("click");
    await flushPromises();
    expect(wrapper.findComponent(WebSourceEditor).exists()).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    expect(button("Download project").attributes("disabled")).toBeUndefined();
    wrapper.unmount();
  });

  it("downloads through an attached anchor and keeps the object URL alive until the browser can use it", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("zip")));
    const create = vi.fn().mockReturnValue("blob:source-download");
    const revoke = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: create, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revoke, configurable: true });
    const clicked: { connected: boolean; filename: string; href: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({ connected: this.isConnected, filename: this.download, href: this.href });
    });
    const { wrapper, button } = setup();
    await button("Download project").trigger("click");
    await flushPromises();
    expect(clicked).toEqual([
      { connected: true, filename: "web-source-source.zip", href: "blob:source-download" },
    ]);
    expect(document.querySelector('a[download="web-source-source.zip"]')).toBeNull();
    expect(revoke).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60000);
    expect(revoke).toHaveBeenCalledWith("blob:source-download");
    wrapper.unmount();
  });

  it("saves owner edits as a new revision and preserves the original model revision", async () => {
    const next = revision("owner-edit", "project", 2);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(response(content()))
        .mockResolvedValueOnce(response({ snapshot: next })),
    );
    const { wrapper, button, store } = setup();
    const original = store.sourceRevisions[0];
    await button("Edit sources").trigger("click");
    await flushPromises();
    const editor = wrapper.getComponent(WebSourceEditor);
    await editor.get("textarea").setValue("<h1>Revised calculator</h1>");
    await editor.get("input").setValue("Repair keyboard interaction");
    await editor.get("form").trigger("submit");
    await flushPromises();
    expect(store.sourceRevisions).toEqual([original, next]);
    expect(store.currentSourceRevision?.id).toBe("owner-edit");
    expect(wrapper.findComponent(WebSourceEditor).exists()).toBe(false);
    expect(wrapper.text()).toContain("original model output preserved");
    wrapper.unmount();
  });

  it("has no axe violations", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(content())));
    const { wrapper } = setup();
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
