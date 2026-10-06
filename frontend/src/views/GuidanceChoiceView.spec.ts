import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import { apiClient, ApiError } from "@/api/client";
import type { UserResponse } from "@/api/contracts";
import { createAppI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { useAuthStore } from "@/stores/auth";
import { expectAccessible } from "@/test/axe";
import GuidanceChoiceView from "./GuidanceChoiceView.vue";

const ACCOUNT: UserResponse = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "owner@example.com",
  is_active: true,
  created_at: "2026-10-05T08:00:00Z",
  guidance_mode: null,
};

const PROJECT_PATH = "/projects/00000000-0000-4000-8000-000000000002";

const COPY = {
  it: {
    eyebrow: "Prima di cominciare",
    title: "Come vuoi lavorare?",
    intro:
      "Scegli come lo Studio ti accompagna nei tuoi progetti. La scelta vale per questo account e dopo la conferma non si può cambiare.",
    legend: "Modalità di lavoro",
    guided: [
      "Guidata",
      "Un passo alla volta, con le spiegazioni.",
      "Il brief nasce da un dialogo, una domanda alla volta.",
      "Quando approvi un passo, lo Studio prepara da solo le proposte del passo dopo.",
      "Le sezioni si aprono in ordine; dopo il primo giro restano tutte aperte.",
      "Per chi non ha esperienza di progettazione.",
    ],
    expert: [
      "Esperta",
      "Tutto aperto da subito, senza spiegazioni introduttive.",
      "Entri in qualunque sezione quando vuoi.",
      "Ogni proposta del modello parte solo quando la chiedi tu.",
      "Puoi inserire direttamente prospettive, twin, definizione e prototipo.",
      "Per chi progetta di mestiere.",
    ],
    warning: "Dopo la conferma non potrai più cambiare modalità.",
    confirm: "Conferma la scelta",
    confirmGuided: "Conferma: modalità guidata",
    confirmExpert: "Conferma: modalità esperta",
    logout: "Esci",
  },
  en: {
    eyebrow: "Before you start",
    title: "How do you want to work?",
    intro:
      "Choose how the Studio supports you in your projects. The choice applies to this account and cannot be changed after you confirm.",
    legend: "Working mode",
    guided: [
      "Guided",
      "One step at a time, with explanations.",
      "The brief comes from a dialogue, one question at a time.",
      "When you approve a step, the Studio prepares the proposals for the next one by itself.",
      "Sections open in order; after the first pass they all stay open.",
      "For people with no design experience.",
    ],
    expert: [
      "Expert",
      "Everything open from the start, without introductory explanations.",
      "You enter any section whenever you want.",
      "Every model proposal starts only when you ask for it.",
      "You can enter perspectives, twins, definition and prototype yourself.",
      "For people who design for a living.",
    ],
    warning: "After you confirm, you will not be able to change mode.",
    confirm: "Confirm the choice",
    confirmGuided: "Confirm: guided mode",
    confirmExpert: "Confirm: expert mode",
    logout: "Log out",
  },
} as const;

async function mountChoice(path = "/guidance", locale: "it" | "en" = "it", local = false) {
  const router = createAppRouter(createMemoryHistory());
  const pinia = createPinia();
  useAuthStore(pinia).$patch({
    status: "authenticated",
    user: ACCOUNT,
    accessToken: "access-token",
    expiresAt: "2026-10-05T08:15:00Z",
  });
  if (local) useAuthStore(pinia).$patch({ accessMode: "LOCAL_OWNER" });
  await router.push(path);
  await router.isReady();
  const replace = vi.spyOn(router, "replace").mockResolvedValue(undefined);
  const wrapper = mount(GuidanceChoiceView, {
    global: { plugins: [pinia, createAppI18n(locale), router] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, replace, auth: useAuthStore(pinia) };
}

type ChoiceWrapper = Awaited<ReturnType<typeof mountChoice>>["wrapper"];

function radio(wrapper: ChoiceWrapper, key: "guided" | "expert") {
  return wrapper.get<HTMLInputElement>(`[data-testid="guidance-option-${key}"] input`);
}

function confirmButton(wrapper: ChoiceWrapper) {
  return wrapper.get<HTMLButtonElement>('[data-testid="guidance-confirm"]');
}

async function confirmWith(wrapper: ChoiceWrapper, key: "guided" | "expert") {
  await wrapper.get(`[data-testid="guidance-option-${key}"]`).trigger("click");
  await confirmButton(wrapper).trigger("click");
  await flushPromises();
}

describe("guidance choice page", () => {
  it.each(["it", "en"] as const)(
    "presents the two modes in %s with nothing selected and the confirmation disabled",
    async (locale) => {
      const choose = vi.spyOn(apiClient, "chooseGuidanceMode");
      const { wrapper } = await mountChoice("/guidance", locale);
      const copy = COPY[locale];
      const screen = wrapper.get('[data-testid="guidance-choice"]');

      expect(screen.attributes("data-surface")).toBe("night");
      expect(wrapper.findAll("h1")).toHaveLength(1);
      expect(wrapper.get("h1").text()).toBe(copy.title);
      expect(wrapper.text()).toContain(copy.eyebrow);
      expect(wrapper.text()).toContain(copy.intro);
      expect(wrapper.get("fieldset legend").text()).toBe(copy.legend);
      for (const key of ["guided", "expert"] as const) {
        const option = wrapper.get(`[data-testid="guidance-option-${key}"]`);
        for (const text of copy[key]) expect(option.text()).toContain(text);
        expect(option.findAll('[role="listitem"]').map((item) => item.text())).toEqual(
          copy[key].slice(2, 5),
        );
        const input = radio(wrapper, key);
        expect(wrapper.get(`#${input.attributes("aria-labelledby")}`).text()).toBe(copy[key][0]);
        expect(wrapper.get(`#${input.attributes("aria-describedby")}`).text()).toContain(
          copy[key][1],
        );
      }
      const radios = wrapper.findAll<HTMLInputElement>('input[type="radio"]');
      expect(radios).toHaveLength(2);
      expect(radios.map((input) => input.attributes("name"))).toEqual([
        "guidance-mode",
        "guidance-mode",
      ]);
      expect(radios.some((input) => input.element.checked)).toBe(false);
      expect(wrapper.text()).toContain(copy.warning);
      expect(confirmButton(wrapper).text()).toBe(copy.confirm);
      expect(confirmButton(wrapper).attributes("disabled")).toBeDefined();
      expect(wrapper.get('[data-testid="guidance-choice-logout"]').text()).toBe(copy.logout);
      expect(wrapper.find('[data-testid="guidance-choice-error"]').exists()).toBe(false);

      await confirmButton(wrapper).trigger("click");
      await flushPromises();
      expect(choose).not.toHaveBeenCalled();
      wrapper.unmount();
    },
  );

  it.each(["it", "en"] as const)(
    "selects a mode with a click on its card and names it on the button in %s",
    async (locale) => {
      const { wrapper } = await mountChoice("/guidance", locale);

      await wrapper.get('[data-testid="guidance-option-expert"]').trigger("click");
      expect(radio(wrapper, "expert").element.checked).toBe(true);
      expect(radio(wrapper, "guided").element.checked).toBe(false);
      expect(confirmButton(wrapper).attributes("disabled")).toBeUndefined();
      expect(confirmButton(wrapper).text()).toBe(COPY[locale].confirmExpert);

      await wrapper.get('[data-testid="guidance-option-guided"]').trigger("click");
      expect(radio(wrapper, "guided").element.checked).toBe(true);
      expect(radio(wrapper, "expert").element.checked).toBe(false);
      expect(confirmButton(wrapper).text()).toBe(COPY[locale].confirmGuided);
      wrapper.unmount();
    },
  );

  it("keeps the hover of a card neutral and the audience line at the bottom of both cards", async () => {
    const { wrapper } = await mountChoice("/guidance", "en");

    for (const key of ["guided", "expert"] as const) {
      const card = wrapper.get(`[data-testid="guidance-option-${key}"]`);
      const details = wrapper.get(`#guidance-${key}-details`);
      const audience = details.element.lastElementChild;

      expect(card.classes().filter((name) => name.startsWith("hover:"))).toEqual([
        "hover:border-night-line-strong",
      ]);
      expect(card.classes()).toEqual(
        expect.arrayContaining([
          "has-checked:border-petrol-on-night",
          "has-checked:bg-petrol-on-night/8",
          "has-checked:ring-1",
        ]),
      );
      expect(details.classes()).toContain("grow");
      expect(audience?.textContent?.trim()).toBe(COPY.en[key][5]);
      expect(audience?.classList.contains("mt-auto")).toBe(true);
    }
    wrapper.unmount();
  });

  it("selects a mode from the keyboard on the native radio buttons", async () => {
    const { wrapper } = await mountChoice();
    const guided = radio(wrapper, "guided");
    const expert = radio(wrapper, "expert");

    guided.element.focus();
    expect(document.activeElement).toBe(guided.element);
    expect(guided.attributes("tabindex")).toBeUndefined();
    await guided.setValue(true);
    expect(confirmButton(wrapper).text()).toBe("Conferma: modalità guidata");

    expert.element.focus();
    await expert.setValue(true);
    expect(guided.element.checked).toBe(false);
    expect(confirmButton(wrapper).text()).toBe("Conferma: modalità esperta");
    wrapper.unmount();
  });

  it.each([
    [`/guidance?redirect=${PROJECT_PATH}`, PROJECT_PATH],
    ["/guidance?redirect=/projects", "/projects"],
    ["/guidance?redirect=//example.com", "/projects"],
    ["/guidance?redirect=https://example.com", "/projects"],
    ["/guidance", "/projects"],
  ])("saves the chosen mode from %s and goes on to %s", async (path, target) => {
    const choose = vi
      .spyOn(apiClient, "chooseGuidanceMode")
      .mockResolvedValue({ ...ACCOUNT, guidance_mode: "EXPERT" });
    const { wrapper, replace, auth } = await mountChoice(path);

    await confirmWith(wrapper, "expert");

    expect(choose).toHaveBeenCalledOnce();
    expect(choose).toHaveBeenCalledWith("access-token", "EXPERT");
    expect(auth.user?.guidance_mode).toBe("EXPERT");
    expect(replace).toHaveBeenCalledWith(target);
    expect(wrapper.find('[data-testid="guidance-choice-error"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("reads the account again when the mode was already chosen and goes on", async () => {
    const choose = vi
      .spyOn(apiClient, "chooseGuidanceMode")
      .mockRejectedValue(new ApiError(409, "guidance_mode_already_chosen"));
    const me = vi.spyOn(apiClient, "me").mockResolvedValue({ ...ACCOUNT, guidance_mode: "GUIDED" });
    const { wrapper, replace, auth } = await mountChoice(`/guidance?redirect=${PROJECT_PATH}`);

    await confirmWith(wrapper, "expert");

    expect(choose).toHaveBeenCalledWith("access-token", "EXPERT");
    expect(me).toHaveBeenCalledWith("access-token");
    expect(auth.user?.guidance_mode).toBe("GUIDED");
    expect(replace).toHaveBeenCalledWith(PROJECT_PATH);
    expect(wrapper.find('[data-testid="guidance-choice-error"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("explains a failed save, keeps the selection and lets the owner try again", async () => {
    const choose = vi
      .spyOn(apiClient, "chooseGuidanceMode")
      .mockRejectedValueOnce(new ApiError(500, "unexpected_api_error"))
      .mockResolvedValueOnce({ ...ACCOUNT, guidance_mode: "GUIDED" });
    const { wrapper, replace, auth } = await mountChoice();

    await confirmWith(wrapper, "guided");

    const error = wrapper.get('[data-testid="guidance-choice-error"]');
    expect(error.attributes("role")).toBe("alert");
    expect(error.text()).toBe("La scelta non è stata salvata. Riprova.");
    expect(document.activeElement).toBe(error.element);
    expect(replace).not.toHaveBeenCalled();
    expect(auth.user?.guidance_mode).toBeNull();
    expect(auth.isAuthenticated).toBe(true);
    expect(radio(wrapper, "guided").element.checked).toBe(true);
    expect(radio(wrapper, "guided").element.disabled).toBe(false);
    expect(confirmButton(wrapper).attributes("disabled")).toBeUndefined();
    expect(confirmButton(wrapper).text()).toBe("Conferma: modalità guidata");

    await confirmButton(wrapper).trigger("click");
    await flushPromises();

    expect(choose).toHaveBeenCalledTimes(2);
    expect(choose).toHaveBeenLastCalledWith("access-token", "GUIDED");
    expect(replace).toHaveBeenCalledWith("/projects");
    expect(wrapper.find('[data-testid="guidance-choice-error"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("shows the error in English", async () => {
    vi.spyOn(apiClient, "chooseGuidanceMode").mockRejectedValue(new TypeError("Failed to fetch"));
    const { wrapper, replace } = await mountChoice("/guidance", "en");

    await confirmWith(wrapper, "expert");

    expect(wrapper.get('[data-testid="guidance-choice-error"]').text()).toBe(
      "The choice was not saved. Try again.",
    );
    expect(replace).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("disables the options and the buttons while the choice is being saved", async () => {
    let resolve!: (value: UserResponse) => void;
    const choose = vi.spyOn(apiClient, "chooseGuidanceMode").mockImplementation(
      () =>
        new Promise<UserResponse>((done) => {
          resolve = done;
        }),
    );
    const { wrapper, replace } = await mountChoice("/guidance", "en");

    await wrapper.get('[data-testid="guidance-option-guided"]').trigger("click");
    await confirmButton(wrapper).trigger("click");
    await flushPromises();

    expect(confirmButton(wrapper).text()).toBe("Saving the choice…");
    expect(confirmButton(wrapper).attributes("disabled")).toBeDefined();
    expect(radio(wrapper, "guided").element.disabled).toBe(true);
    expect(radio(wrapper, "expert").element.disabled).toBe(true);
    expect(
      wrapper.get('[data-testid="guidance-choice-logout"]').attributes("disabled"),
    ).toBeDefined();
    await confirmButton(wrapper).trigger("click");
    expect(choose).toHaveBeenCalledOnce();

    resolve({ ...ACCOUNT, guidance_mode: "GUIDED" });
    await flushPromises();

    expect(replace).toHaveBeenCalledWith("/projects");
    wrapper.unmount();
  });

  it.each([
    ["confirmed by the server", () => Promise.resolve()],
    ["refused by the server", () => Promise.reject(new ApiError(503, "service_unavailable"))],
  ])("logs out and opens the sign in page when the exit is %s", async (_case, outcome) => {
    const logout = vi.spyOn(apiClient, "logout").mockImplementation(outcome);
    const choose = vi.spyOn(apiClient, "chooseGuidanceMode");
    const { wrapper, replace, auth } = await mountChoice(`/guidance?redirect=${PROJECT_PATH}`);

    await wrapper.get('[data-testid="guidance-choice-logout"]').trigger("click");
    await flushPromises();

    expect(logout).toHaveBeenCalledOnce();
    expect(auth.isAuthenticated).toBe(false);
    expect(auth.user).toBeNull();
    expect(replace).toHaveBeenCalledWith("/login");
    expect(choose).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each(["it", "en"] as const)(
    "offers no exit in a local Studio and still saves the choice in %s",
    async (locale) => {
      const logout = vi.spyOn(apiClient, "logout");
      const choose = vi
        .spyOn(apiClient, "chooseGuidanceMode")
        .mockResolvedValue({ ...ACCOUNT, guidance_mode: "GUIDED" });
      const { wrapper, replace, auth } = await mountChoice("/guidance", locale, true);

      expect(auth.isLocal).toBe(true);
      expect(wrapper.find('[data-testid="guidance-choice-logout"]').exists()).toBe(false);
      expect(wrapper.text()).not.toContain(COPY[locale].logout);
      expect(confirmButton(wrapper).text()).toBe(COPY[locale].confirm);

      await confirmWith(wrapper, "guided");

      expect(choose).toHaveBeenCalledWith("access-token", "GUIDED");
      expect(replace).toHaveBeenCalledWith("/projects");
      expect(logout).not.toHaveBeenCalled();
      expect(auth.isAuthenticated).toBe(true);
      wrapper.unmount();
    },
  );

  it("has no axe violations before and after a failed save", { timeout: 30000 }, async () => {
    vi.spyOn(apiClient, "chooseGuidanceMode").mockRejectedValue(
      new ApiError(500, "unexpected_api_error"),
    );
    const { wrapper } = await mountChoice();
    await expectAccessible(wrapper.element);

    await confirmWith(wrapper, "expert");

    expect(wrapper.find('[data-testid="guidance-choice-error"]').exists()).toBe(true);
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
