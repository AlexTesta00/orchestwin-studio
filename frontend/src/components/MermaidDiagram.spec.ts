import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import MermaidDiagram from "./MermaidDiagram.vue";
import type { DiagramLink, DiagramRenderer } from "./mermaidRenderer";
import { expectAccessible } from "@/test/axe";

const SOURCE = 'flowchart LR\n  A["Ospite"] --> B["Lista"]\n';
const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><title>Casi</title></svg>';
const LINKED_SVG = [
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">',
  '<g class="node" id="d-flowchart-REQ001-1"><rect width="80" height="30"></rect>',
  "<text>REQ-001Aggiunta ospite</text></g>",
  '<g class="node" id="d-flowchart-T1-2"><rect width="80" height="30"></rect><text>Ospiti</text></g>',
  '<g class="node" id="d-flowchart-USR009-3"><rect width="80" height="30"></rect>',
  "<text>USR-009Fuori elenco</text></g>",
  "</svg>",
].join("");
const LINKS: DiagramLink[] = [
  { code: "REQ-001", label: "REQ-001 · Aggiunta ospite: leggilo nel testo" },
];

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
    links?: DiagramLink[];
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
      links: options.links,
    },
    attachTo: document.body,
  });
}

function sized(width: number, height: number) {
  const widths = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.dataset.testid === "diagram-canvas" ? width : 0;
  });
  const heights = vi
    .spyOn(HTMLElement.prototype, "clientHeight", "get")
    .mockImplementation(function (this: HTMLElement) {
      return this.dataset.testid === "diagram-canvas" ? height : 0;
    });
  return () => {
    widths.mockRestore();
    heights.mockRestore();
  };
}

function transformOf(wrapper: ReturnType<typeof diagram>): string {
  const inner = wrapper.get('[data-testid="diagram-canvas"]').element.firstElementChild;
  return (inner as HTMLElement).style.transform;
}

async function pointer(
  target: Element,
  type: "pointerdown" | "pointermove" | "pointerup",
  pointerId: number,
  clientX: number,
  clientY: number,
) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX, clientY });
  Object.defineProperty(event, "pointerId", { value: pointerId });
  Object.defineProperty(event, "pointerType", { value: "mouse" });
  target.dispatchEvent(event);
  await flushPromises();
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
    expect(canvas.attributes("tabindex")).toBe("0");
    expect(canvas.attributes("data-links")).toBe("0");
    wrapper.unmount();
  });

  it("shows the source when the diagram cannot be drawn", async () => {
    const wrapper = diagram({ renderer: renderer(new Error("Parse error")) });
    await flushPromises();

    expect(wrapper.get('[data-testid="mermaid-diagram"]').attributes("data-status")).toBe("failed");
    expect(wrapper.get('[data-testid="diagram-error"]').attributes("role")).toBe("alert");
    expect(wrapper.get("details").attributes("open")).toBeDefined();
    expect(wrapper.find('[data-testid="diagram-download-image"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="diagram-zoom-in"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="diagram-canvas"]').isVisible()).toBe(false);
    wrapper.unmount();
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
    wrapper.unmount();
  });

  it("switches between fitting the whole diagram and its actual size", async () => {
    const wrapper = diagram();
    await flushPromises();
    const canvas = wrapper.get('[data-testid="diagram-canvas"]');
    const button = wrapper.get('[data-testid="diagram-size"]');

    expect(canvas.attributes("data-mode")).toBe("fit");
    expect(button.text()).toBe("Dimensione reale");
    await button.trigger("click");

    expect(canvas.attributes("data-mode")).toBe("actual");
    expect(wrapper.get('[data-testid="diagram-zoom-level"]').text()).toBe("100%");
    expect(button.text()).toBe("Adatta");
    await button.trigger("click");

    expect(canvas.attributes("data-mode")).toBe("fit");
    wrapper.unmount();
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

    expect(first.get('[data-testid="diagram-canvas"]').attributes("data-mode")).toBe("actual");
    expect(first.get('[data-testid="diagram-zoom-level"]').text()).toBe("100%");
    expect(first.get('[data-testid="diagram-size"]').text()).toBe("Adatta");
    expect(second.get('[data-testid="diagram-canvas"]').attributes("data-mode")).toBe("fit");
    expect(second.get('[data-testid="diagram-size"]').text()).toBe("Dimensione reale");

    await first.get('[data-testid="diagram-size"]').trigger("click");

    expect(first.get('[data-testid="diagram-canvas"]').attributes("data-mode")).toBe("fit");
    width.mockRestore();
    first.unmount();
    second.unmount();
  });

  it("fits the drawing in the view, zooms with the buttons and the keys and moves with the arrows", async () => {
    const restore = sized(800, 540);
    const wide = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200"></svg>';
    const wrapper = diagram({ renderer: renderer(wide) });
    await flushPromises();
    const canvas = wrapper.get('[data-testid="diagram-canvas"]');
    const level = () => wrapper.get('[data-testid="diagram-zoom-level"]').text();

    expect(level()).toBe("135%");
    expect(transformOf(wrapper)).toBe("translate(130px, 135px) scale(1.35)");
    expect(canvas.element.querySelector("svg")?.getAttribute("width")).toBe("400");

    await wrapper.get('[data-testid="diagram-zoom-in"]').trigger("click");
    expect(level()).toBe("162%");
    expect(canvas.attributes("data-mode")).toBe("custom");
    expect(wrapper.get('[data-testid="diagram-size"]').text()).toBe("Adatta");

    await canvas.trigger("keydown", { key: "+" });
    expect(level()).toBe("194%");
    await canvas.trigger("keydown", { key: "-" });
    expect(level()).toBe("162%");
    await wrapper.get('[data-testid="diagram-zoom-out"]').trigger("click");
    expect(level()).toBe("135%");

    await canvas.trigger("keydown", { key: "0" });
    expect(canvas.attributes("data-mode")).toBe("fit");
    expect(transformOf(wrapper)).toBe("translate(130px, 135px) scale(1.35)");

    await canvas.trigger("keydown", { key: "ArrowRight" });
    await canvas.trigger("keydown", { key: "ArrowDown" });
    expect(transformOf(wrapper)).toBe("translate(82px, 87px) scale(1.35)");
    await canvas.trigger("keydown", { key: "ArrowLeft", shiftKey: true });
    expect(transformOf(wrapper)).toBe("translate(242px, 87px) scale(1.35)");
    expect(canvas.attributes("data-mode")).toBe("custom");
    restore();
    wrapper.unmount();
  });

  it("zooms with the wheel only while Ctrl is held and drags the view with the pointer", async () => {
    const restore = sized(800, 540);
    const wide = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200"></svg>';
    const wrapper = diagram({ renderer: renderer(wide) });
    await flushPromises();
    const canvas = wrapper.get('[data-testid="diagram-canvas"]');
    const level = () => wrapper.get('[data-testid="diagram-zoom-level"]').text();

    const plain = new WheelEvent("wheel", { deltaY: -100, cancelable: true });
    canvas.element.dispatchEvent(plain);
    await flushPromises();
    expect(plain.defaultPrevented).toBe(false);
    expect(level()).toBe("135%");

    const zoom = new WheelEvent("wheel", { deltaY: -100, ctrlKey: true, cancelable: true });
    canvas.element.dispatchEvent(zoom);
    await flushPromises();
    expect(zoom.defaultPrevented).toBe(true);
    expect(level()).toBe("165%");

    await canvas.trigger("keydown", { key: "0" });
    await pointer(canvas.element, "pointerdown", 1, 10, 10);
    await pointer(canvas.element, "pointermove", 1, 12, 11);
    expect(transformOf(wrapper)).toBe("translate(130px, 135px) scale(1.35)");
    await pointer(canvas.element, "pointermove", 1, 60, 30);
    await pointer(canvas.element, "pointerup", 1, 60, 30);
    expect(transformOf(wrapper)).toBe("translate(180px, 155px) scale(1.35)");
    expect(canvas.attributes("data-mode")).toBe("custom");
    restore();
    wrapper.unmount();
  });

  it("turns the nodes with a known code into buttons that lead to the item in the text", async () => {
    const wrapper = diagram({ renderer: renderer(LINKED_SVG), links: LINKS });
    await flushPromises();
    const canvas = wrapper.get('[data-testid="diagram-canvas"]');
    const nodes = canvas.findAll("g.node");

    expect(canvas.attributes("role")).toBe("group");
    expect(canvas.attributes("data-links")).toBe("1");
    expect(nodes[0]!.attributes()).toMatchObject({
      "data-diagram-node": "REQ-001",
      tabindex: "0",
      role: "button",
      "aria-label": "REQ-001 · Aggiunta ospite: leggilo nel testo",
    });
    expect(nodes[1]!.attributes("tabindex")).toBeUndefined();
    expect(nodes[2]!.attributes("data-diagram-node")).toBeUndefined();
    expect(wrapper.text()).toContain("Tocca un elemento con un codice per leggerlo nel testo");

    await nodes[0]!.trigger("click");
    await nodes[0]!.trigger("keydown", { key: "Enter" });
    await nodes[0]!.trigger("keydown", { key: " " });
    await nodes[1]!.trigger("click");
    expect(wrapper.emitted("select-node")).toEqual([["REQ-001"], ["REQ-001"], ["REQ-001"]]);

    await pointer(nodes[0]!.element, "pointerdown", 2, 0, 0);
    await pointer(nodes[0]!.element, "pointermove", 2, 40, 0);
    await pointer(nodes[0]!.element, "pointerup", 2, 40, 0);
    await nodes[0]!.trigger("click");
    expect(wrapper.emitted("select-node")).toHaveLength(3);
    await nodes[0]!.trigger("click");
    expect(wrapper.emitted("select-node")).toHaveLength(4);

    await wrapper.setProps({ links: [] });
    expect(canvas.attributes("role")).toBe("img");
    expect(canvas.find("[data-diagram-node]").exists()).toBe(false);
    wrapper.unmount();
  });

  it("has no axe violations when its nodes can be chosen", async () => {
    const wrapper = diagram({ renderer: renderer(LINKED_SVG), links: LINKS });
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("downloads the source and the drawn image on its dark background, with the name of the diagram", async () => {
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
      {
        name: "use-cases.svg",
        type: "image/svg+xml;charset=utf-8",
        text: SVG.replace("<svg", '<svg style="background-color: #0c0e0f;"'),
      },
    ]);
    wrapper.unmount();
  });

  it("keeps the style of the drawing when it adds the background to the downloaded image", async () => {
    const styled =
      '<svg id="d" style="max-width: 438px;" viewBox="0 0 438 546"><g class="node"></g></svg>';
    const saved: string[] = [];
    const saveFile = vi.fn((blob: Blob) => {
      void blob.text().then((text) => saved.push(text));
    });
    const wrapper = diagram({ renderer: renderer(styled), saveFile });
    await flushPromises();

    await wrapper.get('[data-testid="diagram-download-image"]').trigger("click");
    await flushPromises();

    expect(saved).toEqual([
      '<svg id="d" style="max-width: 438px; background-color: #0c0e0f;" viewBox="0 0 438 546"><g class="node"></g></svg>',
    ]);
    wrapper.unmount();
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
    expect(wrapper.get('[data-testid="diagram-zoom-in"]').attributes("aria-label")).toBe("Zoom in");
    expect(wrapper.get("summary").text()).toBe("Mermaid source");
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
