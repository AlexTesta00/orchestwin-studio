import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DIAGRAM_BACKGROUND,
  DIAGRAM_SANDBOX_ATTRIBUTE,
  DIAGRAM_TOKENS,
  MERMAID_CONFIGURATION,
  createMermaidRenderer,
} from "./mermaidRenderer";
import styles from "../styles/tailwind.css?raw";

type Draw = (id: string, source: string, container?: Element) => Promise<{ svg: string }>;

function engine() {
  return {
    initialize: vi.fn(),
    render: vi.fn<Draw>((id, source) =>
      Promise.resolve({ svg: `<svg id="${id}">${source}</svg>` }),
    ),
  };
}

describe("mermaidRenderer", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(() => {
    Reflect.deleteProperty(document, "fonts");
  });

  it("loads and configures the library once, then draws every diagram", async () => {
    const library = engine();
    const loader = vi.fn(() => Promise.resolve({ default: library }));
    const renderer = createMermaidRenderer(loader);

    const first = await renderer.render("a", "flowchart LR");
    const second = await renderer.render("b", "stateDiagram-v2");

    expect(first).toBe('<svg id="a">flowchart LR</svg>');
    expect(second).toBe('<svg id="b">stateDiagram-v2</svg>');
    expect(loader).toHaveBeenCalledTimes(1);
    expect(library.initialize).toHaveBeenCalledTimes(1);
    expect(library.initialize).toHaveBeenCalledWith({ ...MERMAID_CONFIGURATION });
  });

  it("measures every diagram inside one hidden sandbox of the page", async () => {
    const library = engine();
    const renderer = createMermaidRenderer(() => Promise.resolve({ default: library }));

    await renderer.render("a", "flowchart LR");
    await renderer.render("b", "stateDiagram-v2");

    const sandboxes = document.querySelectorAll(`[${DIAGRAM_SANDBOX_ATTRIBUTE}]`);
    expect(sandboxes).toHaveLength(1);
    expect(sandboxes[0]?.parentElement).toBe(document.body);
    expect(sandboxes[0]?.getAttribute("aria-hidden")).toBe("true");
    expect(library.render.mock.calls.map((call) => call[2])).toEqual([sandboxes[0], sandboxes[0]]);
  });

  it("keeps the sandbox out of the reduced motion rule that delays every style change", () => {
    const sandbox = `[${DIAGRAM_SANDBOX_ATTRIBUTE}]`;
    const rule = styles.slice(styles.lastIndexOf("@media (prefers-reduced-motion: reduce)"));
    const hidden = styles.slice(styles.indexOf(`${sandbox} {`));

    expect(rule).toContain(`*:not(${sandbox} *)`);
    expect(rule).toContain("transition-duration: 0.01ms !important");
    expect(hidden.slice(0, hidden.indexOf("}"))).toContain("visibility: hidden;");
  });

  it("never runs scripts of a diagram and never draws on page load", () => {
    expect(MERMAID_CONFIGURATION.securityLevel).toBe("strict");
    expect(MERMAID_CONFIGURATION.startOnLoad).toBe(false);
    expect(MERMAID_CONFIGURATION.theme).toBe("base");
  });

  it("writes in Geist with the petrol colours of the tokens, readable on the dark canvas", () => {
    const theme = MERMAID_CONFIGURATION.themeVariables;

    expect(MERMAID_CONFIGURATION.fontFamily.startsWith('"Geist"')).toBe(true);
    expect(theme.fontFamily).toBe(MERMAID_CONFIGURATION.fontFamily);
    expect(MERMAID_CONFIGURATION.usecase.actorFontFamily).toBe(MERMAID_CONFIGURATION.fontFamily);
    expect(theme.darkMode).toBe(true);
    expect(theme.background).toBe(DIAGRAM_TOKENS["night-deep"]);
    expect(DIAGRAM_BACKGROUND).toBe(DIAGRAM_TOKENS["night-deep"]);
    expect(theme.primaryBorderColor).toBe(DIAGRAM_TOKENS["petrol-on-night"]);
    expect(theme.nodeBorder).toBe(DIAGRAM_TOKENS["petrol-on-night"]);
    expect(theme.lineColor).toBe(DIAGRAM_TOKENS["petrol-on-night-2"]);
    expect(theme.primaryTextColor).toBe(DIAGRAM_TOKENS["on-night"]);
    expect(theme.requirementTextColor).toBe(DIAGRAM_TOKENS["on-night"]);
    for (const [name, value] of Object.entries(DIAGRAM_TOKENS)) {
      expect(styles).toContain(`--color-${name}: ${value};`);
    }
  });

  it("waits for the font of the diagrams before measuring them", async () => {
    const order: string[] = [];
    const load = vi.fn((font: string) => {
      order.push(`font ${font}`);
      return Promise.resolve([]);
    });
    Object.defineProperty(document, "fonts", { configurable: true, value: { load } });
    const library = {
      initialize: vi.fn(),
      render: vi.fn<Draw>(async (id) => {
        order.push(`draw ${id}`);
        return { svg: id };
      }),
    };
    const renderer = createMermaidRenderer(() => Promise.resolve({ default: library }));

    await renderer.render("a", "flowchart LR");

    expect(order).toEqual(['font 15px "Geist"', 'font bold 15px "Geist"', "draw a"]);
  });

  it("draws one diagram at a time in the order of the requests", async () => {
    const order: string[] = [];
    const library = {
      initialize: vi.fn(),
      render: vi.fn<Draw>(async (id) => {
        order.push(`start ${id}`);
        await Promise.resolve();
        order.push(`end ${id}`);
        return { svg: id };
      }),
    };
    const renderer = createMermaidRenderer(() => Promise.resolve({ default: library }));

    await Promise.all([renderer.render("a", "x"), renderer.render("b", "y")]);

    expect(order).toEqual(["start a", "end a", "start b", "end b"]);
  });

  it("keeps drawing after a diagram fails", async () => {
    const library = engine();
    library.render.mockRejectedValueOnce(new Error("Parse error"));
    const renderer = createMermaidRenderer(() => Promise.resolve({ default: library }));

    await expect(renderer.render("a", "broken")).rejects.toThrow("Parse error");
    await expect(renderer.render("b", "flowchart LR")).resolves.toContain("flowchart LR");
  });

  it("tries to load the library again after a failed load", async () => {
    const library = engine();
    const loader = vi
      .fn<() => Promise<{ default: typeof library }>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ default: library });
    const renderer = createMermaidRenderer(loader);

    await expect(renderer.render("a", "flowchart LR")).rejects.toThrow("offline");
    await expect(renderer.render("b", "flowchart LR")).resolves.toContain("svg");
    expect(loader).toHaveBeenCalledTimes(2);
  });
});
