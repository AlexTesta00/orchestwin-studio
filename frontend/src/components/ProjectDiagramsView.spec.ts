import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDiagramsView from "./ProjectDiagramsView.vue";
import type { DiagramRenderer } from "./mermaidRenderer";
import { DiagramsApiError, type DiagramsApi } from "../api/diagrams";
import type { AuthorizedRequest } from "../stores/diagrams";
import type { DiagramLocale, DiagramPayload, ProjectDiagramsPayload } from "../types/diagrams";
import { expectAccessible } from "@/test/axe";

const PROJECT_ID = "00000000-0000-4000-8000-000000000101";
const VERSION = {
  version_id: "00000000-0000-4000-8000-000000000201",
  version_number: 2,
  content_hash: "a".repeat(64),
};

function diagram(key: string, title: string, stage: "requirements" | "design"): DiagramPayload {
  return {
    key,
    stage,
    kind: stage === "requirements" ? "USE_CASES" : "WORKFLOWS",
    subject: stage === "design" ? "DES-001" : null,
    title,
    description: `Descrizione di ${title}.`,
    path: `${stage}/diagrams/${key.split("/")[1]}.mmd`,
    source: `flowchart LR\n  A["${title}"]\n`,
  };
}

function payload(locale: DiagramLocale, diagrams: DiagramPayload[]): ProjectDiagramsPayload {
  return {
    project_id: PROJECT_ID,
    locale,
    mermaid_version: "12.0.0",
    system_name: "Lista ospiti workshop",
    requirements: VERSION,
    design: null,
    diagrams,
  };
}

const DIAGRAMS = [
  diagram("requirements/use-cases", "Casi d'uso", "requirements"),
  diagram("requirements/traceability", "Tracciabilità dei requisiti", "requirements"),
  diagram("design/des-001-workflows", "Flussi di DES-001", "design"),
];

const authorize: AuthorizedRequest = (operation) => operation("token");

function renderer(): DiagramRenderer & { render: ReturnType<typeof vi.fn> } {
  return { render: vi.fn((id: string) => Promise.resolve(`<svg id="${id}"></svg>`)) };
}

function api(current: DiagramsApi["current"]): DiagramsApi {
  return { current };
}

function view(
  options: {
    stage?: "requirements" | "design";
    locale?: DiagramLocale;
    api?: DiagramsApi;
    renderer?: DiagramRenderer;
    refreshKey?: string | number | null;
  } = {},
) {
  return mount(ProjectDiagramsView, {
    props: {
      projectId: PROJECT_ID,
      stage: options.stage ?? "requirements",
      locale: options.locale ?? "it",
      refreshKey: options.refreshKey ?? null,
      authorize,
      api:
        options.api ?? api(vi.fn((_project, locale) => Promise.resolve(payload(locale, DIAGRAMS)))),
      renderer: options.renderer ?? renderer(),
    },
    attachTo: document.body,
  });
}

describe("ProjectDiagramsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
  });

  it("loads the diagrams of the project and shows the ones of its stage", async () => {
    const current = vi.fn<DiagramsApi["current"]>((_project, locale) =>
      Promise.resolve(payload(locale, DIAGRAMS)),
    );
    const engine = renderer();
    const wrapper = view({ api: api(current), renderer: engine });

    expect(wrapper.text()).toContain("Preparo i diagrammi");
    await flushPromises();

    expect(current).toHaveBeenCalledWith(PROJECT_ID, "it", "token");
    expect(wrapper.get('[data-testid="project-diagrams"]').attributes("data-stage")).toBe(
      "requirements",
    );
    expect(wrapper.get('[data-testid="diagram-choice"]').attributes("aria-label")).toBe(
      "Scegli un diagramma",
    );
    expect(
      wrapper.findAll('[data-testid="diagram-choice"] button').map((option) => option.text()),
    ).toEqual(["Casi d'uso", "Tracciabilità dei requisiti"]);
    expect(wrapper.get("figcaption").text()).toContain("Casi d'uso");
    expect(engine.render.mock.calls[0]![1]).toBe(DIAGRAMS[0]!.source);
    expect(wrapper.get('[data-testid="diagrams-note"]').text()).toContain("senza usare un modello");
    wrapper.unmount();
  });

  it("switches diagram when another one is chosen", async () => {
    const engine = renderer();
    const wrapper = view({ renderer: engine });
    await flushPromises();
    const option = '[data-testid="diagram-option-requirements/traceability"]';
    const chosen = wrapper.get(option).element;

    await wrapper.get(option).trigger("click");
    await flushPromises();

    const options = wrapper.findAll('[data-testid="diagram-choice"] button');
    expect(options.map((item) => item.attributes("aria-pressed"))).toEqual(["false", "true"]);
    expect(wrapper.get(option).element).toBe(chosen);
    expect(wrapper.get("figcaption").text()).toContain("Tracciabilità dei requisiti");
    expect(engine.render.mock.calls.at(-1)![1]).toBe(DIAGRAMS[1]!.source);
    wrapper.unmount();
  });

  it("shows a single diagram without the choice and with its title", async () => {
    const wrapper = view({ stage: "design" });
    await flushPromises();

    expect(wrapper.find('[data-testid="diagram-choice"]').exists()).toBe(false);
    expect(wrapper.get("figcaption").text()).toContain("Flussi di DES-001");
    expect(wrapper.get('[data-testid="mermaid-diagram"] p[aria-hidden="true"]').text()).toBe(
      "Flussi di DES-001",
    );
    wrapper.unmount();
  });

  it("offers the items it can open and reports the one that the person chooses", async () => {
    const linked: DiagramRenderer = {
      render: vi.fn(() =>
        Promise.resolve(
          '<svg viewBox="0 0 100 40"><g class="node"><text>USR-001 Vedere la lista</text></g></svg>',
        ),
      ),
    };
    const wrapper = mount(ProjectDiagramsView, {
      props: {
        projectId: PROJECT_ID,
        stage: "requirements",
        locale: "it",
        authorize,
        api: api(vi.fn((_project, locale) => Promise.resolve(payload(locale, DIAGRAMS)))),
        renderer: linked,
        links: [{ code: "USR-001", label: "USR-001: leggila nel testo" }],
      },
      attachTo: document.body,
    });
    await flushPromises();

    const node = wrapper.get('[data-diagram-node="USR-001"]');
    expect(node.attributes("aria-label")).toBe("USR-001: leggila nel testo");
    await node.trigger("click");

    expect(wrapper.emitted("select-node")).toEqual([["USR-001"]]);
    wrapper.unmount();
  });

  it("explains what is missing when the stage has no diagrams yet", async () => {
    const missing = api(
      vi.fn(() =>
        Promise.reject(
          new DiagramsApiError("The diagrams request failed", {
            status: 404,
            code: "DIAGRAMS_NOT_FOUND",
            payload: null,
          }),
        ),
      ),
    );
    const requirements = view({ api: missing });
    await flushPromises();

    expect(requirements.get('[data-testid="diagrams-empty"]').text()).toBe(
      "I diagrammi compaiono qui appena esistono i requisiti.",
    );
    expect(requirements.find('[data-testid="diagrams-error"]').exists()).toBe(false);
    requirements.unmount();
  });

  it("explains that the design diagrams need the design alternatives", async () => {
    const design = view({
      stage: "design",
      api: api(vi.fn((_project, locale) => Promise.resolve(payload(locale, DIAGRAMS.slice(0, 2))))),
    });
    await flushPromises();

    expect(design.get('[data-testid="diagrams-empty"]').text()).toBe(
      "I diagrammi compaiono qui appena esistono le alternative di design.",
    );
    design.unmount();
  });

  it("reports a failure and loads again on request", async () => {
    const current = vi
      .fn<DiagramsApi["current"]>()
      .mockRejectedValueOnce(
        new DiagramsApiError("The diagrams request failed", {
          status: 500,
          code: null,
          payload: null,
        }),
      )
      .mockImplementation((_project, locale) => Promise.resolve(payload(locale, DIAGRAMS)));
    const wrapper = view({ api: api(current) });
    await flushPromises();

    expect(wrapper.get('[data-testid="diagrams-error"]').attributes("role")).toBe("alert");
    await wrapper.get('[data-testid="diagrams-retry"]').trigger("click");
    await flushPromises();

    expect(current).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="diagrams-error"]').exists()).toBe(false);
    expect(wrapper.get("figcaption").text()).toContain("Casi d'uso");
    wrapper.unmount();
  });

  it("loads again when the language or the content changes", async () => {
    const current = vi.fn<DiagramsApi["current"]>((_project, locale) =>
      Promise.resolve(
        payload(locale, [
          diagram(
            "requirements/use-cases",
            locale === "it" ? "Casi d'uso" : "Use cases",
            "requirements",
          ),
        ]),
      ),
    );
    const wrapper = view({ api: api(current), refreshKey: 1 });
    await flushPromises();

    await wrapper.setProps({ locale: "en" });
    await flushPromises();
    await wrapper.setProps({ refreshKey: 2 });
    await flushPromises();

    expect(current.mock.calls.map((call) => call[1])).toEqual(["it", "en", "en"]);
    expect(wrapper.get("figcaption").text()).toContain("Use cases");
    expect(wrapper.get('[data-testid="diagrams-note"]').text()).toContain("without a model");
    wrapper.unmount();
  });

  it("has no axe violations", async () => {
    const wrapper = view();
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
