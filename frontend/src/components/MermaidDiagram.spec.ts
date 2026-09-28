import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import MermaidDiagram from "./MermaidDiagram.vue";
import type { DiagramRenderer } from "./mermaidRenderer";
import { expectAccessible } from "@/test/axe";

const SOURCE = 'flowchart LR\n  A["Ospite"] --> B["Lista"]\n';
const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><title>Casi</title></svg>';

function renderer(result: string | Error = SVG) {
  const render = vi.fn<DiagramRenderer["render"]>(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return { render };
}

function diagram(
  options: {
    renderer?: DiagramRenderer;
    saveFile?: (blob: Blob, fileName: string) => void;
  } = {},
) {
  return mount(MermaidDiagram, {
    props: {
      source: SOURCE,
      title: "Casi d'uso",
      description: "2 attori e 5 casi d'uso.",
      fileName: "requirements/diagrams/use-cases.mmd",
      locale: "it",
      renderer: options.renderer ?? renderer(),
      saveFile: options.saveFile,
    },
  });
}

describe("MermaidDiagram", () => {
  it("draws the source and describes the diagram in words", async () => {
    const engine = renderer();
    const wrapper = diagram({ renderer: engine });

    expect(wrapper.get('[data-testid="mermaid-diagram"]').attributes("data-status")).toBe(
      "loading",
    );
    expect(wrapper.text()).toContain("Disegno il diagramma");
    await flushPromises();

    const canvas = wrapper.get('[data-testid="diagram-canvas"]');
    expect(wrapper.get('[data-testid="mermaid-diagram"]').attributes("data-status")).toBe("ready");
    expect(engine.render).toHaveBeenCalledTimes(1);
    expect(engine.render.mock.calls[0]![0]).toMatch(/^diagram-[\w-]+-1$/);
    expect(engine.render.mock.calls[0]![1]).toBe(SOURCE);
    expect(canvas.element.querySelector("svg")).not.toBeNull();
    expect(canvas.attributes("role")).toBe("img");
    expect(canvas.attributes("aria-label")).toBe("Casi d'uso. 2 attori e 5 casi d'uso.");
    expect(wrapper.get("figcaption").text()).toContain("Casi d'uso");
    expect(wrapper.get('[data-testid="diagram-description"]').text()).toBe(
      "2 attori e 5 casi d'uso.",
    );
    expect(wrapper.get('[data-testid="diagram-source"]').text()).toBe(SOURCE.trim());
  });

  it("shows the source when the diagram cannot be drawn", async () => {
    const wrapper = diagram({ renderer: renderer(new Error("Parse error")) });
    await flushPromises();

    expect(wrapper.get('[data-testid="mermaid-diagram"]').attributes("data-status")).toBe("failed");
    expect(wrapper.get('[data-testid="diagram-error"]').attributes("role")).toBe("alert");
    expect(wrapper.get("details").attributes("open")).toBeDefined();
    expect(wrapper.find('[data-testid="diagram-download-image"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="diagram-canvas"]').isVisible()).toBe(false);
  });

  it("draws again when the source changes and ignores the older drawing", async () => {
    let release: (svg: string) => void = () => undefined;
    const slow = new Promise<string>((resolve) => {
      release = resolve;
    });
    const render = vi
      .fn<DiagramRenderer["render"]>()
      .mockReturnValueOnce(slow)
      .mockResolvedValueOnce('<svg data-version="new"></svg>');
    const wrapper = diagram({ renderer: { render } });

    await wrapper.setProps({ source: "stateDiagram-v2\n" });
    await flushPromises();
    release('<svg data-version="old"></svg>');
    await flushPromises();

    expect(render).toHaveBeenCalledTimes(2);
    expect(render.mock.calls[1]![1]).toBe("stateDiagram-v2\n");
    expect(
      wrapper.get('[data-testid="diagram-canvas"]').element.querySelector("svg")?.dataset.version,
    ).toBe("new");
  });

  it("switches between the width of the page and the actual size", async () => {
    const wrapper = diagram();
    await flushPromises();
    const canvas = wrapper.get('[data-testid="diagram-canvas"]');
    const button = wrapper.get('[data-testid="diagram-size"]');

    expect(canvas.classes()).toContain("[&>svg]:max-w-full");
    expect(button.text()).toBe("Dimensione reale");
    await button.trigger("click");

    expect(canvas.classes()).toContain("[&>svg]:max-w-none");
    expect(button.text()).toBe("Adatta alla larghezza");
  });

  it("opens a diagram much wider than the page at its actual size so that it stays readable", async () => {
    const width = vi
      .spyOn(HTMLElement.prototype, "clientWidth", "get")
      .mockImplementation(function (this: HTMLElement) {
        return this.dataset.testid === "diagram-canvas" ? 0 : 700;
      });
    const wide = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="4 4 2620.5 427"></svg>';
    const narrow = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 -8 1050 546"></svg>';
    const first = diagram({ renderer: renderer(wide) });
    const second = diagram({ renderer: renderer(narrow) });
    await flushPromises();

    expect(first.get('[data-testid="diagram-canvas"]').classes()).toContain("[&>svg]:max-w-none");
    expect(first.get('[data-testid="diagram-size"]').text()).toBe("Adatta alla larghezza");
    expect(second.get('[data-testid="diagram-canvas"]').classes()).toContain("[&>svg]:max-w-full");
    expect(second.get('[data-testid="diagram-size"]').text()).toBe("Dimensione reale");

    await first.get('[data-testid="diagram-size"]').trigger("click");

    expect(first.get('[data-testid="diagram-canvas"]').classes()).toContain("[&>svg]:max-w-full");
    width.mockRestore();
  });

  it("downloads the source and the drawn image with the name of the diagram", async () => {
    const saved: { name: string; type: string; text: string }[] = [];
    const saveFile = vi.fn((blob: Blob, name: string) => {
      void blob.text().then((text) => saved.push({ name, type: blob.type, text }));
    });
    const wrapper = diagram({ saveFile });
    await flushPromises();

    await wrapper.get('[data-testid="diagram-download-source"]').trigger("click");
    await wrapper.get('[data-testid="diagram-download-image"]').trigger("click");
    await flushPromises();

    expect(saved).toEqual([
      { name: "use-cases.mmd", type: "text/plain;charset=utf-8", text: SOURCE },
      { name: "use-cases.svg", type: "image/svg+xml;charset=utf-8", text: SVG },
    ]);
  });

  it("speaks English by default and has no axe violations", async () => {
    const wrapper = mount(MermaidDiagram, {
      props: {
        source: SOURCE,
        title: "Use cases",
        description: "2 actors and 5 use cases.",
        fileName: "requirements/diagrams/use-cases.mmd",
        renderer: renderer(),
      },
      attachTo: document.body,
    });
    await flushPromises();

    expect(wrapper.get('[data-testid="diagram-size"]').text()).toBe("Actual size");
    expect(wrapper.get("summary").text()).toBe("Diagram source (Mermaid)");
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
