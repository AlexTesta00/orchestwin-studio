import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignChangeTarget } from "../api/designIterations";
import { DesignOpinionsApiError, type DesignOpinionsApi } from "../api/designOpinions";
import type { ChangeOpinionRun } from "../types/designOpinions";
import {
  CHANGE_OPINION_FAILED,
  useDesignOpinionsStore,
  type AuthorizedOpinionRequest,
} from "./designOpinions";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const VERSION = { id: "22222222-2222-4222-8222-222222222222", content_hash: "a".repeat(64) };
const NEXT_VERSION = { id: "22222222-2222-4222-8222-222222222333", content_hash: "b".repeat(64) };
const REQUEST = "Rendi la barra rossa con il testo blu";
const OTHER_REQUEST = "Rendi la barra verde";
const TARGET: DesignChangeTarget = {
  screen_code: "SCR-001",
  element_code: "ELM-018",
  label: "Forno Ravasi",
  html: "<a href='#SCR-002'>Forno Ravasi</a>",
};
const OTHER_TARGET: DesignChangeTarget = {
  ...TARGET,
  element_code: "ELM-027",
  label: "Panificio Colombo",
};
const SCREEN_TARGET: DesignChangeTarget = {
  screen_code: "SCR-001",
  label: "Botteghe vicine",
  html: "<section>Botteghe vicine</section>",
};
const ZONE_TARGET: DesignChangeTarget = {
  screen_code: "SCR-001",
  element_code: "ZON-005",
  label: "Cosa cerchi oggi?",
};
const PARTS_TARGET: DesignChangeTarget = {
  screen_code: "SCR-001",
  elements: [
    { element_code: "ELM-018", label: "Forno Ravasi" },
    { element_code: "ZON-005", label: "Cosa cerchi oggi?" },
  ],
};
const SWAPPED_PARTS_TARGET: DesignChangeTarget = {
  screen_code: "SCR-001",
  elements: [
    { element_code: "ZON-005", label: "Cosa cerchi oggi?" },
    { element_code: "ELM-018", label: "Forno Ravasi" },
  ],
};

const authorize: AuthorizedOpinionRequest = (operation) => operation("token");

function run(id: string, overrides: Partial<ChangeOpinionRun> = {}): ChangeOpinionRun {
  return {
    run_id: id,
    design_version_id: VERSION.id,
    design_content_hash: VERSION.content_hash,
    design_version_number: 7,
    request: REQUEST,
    target: TARGET,
    locale: "it-IT",
    requested_at: "2026-10-12T10:00:00+00:00",
    opinions: [],
    contrast: {
      mode: "LIGHT",
      text_threshold: 4.5,
      large_text_threshold: 3,
      control_border_threshold: 3,
    },
    cost_microusd: null,
    ...overrides,
  };
}

const ASKED = run("33333333-3333-4333-8333-333333333333");

function fakeApi() {
  return {
    ask: vi.fn<DesignOpinionsApi["ask"]>(async () => ASKED),
  } satisfies DesignOpinionsApi;
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function askAbout(
  store: ReturnType<typeof useDesignOpinionsStore>,
  api: DesignOpinionsApi,
  request = REQUEST,
  target = TARGET,
) {
  return store.ask(PROJECT, VERSION, request, target, "it-IT", authorize, api);
}

describe("design opinions store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("remembers what it asked about and keeps the opinion the twins gave", async () => {
    const store = useDesignOpinionsStore();
    const api = fakeApi();
    const answer = deferred<ChangeOpinionRun>();
    api.ask.mockImplementationOnce(() => answer.promise);

    const pending = askAbout(store, api, "  Rendi la barra   rossa\n con il testo blu ");

    expect(store.busy).toBe(true);
    expect(store.askedFor).toEqual({
      contentHash: VERSION.content_hash,
      codes: ["ELM-018"],
      request: REQUEST,
    });
    expect(api.ask).toHaveBeenCalledWith(
      PROJECT,
      {
        design_version_id: VERSION.id,
        design_content_hash: VERSION.content_hash,
        request: REQUEST,
        target: TARGET,
        locale: "it-IT",
      },
      "token",
    );
    answer.resolve(ASKED);

    await expect(pending).resolves.toEqual(ASKED);
    expect(store.busy).toBe(false);
    expect(store.current).toEqual(ASKED);
    expect(store.error).toBeNull();
  });

  it("asks one question at a time", async () => {
    const store = useDesignOpinionsStore();
    const api = fakeApi();
    const answer = deferred<ChangeOpinionRun>();
    api.ask.mockImplementationOnce(() => answer.promise);

    const first = askAbout(store, api);
    await expect(askAbout(store, api, OTHER_REQUEST, OTHER_TARGET)).resolves.toBeNull();
    answer.resolve(ASKED);
    await first;

    expect(api.ask).toHaveBeenCalledOnce();
    expect(store.askedFor?.codes).toEqual(["ELM-018"]);
    expect(store.current).toEqual(ASKED);
  });

  it("calls stale every opinion before the first question", () => {
    expect(useDesignOpinionsStore().isStale(VERSION, TARGET, REQUEST)).toBe(true);
  });

  it.each([
    ["the same request written with other spaces", VERSION, TARGET, `  ${REQUEST} `, false],
    ["another version of the design", NEXT_VERSION, TARGET, REQUEST, true],
    ["another element", VERSION, OTHER_TARGET, REQUEST, true],
    ["a zone", VERSION, ZONE_TARGET, REQUEST, true],
    ["the whole screen", VERSION, SCREEN_TARGET, REQUEST, true],
    ["another text", VERSION, TARGET, OTHER_REQUEST, true],
  ])(
    "tells whether the opinion is stale for %s",
    async (_case, version, target, request, stale) => {
      const store = useDesignOpinionsStore();
      await askAbout(store, fakeApi());

      expect(store.isStale(version, target, request)).toBe(stale);
    },
  );

  it.each([
    ["an element", TARGET, ["ELM-018"]],
    ["a zone", ZONE_TARGET, ["ZON-005"]],
    ["several parts", PARTS_TARGET, ["ELM-018", "ZON-005"]],
    ["several parts in another order", SWAPPED_PARTS_TARGET, ["ZON-005", "ELM-018"]],
    ["a screen", SCREEN_TARGET, []],
  ])("remembers the codes of %s in the order of the target", async (_case, target, codes) => {
    const store = useDesignOpinionsStore();
    await askAbout(store, fakeApi(), REQUEST, target);

    expect(store.askedFor?.codes).toEqual(codes);
  });

  it("ties an opinion on several parts to the same parts in the same order", async () => {
    const store = useDesignOpinionsStore();
    await askAbout(store, fakeApi(), REQUEST, PARTS_TARGET);

    expect(store.askedFor?.codes).toEqual(["ELM-018", "ZON-005"]);
    expect(store.isStale(VERSION, { ...PARTS_TARGET }, REQUEST)).toBe(false);
    expect(store.isStale(VERSION, SWAPPED_PARTS_TARGET, REQUEST)).toBe(true);
    expect(store.isStale(VERSION, ZONE_TARGET, REQUEST)).toBe(true);
    expect(store.isStale(VERSION, TARGET, REQUEST)).toBe(true);
  });

  it("forgets the opinion and drops an answer that arrives after it was cleared", async () => {
    const store = useDesignOpinionsStore();
    const api = fakeApi();
    await askAbout(store, api);
    const late = deferred<ChangeOpinionRun>();
    api.ask.mockImplementationOnce(() => late.promise);
    const pending = askAbout(store, api, OTHER_REQUEST);

    store.clear();

    expect(store.current).toBeNull();
    expect(store.askedFor).toBeNull();
    expect(store.busy).toBe(false);
    late.resolve(run("33333333-3333-4333-8333-333333333444", { request: OTHER_REQUEST }));
    await expect(pending).resolves.toBeNull();
    expect(store.current).toBeNull();
    expect(store.busy).toBe(false);
  });

  it("keeps the code of a refusal and gives the error back to the caller", async () => {
    const store = useDesignOpinionsStore();
    const api = fakeApi();
    const refusal = new DesignOpinionsApiError("The design opinions request failed", {
      status: 503,
      code: "DESIGN_REVIEWER_NOT_CONFIGURED",
      payload: { detail: { code: "DESIGN_REVIEWER_NOT_CONFIGURED" } },
    });
    api.ask.mockRejectedValueOnce(refusal);

    await expect(askAbout(store, api)).rejects.toBe(refusal);
    expect(store.error).toBe("DESIGN_REVIEWER_NOT_CONFIGURED");
    expect(store.busy).toBe(false);
    expect(store.current).toBeNull();

    api.ask.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(askAbout(store, api)).rejects.toBeInstanceOf(TypeError);
    expect(store.error).toBe(CHANGE_OPINION_FAILED);

    await askAbout(store, api);
    expect(store.error).toBeNull();
  });
});
