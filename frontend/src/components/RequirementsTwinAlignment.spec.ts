import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  RequirementsAlignmentApiError,
  type RequirementsAlignmentApi,
} from "@/api/requirementsAlignment";
import { expectAccessible } from "@/test/axe";
import type {
  RequirementsAlignmentPayload,
  RequirementsRealignmentPayload,
} from "@/types/requirementsAlignment";
import RequirementsTwinAlignment from "./RequirementsTwinAlignment.vue";

const PROJECT_ID = "project-1";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function status(
  overrides: Partial<RequirementsAlignmentPayload> = {},
): RequirementsAlignmentPayload {
  return {
    aligned: false,
    issue: null,
    requirements_version_number: 2,
    snapshot_version_number: 3,
    twins_approved: true,
    ...overrides,
  };
}

const REALIGNMENT: RequirementsRealignmentPayload = {
  version_id: "requirements-3",
  version_number: 3,
  based_on_version_number: 2,
  content_hash: "3".repeat(64),
  user_modeling_version_number: 3,
  twin_count: 5,
  gate_approval_required: true,
};

class FakeAlignmentApi implements RequirementsAlignmentApi {
  current: RequirementsAlignmentPayload | Error;

  constructor(initial: RequirementsAlignmentPayload | Error) {
    this.current = initial;
  }

  status = vi.fn(async (): Promise<RequirementsAlignmentPayload> => {
    if (this.current instanceof Error) throw this.current;
    return this.current;
  });

  realign = vi.fn(async (): Promise<RequirementsRealignmentPayload> => {
    this.current = status({
      aligned: true,
      issue: "REQUIREMENTS_ALREADY_ALIGNED",
      requirements_version_number: REALIGNMENT.version_number,
    });
    return REALIGNMENT;
  });
}

function refused(code: string, status = 409): RequirementsAlignmentApiError {
  return new RequirementsAlignmentApiError("The requirements alignment request failed", {
    status,
    code,
    payload: { detail: { code } },
  });
}

function mountAlignment(
  api: RequirementsAlignmentApi,
  props: Partial<{ locale: "en" | "it"; refreshKey: string | number | null }> = {},
) {
  return mount(RequirementsTwinAlignment, {
    props: { projectId: PROJECT_ID, locale: "it", authorize, api, ...props },
  });
}

const card = '[data-testid="requirements-twin-alignment"]';
const text = '[data-testid="requirements-twin-alignment-text"]';
const update = '[data-testid="requirements-twin-alignment-update"]';
const failure = '[data-testid="requirements-twin-alignment-error"]';

describe("RequirementsTwinAlignment", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it.each([
    ["aligned", status({ aligned: true, issue: "REQUIREMENTS_ALREADY_ALIGNED" })],
    ["missing", status({ issue: "REQUIREMENTS_NOT_FOUND", requirements_version_number: null })],
    ["unavailable", new Error("network down")],
  ])("renders nothing when the requirements are %s", async (_label, initial) => {
    const api = new FakeAlignmentApi(initial);
    const wrapper = mountAlignment(api);
    await flushPromises();
    expect(api.status).toHaveBeenCalledWith(PROJECT_ID, "token");
    expect(wrapper.find(card).exists()).toBe(false);
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("updates the requirements to the current twins and asks to approve them again", async () => {
    const api = new FakeAlignmentApi(status());
    const wrapper = mountAlignment(api);
    await flushPromises();
    expect(wrapper.get(card).find("h3").text()).toBe("I twin sono cambiati");
    expect(wrapper.get(text).text()).toBe(
      "Questi requisiti sono stati scritti per i twin precedenti. Aggiornali perché seguano i twin attuali: il contenuto resta lo stesso, poi li approvi di nuovo.",
    );
    expect(wrapper.get(update).text()).toBe("Aggiorna i requisiti");
    await wrapper.get(update).trigger("click");
    await flushPromises();
    expect(api.realign).toHaveBeenCalledWith(PROJECT_ID, "token");
    expect(wrapper.emitted("realigned")).toEqual([[REALIGNMENT]]);
    const done = wrapper.get('[data-testid="requirements-twin-alignment-done"]');
    expect(done.attributes("role")).toBe("status");
    expect(done.text()).toContain(
      "La versione 3 dei requisiti è pronta con lo stesso contenuto. Approvala di nuovo qui sotto.",
    );
    expect(wrapper.get(card).find("h3").text()).toBe("I requisiti seguono i twin attuali");
    expect(wrapper.find(update).exists()).toBe(false);
    await wrapper.setProps({ refreshKey: REALIGNMENT.content_hash });
    await flushPromises();
    expect(api.status).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="requirements-twin-alignment-done"]').exists()).toBe(true);
    api.current = status({ aligned: true, requirements_version_number: 4 });
    await wrapper.setProps({ refreshKey: "4".repeat(64) });
    await flushPromises();
    expect(wrapper.find(card).exists()).toBe(false);
  });

  it("shows a status line and keeps the button disabled while the update runs", async () => {
    let resolve!: (value: RequirementsRealignmentPayload) => void;
    const api = new FakeAlignmentApi(status());
    api.realign.mockImplementationOnce(
      () =>
        new Promise<RequirementsRealignmentPayload>((done) => {
          resolve = done;
        }),
    );
    const wrapper = mountAlignment(api, { locale: "en" });
    await flushPromises();
    await wrapper.get(update).trigger("click");
    await flushPromises();
    const running = wrapper.get('[data-testid="requirements-twin-alignment-running"]');
    expect(running.attributes("role")).toBe("status");
    expect(running.text()).toBe("Updating the requirements…");
    expect(wrapper.get(update).attributes("disabled")).toBeDefined();
    await wrapper.get(update).trigger("click");
    expect(api.realign).toHaveBeenCalledTimes(1);
    resolve(REALIGNMENT);
    await flushPromises();
    expect(wrapper.find('[data-testid="requirements-twin-alignment-running"]').exists()).toBe(
      false,
    );
    expect(wrapper.get('[data-testid="requirements-twin-alignment-done"]').text()).toContain(
      "Version 3 of the requirements is ready with the same content. Approve it again below.",
    );
  });

  it("asks to approve the twins first without offering the update", async () => {
    const api = new FakeAlignmentApi(
      status({ issue: "USER_TWINS_APPROVAL_REQUIRED", twins_approved: false }),
    );
    const wrapper = mountAlignment(api);
    await flushPromises();
    expect(wrapper.get(text).text()).toBe(
      "Approva prima i twin nel passo User Twin, poi torna qui per aggiornare i requisiti.",
    );
    expect(wrapper.find(update).exists()).toBe(false);
    expect(wrapper.get(card).find("details").exists()).toBe(false);
  });

  it("asks to decide the pending change first without offering the update", async () => {
    const api = new FakeAlignmentApi(status({ issue: "REQUIREMENTS_REVISION_PENDING" }));
    const wrapper = mountAlignment(api);
    await flushPromises();
    expect(wrapper.get(text).text()).toBe(
      "Una modifica proposta a questi requisiti aspetta la tua decisione. Applicala o scartala qui sotto, poi aggiorna i requisiti.",
    );
    expect(wrapper.find(update).exists()).toBe(false);
  });

  it.each([
    [
      "REQUIREMENTS_CONTEXT_CHANGED",
      "Sono cambiati anche il brief o la squadra, quindi questi requisiti non si possono aggiornare automaticamente.",
    ],
    [
      "TWIN_NO_LONGER_AVAILABLE",
      "Questi requisiti citano un twin che non fa più parte del progetto, quindi non si possono aggiornare automaticamente.",
    ],
    ["SOMETHING_NEW", "Questi requisiti non si possono aggiornare automaticamente."],
  ])("explains that %s blocks the automatic update", async (issue, explanation) => {
    const api = new FakeAlignmentApi(status({ issue }));
    const wrapper = mountAlignment(api);
    await flushPromises();
    expect(wrapper.get(text).text()).toBe(explanation);
    const details = wrapper.get(card).get("details");
    expect(details.get("summary").text()).toBe("Dettagli");
    expect(details.get("code").text()).toBe(issue);
    expect(wrapper.find(update).exists()).toBe(false);
  });

  it("explains a refused update and keeps the button available", async () => {
    const api = new FakeAlignmentApi(status());
    api.realign
      .mockRejectedValueOnce(refused("REQUIREMENTS_REVISION_PENDING"))
      .mockRejectedValueOnce(refused("PERSISTENCE_REJECTED"))
      .mockRejectedValueOnce(refused("TWIN_NO_LONGER_AVAILABLE"))
      .mockRejectedValueOnce(new Error("network down"));
    const wrapper = mountAlignment(api);
    await flushPromises();
    const messages: string[] = [];
    for (let attempt = 0; attempt < 4; attempt++) {
      await wrapper.get(update).trigger("click");
      await flushPromises();
      const alert = wrapper.get(failure);
      expect(alert.attributes("role")).toBe("alert");
      messages.push(alert.get("p").text());
      expect(wrapper.get(update).attributes("disabled")).toBeUndefined();
    }
    expect(messages).toEqual([
      "Una modifica proposta a questi requisiti aspetta la tua decisione. Applicala o scartala qui sotto, poi riprova.",
      "Non è stato possibile salvare l'aggiornamento perché nel frattempo i requisiti sono cambiati. Ricarica la pagina e riprova.",
      "Questi requisiti citano un twin che non fa più parte del progetto, quindi non si possono aggiornare automaticamente.",
      "Non è stato possibile aggiornare i requisiti. Riprova.",
    ]);
    expect(wrapper.get(failure).find("details").exists()).toBe(false);
    expect(wrapper.emitted("realigned")).toBeUndefined();
    await wrapper.get(update).trigger("click");
    await flushPromises();
    expect(wrapper.find(failure).exists()).toBe(false);
    expect(wrapper.emitted("realigned")).toHaveLength(1);
  });

  it("reads the status again when the refresh key or the project changes", async () => {
    const api = new FakeAlignmentApi(status({ aligned: true }));
    const wrapper = mountAlignment(api, { refreshKey: "a" });
    await flushPromises();
    expect(wrapper.find(card).exists()).toBe(false);
    api.current = status();
    await wrapper.setProps({ refreshKey: "b" });
    await flushPromises();
    expect(api.status).toHaveBeenCalledTimes(2);
    expect(wrapper.find(update).exists()).toBe(true);
    api.current = status({ issue: "REQUIREMENTS_NOT_FOUND" });
    await wrapper.setProps({ projectId: "project-2" });
    await flushPromises();
    expect(api.status).toHaveBeenLastCalledWith("project-2", "token");
    expect(wrapper.find(card).exists()).toBe(false);
  });

  it("has no axe violations", async () => {
    const api = new FakeAlignmentApi(status());
    api.realign.mockRejectedValueOnce(refused("USER_TWINS_APPROVAL_REQUIRED"));
    const wrapper = mountAlignment(api);
    await flushPromises();
    await expectAccessible(wrapper.element);
    await wrapper.get(update).trigger("click");
    await flushPromises();
    expect(wrapper.get(failure).get("code").text()).toBe("USER_TWINS_APPROVAL_REQUIRED");
    await expectAccessible(wrapper.element);
  });
});
