import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { expectAccessible } from "@/test/axe";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import source from "./GeneratedMockupFrame.vue?raw";

const HTML = [
  "<!doctype html><html lang='it'><head><title>Prestiti</title></head><body>",
  "<section class='ot-screen' id='SCR-001' data-entry><h1 class='mockup-marker'>Registro</h1>",
  "<a href='#SCR-002'>Nuovo prestito</a></section>",
  "<section class='ot-screen' id='SCR-002'><h1>Nuovo prestito</h1></section>",
  "</body></html>",
].join("");

class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  readonly callback: ResizeObserverCallback;
  observed: Element[] = [];
  disconnected = false;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    FakeResizeObserver.instances.push(this);
  }

  observe(element: Element): void {
    this.observed.push(element);
  }

  unobserve(): void {}

  disconnect(): void {
    this.disconnected = true;
  }

  fire(): void {
    this.callback([], this as unknown as ResizeObserver);
  }
}

function boxSize(width: number, height: number): void {
  vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(width);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(height);
}

function frameOf(wrapper: ReturnType<typeof mount>) {
  return wrapper.get<HTMLIFrameElement>("iframe").element;
}

afterEach(() => {
  FakeResizeObserver.instances = [];
  document.body.innerHTML = "";
});

describe("generated mockup frame", () => {
  it("shows the document only inside one iframe with an empty sandbox", () => {
    const wrapper = mount(GeneratedMockupFrame, {
      props: { html: HTML, title: "Mockup navigabile: Registro dei prestiti" },
      attachTo: document.body,
    });
    const frames = wrapper.findAll("iframe");
    expect(frames).toHaveLength(1);
    const frame = frameOf(wrapper);
    expect(frame.hasAttribute("sandbox")).toBe(true);
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("srcdoc")).toBe(HTML);
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("loading")).toBe("lazy");
    expect(frame.getAttribute("title")).toBe("Mockup navigabile: Registro dei prestiti");
    for (const attribute of ["src", "allow", "allowfullscreen", "name", "csp"]) {
      expect(frame.hasAttribute(attribute)).toBe(false);
    }
    expect(document.querySelector(".mockup-marker")).toBeNull();
    expect(wrapper.element.querySelector(".mockup-marker")).toBeNull();
    expect(wrapper.element.querySelector("section, a, script, form")).toBeNull();
    expect(wrapper.element.children).toHaveLength(1);
    wrapper.unmount();
  });

  it("points the links between the screens at the document itself and changes nothing else", () => {
    const linked = [
      '<nav><a href="#SCR-001" aria-current="page" data-elm="ELM-003">Registro</a>',
      '<a class="btn" role="button" href="#SCR-002" data-elm="ELM-004">Nuovo prestito</a></nav>',
      '<p>Scrivi href="#SCR-003" per collegare</p>',
      '<abbr title="x" href="#SCR-004">x</abbr><a href="#dettagli">Dettagli</a>',
    ].join("");
    const wrapper = mount(GeneratedMockupFrame, { props: { html: linked, title: "Mockup" } });
    expect(frameOf(wrapper).getAttribute("srcdoc")).toBe(
      [
        '<nav><a href="about:srcdoc#SCR-001" aria-current="page" data-elm="ELM-003">Registro</a>',
        '<a class="btn" role="button" href="about:srcdoc#SCR-002" data-elm="ELM-004">Nuovo prestito</a></nav>',
        '<p>Scrivi href="#SCR-003" per collegare</p>',
        '<abbr title="x" href="#SCR-004">x</abbr><a href="#dettagli">Dettagli</a>',
      ].join(""),
    );
  });

  it("never inserts raw markup and never grants a permission in its source", () => {
    expect(source).not.toMatch(/v-html/);
    expect(source).not.toMatch(/innerHTML/);
    expect(source).not.toMatch(/allow-/);
    expect(source).not.toMatch(/\ballow=/);
    expect(source.match(/sandbox=""/g)).toHaveLength(1);
    expect(source.match(/<iframe/g)).toHaveLength(1);
  });

  it("is interactive by default, reachable with the keyboard and visible to assistive technology", () => {
    const wrapper = mount(GeneratedMockupFrame, { props: { html: HTML, title: "Mockup" } });
    const root = wrapper.get("[data-testid='generated-mockup-frame']");
    expect(root.attributes("data-interactive")).toBe("true");
    expect(root.attributes("inert")).toBeUndefined();
    expect(root.attributes("aria-hidden")).toBeUndefined();
    expect(frameOf(wrapper).hasAttribute("tabindex")).toBe(false);
    expect(root.attributes("data-width")).toBe("desktop");
  });

  it("makes a thumbnail inert, hidden, out of the tab order and scaled in a box of fixed ratio", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    boxSize(320, 200);
    const wrapper = mount(GeneratedMockupFrame, {
      props: { html: HTML, title: "Anteprima di DES-001", interactive: false },
    });
    await flushPromises();
    const root = wrapper.get("[data-testid='generated-mockup-frame']");
    expect(root.element.hasAttribute("inert")).toBe(true);
    expect(root.attributes("inert")).not.toBe("false");
    expect(root.attributes("aria-hidden")).toBe("true");
    expect(root.classes()).toEqual(
      expect.arrayContaining(["aspect-[16/10]", "pointer-events-none"]),
    );
    const frame = frameOf(wrapper);
    expect(frame.getAttribute("tabindex")).toBe("-1");
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.style.width).toBe("1280px");
    expect(frame.style.height).toBe("800px");
    expect(frame.style.transform).toBe("scale(0.25)");
    await wrapper.setProps({ scale: 0.5 });
    expect(frameOf(wrapper).style.transform).toBe("scale(0.5)");
    expect(frameOf(wrapper).style.height).toBe("400px");
    await wrapper.setProps({ scale: undefined, width: "phone" });
    expect(root.classes()).toContain("aspect-[390/844]");
    expect(frameOf(wrapper).style.width).toBe("390px");
  });

  it("fits a desktop mockup to the width that is available and never enlarges it", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    boxSize(900, 600);
    const wrapper = mount(GeneratedMockupFrame, { props: { html: HTML, title: "Mockup" } });
    await flushPromises();
    let frame = frameOf(wrapper);
    expect(frame.style.width).toBe("1024px");
    expect(frame.style.transform).toBe(`scale(${900 / 1024})`);
    expect(frame.style.height).toBe(`${Math.ceil(600 / (900 / 1024))}px`);
    expect(frame.style.left).toBe("0px");
    expect(frame.style.top).toBe("0px");
    expect(frame.classList).not.toContain("rounded-[18px]");
    boxSize(1200, 700);
    FakeResizeObserver.instances[0]?.fire();
    await flushPromises();
    frame = frameOf(wrapper);
    expect(frame.style.width).toBe("1200px");
    expect(frame.style.transform).toBe("");
    expect(frame.style.height).toBe("700px");
  });

  it("centres a phone or a tablet on the stage with a margin and keeps an explicit width", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    boxSize(1000, 700);
    const wrapper = mount(GeneratedMockupFrame, {
      props: { html: HTML, title: "Mockup", width: "phone" },
    });
    await flushPromises();
    const frame = frameOf(wrapper);
    expect(frame.style.width).toBe("390px");
    expect(frame.style.left).toBe("305px");
    expect(frame.style.top).toBe("16px");
    expect(frame.style.height).toBe("668px");
    expect(frame.classList).toContain("rounded-[18px]");
    await wrapper.setProps({ width: "tablet" });
    expect(frameOf(wrapper).style.width).toBe("768px");
    expect(frameOf(wrapper).style.left).toBe("116px");
    await wrapper.setProps({ width: 2000 });
    expect(frameOf(wrapper).style.width).toBe("2000px");
    expect(frameOf(wrapper).style.transform).toBe("scale(0.5)");
    expect(frameOf(wrapper).style.height).toBe(`${(700 - 32) * 2}px`);
    expect(wrapper.get("[data-testid='generated-mockup-frame']").attributes("data-width")).toBe(
      "2000",
    );
  });

  it("observes its own box and stops when it is removed", () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const wrapper = mount(GeneratedMockupFrame, { props: { html: HTML, title: "Mockup" } });
    const observer = FakeResizeObserver.instances[0];
    expect(observer?.observed).toEqual([wrapper.element]);
    wrapper.unmount();
    expect(observer?.disconnected).toBe(true);
  });

  it("loads the new document when the html changes", async () => {
    const wrapper = mount(GeneratedMockupFrame, { props: { html: HTML, title: "Mockup" } });
    const next = HTML.replace("Registro", "Registro aggiornato");
    await wrapper.setProps({ html: next });
    expect(frameOf(wrapper).getAttribute("srcdoc")).toBe(next);
  });

  it("has no axe violations as a frame and as a thumbnail", async () => {
    await expectAccessible(
      mount(GeneratedMockupFrame, { props: { html: HTML, title: "Mockup navigabile" } }).element,
      { iframes: false },
    );
    await expectAccessible(
      mount(GeneratedMockupFrame, {
        props: { html: HTML, title: "Anteprima", interactive: false },
      }).element,
      { iframes: false },
    );
  });
});
