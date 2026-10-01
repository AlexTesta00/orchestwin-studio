import { createPinia } from "pinia";
import { mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { useAuthStore } from "@/stores/auth";
import HomeView from "./HomeView.vue";
import { expectAccessible } from "@/test/axe";

class FakeObserver {
  static instances: FakeObserver[] = [];
  readonly observed = new Set<Element>();
  readonly callback: IntersectionObserverCallback;
  readonly options: IntersectionObserverInit | undefined;
  disconnected = false;

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.callback = callback;
    this.options = options;
    FakeObserver.instances.push(this);
  }

  observe(element: Element): void {
    this.observed.add(element);
  }

  unobserve(element: Element): void {
    this.observed.delete(element);
  }

  disconnect(): void {
    this.disconnected = true;
    this.observed.clear();
  }

  enter(elements: Element[]): void {
    this.callback(
      elements.map((target) => ({ target, isIntersecting: true }) as IntersectionObserverEntry),
      this as unknown as IntersectionObserver,
    );
  }
}

const frames: FrameRequestCallback[] = [];

function flushFrames(): void {
  for (const callback of frames.splice(0)) callback(0);
}

function allowMotion(reduce: boolean): void {
  FakeObserver.instances = [];
  frames.length = 0;
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduce, media: query }));
  vi.stubGlobal("IntersectionObserver", FakeObserver);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
}

function rect(top: number, height: number): DOMRect {
  return {
    top,
    height,
    bottom: top + height,
    left: 0,
    right: 100,
    width: 100,
    x: 0,
    y: top,
    toJSON: () => ({}),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(Element.prototype, "scrollIntoView");
});

async function mountHome(authenticated = false, locale: "it" | "en" = "it") {
  const router = createAppRouter(createMemoryHistory());
  const pinia = createPinia();

  if (authenticated) {
    useAuthStore(pinia).$patch({
      status: "authenticated",
      user: {
        id: "00000000-0000-4000-8000-000000000001",
        email: "owner@example.com",
        is_active: true,
        created_at: "2026-08-10T12:00:00Z",
      },
      accessToken: "access-token",
      expiresAt: "2026-08-10T12:15:00Z",
    });
  }

  await router.push("/");
  await router.isReady();

  return mount(HomeView, {
    attachTo: document.body,
    global: {
      plugins: [pinia, createAppI18n(locale), router],
    },
  });
}

describe("home page", () => {
  it("presents the six-step path with a single h1 and the three twins", async () => {
    const wrapper = await mountHome();

    expect(wrapper.findAll("h1")).toHaveLength(1);
    expect(wrapper.get("h1").text()).toBe(
      "Un'idea diventa un'applicazione. Tu decidi a ogni passo.",
    );
    const steps = wrapper.findAll("[data-testid='home-step']");
    expect(steps).toHaveLength(6);
    expect(steps[0]?.text()).toContain("Tua decisione: Approva il brief");
    expect(steps[5]?.text()).toContain("Tua decisione: Scarica la cartella");
    const twins = wrapper.findAll("[data-testid='home-twin']");
    expect(twins).toHaveLength(3);
    expect(twins.map((twin) => twin.get("img").attributes("src"))).toEqual([
      "/home/brief.webp",
      "/home/critica.webp",
      "/home/prova.webp",
    ]);
    expect(twins.every((twin) => (twin.get("img").attributes("alt") ?? "").length > 0)).toBe(true);
    expect(wrapper.findAll("video")).toHaveLength(0);
    expect(wrapper.findAll("[data-testid='home-rule']")).toHaveLength(3);
    expect(wrapper.get("[data-testid='home-legend']").findAll("[data-claim]")).toHaveLength(3);
    expect(wrapper.get("[data-testid='home-enter']").attributes("href")).toBe("/register");
    expect(wrapper.get("footer").text()).toContain("Dott. Alex Testa");
    wrapper.unmount();
  });

  it.each<["it" | "en", string[], string, RegExp]>([
    [
      "it",
      ["Brief", "Prospettive", "User Twin", "Definizione", "Design e valutazione", "Dossier"],
      "Tua decisione: Approva le prospettive",
      /\b(squadra|agenti|agente|assistenti|assistente|pacchetto)\b/i,
    ],
    [
      "en",
      ["Brief", "Perspectives", "User Twin", "Definition", "Design & Evaluation", "Dossier"],
      "Your decision: Approve the perspectives",
      /\b(team|agents|agent|assistants|assistant|package)\b/i,
    ],
  ])(
    "names the six steps in %s and speaks of perspectives, not of a team",
    async (locale, titles, decision, team) => {
      const wrapper = await mountHome(false, locale);
      const steps = wrapper.findAll("[data-testid='home-step']");

      expect(steps.map((step) => step.get("h3").text())).toEqual(titles);
      expect(steps[1]?.text()).toContain(decision);
      expect(wrapper.text()).not.toMatch(team);
      wrapper.unmount();
    },
  );

  it("sends an authenticated owner to the projects from every entry", async () => {
    const wrapper = await mountHome(true);

    for (const hook of ["home-enter", "home-enter-path", "home-enter-closing"]) {
      expect(wrapper.get(`[data-testid='${hook}']`).attributes("href")).toBe("/projects");
    }
    wrapper.unmount();
  });

  it("scrolls to the twins and to the path and moves the focus there", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    allowMotion(false);
    const wrapper = await mountHome();

    await wrapper.get("[data-testid='home-twins-link']").trigger("click");
    expect(scrollIntoView).toHaveBeenLastCalledWith({ behavior: "smooth", block: "start" });
    expect(document.activeElement?.id).toBe("twin");

    await wrapper.get("[data-testid='home-path-link']").trigger("click");
    expect(document.activeElement?.id).toBe("steps");
    wrapper.unmount();
  });

  it("keeps every element visible and still when the visitor prefers reduced motion", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    allowMotion(true);
    const wrapper = await mountHome();

    expect(FakeObserver.instances).toHaveLength(0);
    expect(frames).toHaveLength(0);
    for (const element of wrapper.findAll("[data-reveal]")) {
      expect((element.element as HTMLElement).style.opacity).toBe("");
      expect((element.element as HTMLElement).style.transform).toBe("");
    }
    window.dispatchEvent(new Event("scroll"));
    expect(frames).toHaveLength(0);
    for (const row of wrapper.findAll("[data-timeline]")) {
      expect((row.element as HTMLElement).style.opacity).toBe("");
    }
    await wrapper.get("[data-testid='home-twins-link']").trigger("click");
    expect(scrollIntoView).toHaveBeenLastCalledWith({ behavior: "auto", block: "start" });
    wrapper.unmount();
  });

  it("reveals each part of the page when it scrolls into view", async () => {
    allowMotion(false);
    const wrapper = await mountHome();
    const observer = FakeObserver.instances[0];

    expect(observer?.options).toEqual({ threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    const title = wrapper.get("h1").element as HTMLElement;
    expect(title.style.opacity).toBe("0");
    expect(title.style.transform).toBe("translateY(32px)");
    const hero = wrapper.get("img[src='/home/hero.webp']").element as HTMLElement;
    expect(hero.style.transform).toBe("scale(1.1)");
    const number = wrapper.get("[data-reveal='rise']").element as HTMLElement;
    expect(number.style.transform).toBe("translateY(105%)");
    expect(observer?.observed.has(number.parentElement as Element)).toBe(true);
    expect(observer?.observed.has(number)).toBe(false);

    observer?.enter([title, number.parentElement as Element]);

    expect(title.style.opacity).toBe("1");
    expect(title.style.transform).toBe("none");
    expect(number.style.opacity).toBe("1");
    expect(number.style.transform).toBe("none");
    expect(observer?.observed.has(title)).toBe(false);

    wrapper.unmount();
    expect(observer?.disconnected).toBe(true);
  });

  it("moves the pictures with the scroll and lights the step in the middle of the screen", async () => {
    allowMotion(false);
    const wrapper = await mountHome();
    const rows = wrapper.findAll("[data-timeline]").map((row) => row.element as HTMLElement);
    rows.forEach((row, index) => {
      vi.spyOn(row, "getBoundingClientRect").mockReturnValue(rect(index * 200, 100));
    });
    const layer = wrapper.get("[data-parallax='0.12']").element as HTMLElement;
    vi.spyOn(layer.parentElement as HTMLElement, "getBoundingClientRect").mockReturnValue(
      rect(0, 740),
    );

    flushFrames();

    expect(rows.map((row) => row.style.opacity)).toEqual([
      "0.62",
      "0.62",
      "1",
      "0.62",
      "0.62",
      "0.62",
    ]);
    const expected = (-(370 - window.innerHeight / 2) * 0.12).toFixed(1);
    expect(layer.style.getPropertyValue("translate")).toBe(`0 ${expected}px`);

    rows.forEach((row, index) => {
      vi.spyOn(row, "getBoundingClientRect").mockReturnValue(rect(index * 200 - 400, 100));
    });
    window.dispatchEvent(new Event("scroll"));
    window.dispatchEvent(new Event("scroll"));
    expect(frames).toHaveLength(1);
    flushFrames();
    expect(rows[4]?.style.opacity).toBe("1");
    expect(rows[2]?.style.opacity).toBe("0.62");

    wrapper.unmount();
    window.dispatchEvent(new Event("scroll"));
    expect(frames).toHaveLength(0);
  });

  it("has no axe violations", { timeout: 30000 }, async () => {
    const wrapper = await mountHome();
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
