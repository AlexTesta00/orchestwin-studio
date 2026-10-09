import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { DesignCritiqueApiError, type DesignCritiqueApi } from "../api/designCritique";
import { CRITIQUE_MAX_FILE_BYTES } from "../stores/designCritique";
import { expectAccessible } from "../test/axe";
import type {
  DesignCritiqueResultPayload,
  DesignCritiqueRunPayload,
  DesignCritiqueSourcePayload,
} from "../types/designCritique";
import DesignCritiquePanel from "./DesignCritiquePanel.vue";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SOURCE_ID = "22222222-2222-4222-8222-222222222222";
const PAGE_ID = "22222222-2222-4222-8222-222222222333";
const GIULIA = "44444444-4444-4444-8444-444444444444";
const MARCO = "44444444-4444-4444-8444-444444444555";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");

const IMAGE_SOURCE: DesignCritiqueSourcePayload = {
  id: SOURCE_ID,
  project_id: PROJECT_ID,
  kind: "IMAGE",
  title: "Booking page",
  url: null,
  page: null,
  shots: [
    {
      code: "SCR-001",
      media_type: "image/png",
      byte_size: 8,
      sha256: "a".repeat(64),
      width: 1170,
      height: 2532,
      viewport_width: null,
    },
  ],
  created_at: "2026-10-09T10:00:00Z",
  content_hash: "b".repeat(64),
};

const PAGE_SOURCE: DesignCritiqueSourcePayload = {
  ...IMAGE_SOURCE,
  id: PAGE_ID,
  kind: "WEB_PAGE",
  title: "Gym timetable",
  url: "https://gym.example.org/timetable",
  shots: [
    { ...IMAGE_SOURCE.shots[0]!, width: 1440, height: 900, viewport_width: 1440 },
    { ...IMAGE_SOURCE.shots[0]!, code: "SCR-002", width: 390, height: 844, viewport_width: 390 },
  ],
};

const IMAGE_RUN: DesignCritiqueRunPayload = {
  id: "33333333-3333-4333-8333-333333333333",
  project_id: PROJECT_ID,
  source: IMAGE_SOURCE,
  twins: [{ twin_id: GIULIA, version_number: 2, name: "Giulia" }],
  responses: [
    {
      twin_id: GIULIA,
      twin_version: 2,
      summary: "I find the times quickly, but the booking button is far from them.",
      evidence_gaps: ["The colour contrast, from a single picture."],
      findings: [
        {
          finding_id: "UTF-001",
          twin_id: GIULIA,
          location: "SCR-001 Supplied image · 1170×2532 px",
          anchor_key: "SCR-001",
          summary: "The booking button sits below the fold.",
          rationale: "I book between two lessons.",
          criterion: "actionability",
          severity: "moderate",
          recommended_action: "Move the booking button next to the times.",
          confidence: 0.6,
        },
      ],
    },
  ],
  verdicts: [{ twin_id: GIULIA, anchor_key: "SCR-001", verdict: "SLOWS" }],
  started_at: "2026-10-09T10:00:00Z",
  completed_at: "2026-10-09T10:02:22Z",
  duration_seconds: 142.3,
  cost_microusd: 0,
  content_hash: "c".repeat(64),
};

const PAGE_RUN: DesignCritiqueRunPayload = {
  ...IMAGE_RUN,
  id: "33333333-3333-4333-8333-333333333444",
  source: PAGE_SOURCE,
  twins: [
    { twin_id: GIULIA, version_number: 2, name: "Giulia" },
    { twin_id: MARCO, version_number: 1, name: "Marco" },
  ],
  responses: [
    { ...IMAGE_RUN.responses[0]!, evidence_gaps: [] },
    {
      twin_id: MARCO,
      twin_version: 1,
      summary: "On the phone I cannot read the timetable.",
      evidence_gaps: [],
      findings: [
        {
          ...IMAGE_RUN.responses[0]!.findings[0]!,
          finding_id: "UTF-002",
          twin_id: MARCO,
          anchor_key: "SCR-002",
          severity: "critical",
          summary: "The timetable in SCR-002 is cut on the right.",
          recommended_action: "Show one day at a time on SCR-002.",
        },
      ],
    },
  ],
  verdicts: [
    { twin_id: GIULIA, anchor_key: "SCR-001", verdict: "WORKS" },
    { twin_id: GIULIA, anchor_key: "SCR-002", verdict: "SLOWS" },
    { twin_id: MARCO, anchor_key: "SCR-001", verdict: "WORKS" },
    { twin_id: MARCO, anchor_key: "SCR-002", verdict: "BLOCKS" },
  ],
  completed_at: "2026-10-08T09:30:00Z",
  duration_seconds: 95,
  cost_microusd: 452000,
};

function fakeApi(runs: DesignCritiqueRunPayload[] = []) {
  return {
    uploadSource: vi.fn<DesignCritiqueApi["uploadSource"]>(async () => IMAGE_SOURCE),
    sources: vi.fn<DesignCritiqueApi["sources"]>(async () => runs.map((item) => item.source)),
    shot: vi.fn<DesignCritiqueApi["shot"]>(
      async () => new Blob(["fake-png"], { type: "image/png" }),
    ),
    critique: vi.fn<DesignCritiqueApi["critique"]>(
      async (): Promise<DesignCritiqueResultPayload> => ({
        status: "DESIGN_CRITIQUE_RECORDED",
        run: IMAGE_RUN,
      }),
    ),
    runs: vi.fn<DesignCritiqueApi["runs"]>(async () => runs),
  } satisfies DesignCritiqueApi;
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

interface MountOptions {
  locale?: "en" | "it";
  api?: DesignCritiqueApi;
  twinsReady?: boolean;
  redrawReady?: boolean;
  redrawBusy?: boolean;
  attach?: boolean;
}

const mounted: VueWrapper[] = [];

function mountPanel(options: MountOptions = {}) {
  const locale = options.locale ?? "en";
  const wrapper = mount(DesignCritiquePanel, {
    props: {
      projectId: PROJECT_ID,
      locale,
      authorize,
      api: options.api ?? fakeApi(),
      ...(options.twinsReady === undefined ? {} : { twinsReady: options.twinsReady }),
      ...(options.redrawReady === undefined ? {} : { redrawReady: options.redrawReady }),
      ...(options.redrawBusy === undefined ? {} : { redrawBusy: options.redrawBusy }),
    },
    global: { plugins: [createAppI18n(locale)] },
    ...(options.attach === true ? { attachTo: document.body } : {}),
  });
  mounted.push(wrapper);
  return wrapper;
}

async function open(wrapper: VueWrapper): Promise<void> {
  const details = wrapper.get('[data-testid="design-critique"]');
  (details.element as HTMLDetailsElement).open = true;
  await details.trigger("toggle");
  await flushPromises();
}

async function choose(wrapper: VueWrapper, file: File): Promise<void> {
  const input = wrapper.get('[data-testid="design-critique-file"]');
  Object.defineProperty(input.element, "files", { value: [file], configurable: true });
  await input.trigger("change");
}

function image(name = "booking.png", type = "image/png", size: number | null = null): File {
  const file = new File(["fake-png"], name, { type });
  if (size !== null) {
    Object.defineProperty(file, "size", { configurable: true, value: size });
  }
  return file;
}

function texts(wrapper: VueWrapper, testid: string): string[] {
  return wrapper.findAll(`[data-testid="${testid}"]`).map((item) => item.text());
}

const URL_METHODS = ["createObjectURL", "revokeObjectURL"] as const;
const originals = Object.fromEntries(
  URL_METHODS.map((name) => [name, Object.getOwnPropertyDescriptor(URL, name)]),
);
let revokeObjectURL = vi.fn<(url: string) => void>();

describe("DesignCritiquePanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    let created = 0;
    revokeObjectURL = vi.fn<(url: string) => void>();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn<(blob: Blob) => string>(() => `blob:shot-${(created += 1)}`),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: revokeObjectURL,
    });
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
    for (const name of URL_METHODS) {
      const original = originals[name];
      if (original === undefined) {
        Reflect.deleteProperty(URL, name);
      } else {
        Object.defineProperty(URL, name, original);
      }
    }
  });

  it.each([
    ["en", "Critique of an existing design"],
    ["it", "Critica di un design esistente"],
  ] as const)(
    "stays closed and asks the Studio nothing until it is opened (%s)",
    (locale, label) => {
      const api = fakeApi([IMAGE_RUN]);
      const wrapper = mountPanel({ locale, api });

      const details = wrapper.get('[data-testid="design-critique"]');
      expect(details.element.tagName).toBe("DETAILS");
      expect((details.element as HTMLDetailsElement).open).toBe(false);
      const summary = wrapper.get('[data-testid="design-critique-summary"]');
      expect(summary.element.tagName).toBe("SUMMARY");
      expect(summary.get("span:not([aria-hidden])").text()).toBe(label);
      expect(api.runs).not.toHaveBeenCalled();
      expect(api.sources).not.toHaveBeenCalled();
      expect(api.shot).not.toHaveBeenCalled();
    },
  );

  it("loads the earlier critiques once, when it is opened", async () => {
    const api = fakeApi([IMAGE_RUN]);
    const wrapper = mountPanel({ api });

    await open(wrapper);
    const details = wrapper.get('[data-testid="design-critique"]');
    (details.element as HTMLDetailsElement).open = false;
    await details.trigger("toggle");
    await open(wrapper);

    expect(api.runs).toHaveBeenCalledTimes(1);
    expect(api.runs).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(wrapper.get('[data-testid="design-critique-run"] h3').text()).toBe("Booking page");
    expect(api.shot).toHaveBeenCalledWith(PROJECT_ID, SOURCE_ID, "SCR-001", "access-token");
  });

  it.each([
    ["en", "Approve the twins first."],
    ["it", "Prima approva i twin."],
  ] as const)(
    "keeps the request unavailable without an image or without approved twins (%s)",
    async (locale, missing) => {
      const api = fakeApi();
      const wrapper = mountPanel({ locale, api });
      await open(wrapper);
      const button = () => wrapper.get('[data-testid="design-critique-ask"]');

      expect(button().attributes("aria-disabled")).toBe("true");
      expect(wrapper.find('[data-testid="design-critique-twins-missing"]').exists()).toBe(false);
      await button().trigger("click");
      expect(api.uploadSource).not.toHaveBeenCalled();

      await choose(wrapper, image());
      expect(button().attributes("aria-disabled")).toBeUndefined();

      await wrapper.setProps({ twinsReady: false });
      const note = wrapper.get('[data-testid="design-critique-twins-missing"]');
      expect(note.text()).toBe(missing);
      expect(button().attributes("aria-disabled")).toBe("true");
      expect(button().attributes("aria-describedby")?.split(" ")).toContain(note.attributes("id"));
      await button().trigger("click");
      await flushPromises();
      expect(api.uploadSource).not.toHaveBeenCalled();
      expect(api.critique).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["en", image("logo.gif", "image/gif"), "Choose a PNG or JPEG image."],
    [
      "en",
      image("huge.png", "image/png", CRITIQUE_MAX_FILE_BYTES + 1),
      "The image is larger than 5 MB: choose a lighter one.",
    ],
    ["it", image("logo.gif", "image/gif"), "Scegli un'immagine PNG o JPEG."],
    [
      "it",
      image("huge.jpg", "image/jpeg", CRITIQUE_MAX_FILE_BYTES + 1),
      "L'immagine supera 5 MB: scegline una più leggera.",
    ],
  ] as const)(
    "refuses a file that the Studio would refuse, with a message and no request (%s)",
    async (locale, file, message) => {
      const api = fakeApi();
      const wrapper = mountPanel({ locale, api });
      await open(wrapper);

      await choose(wrapper, file);

      const error = wrapper.get('[data-testid="design-critique-file-error"]');
      expect(error.text()).toBe(message);
      expect(error.attributes("role")).toBe("alert");
      const input = wrapper.get('[data-testid="design-critique-file"]');
      expect(input.attributes("aria-invalid")).toBe("true");
      expect(input.attributes("accept")).toBe("image/png,image/jpeg");
      expect(input.attributes("aria-describedby")?.split(" ")).toContain(error.attributes("id"));
      await wrapper.get('[data-testid="design-critique-ask"]').trigger("click");
      await flushPromises();
      expect(api.uploadSource).not.toHaveBeenCalled();

      await choose(wrapper, image());
      expect(wrapper.find('[data-testid="design-critique-file-error"]').exists()).toBe(false);
      expect(
        wrapper.get('[data-testid="design-critique-ask"]').attributes("aria-disabled"),
      ).toBeUndefined();
    },
  );

  it.each([
    [
      "en",
      "en-US",
      [
        "Uploading the image…",
        "The twins are looking at the design…",
        "Opinion received in 142 s.",
      ],
      "Slows me down",
      "Moderate",
      "What to do: Move the booking button next to the times.",
      "Opinion in 142 s · included in the subscription",
      "Booking page, Supplied image",
      "I cannot judge",
    ],
    [
      "it",
      "it-IT",
      ["Carico l'immagine…", "I twin guardano il design…", "Parere ricevuto in 142 s."],
      "Mi rallenta",
      "Moderata",
      "Cosa fare: Move the booking button next to the times.",
      "Parere in 142 s · incluso nell'abbonamento",
      "Booking page, Immagine fornita",
      "Non posso giudicare",
    ],
  ] as const)(
    "uploads the image, asks the twins in the language of the page and shows their opinion (%s)",
    async (locale, tag, statuses, verdict, severity, action, cost, alt, gaps) => {
      const api = fakeApi();
      const upload = deferred<DesignCritiqueSourcePayload>();
      const answer = deferred<DesignCritiqueResultPayload>();
      api.uploadSource.mockImplementationOnce(() => upload.promise);
      api.critique.mockImplementationOnce(() => answer.promise);
      const wrapper = mountPanel({ locale, api, attach: true });
      await open(wrapper);
      const status = () => wrapper.get('[data-testid="design-critique-status"]');
      expect(status().attributes("role")).toBe("status");
      expect(status().attributes("aria-live")).toBe("polite");
      const file = image();

      await choose(wrapper, file);
      await wrapper.get('[data-testid="design-critique-title"]').setValue("Booking page");
      await wrapper.get('[data-testid="design-critique-ask"]').trigger("click");
      await flushPromises();
      expect(status().text()).toBe(statuses[0]);
      expect(wrapper.get('[data-testid="design-critique-ask"]').attributes("aria-disabled")).toBe(
        "true",
      );
      upload.resolve(IMAGE_SOURCE);
      await flushPromises();
      expect(status().text()).toBe(statuses[1]);
      answer.resolve({ status: "DESIGN_CRITIQUE_RECORDED", run: IMAGE_RUN });
      await flushPromises();
      expect(status().text()).toBe(statuses[2]);

      const [project, form] = api.uploadSource.mock.calls[0] ?? [];
      expect(project).toBe(PROJECT_ID);
      expect([...(form?.keys() ?? [])]).toEqual(["kind", "title", "shots"]);
      expect(form?.get("kind")).toBe("IMAGE");
      expect(form?.get("title")).toBe("Booking page");
      expect(form?.get("shots")).toBe(file);
      expect(api.critique).toHaveBeenCalledWith(
        PROJECT_ID,
        { source_id: SOURCE_ID, locale: tag },
        "access-token",
      );
      expect(wrapper.emitted("critiqued")).toEqual([[IMAGE_RUN]]);

      const result = wrapper.get('[data-testid="design-critique-run"]');
      expect(result.get("h3").text()).toBe("Booking page");
      expect(document.activeElement).toBe(result.get("h3").element);
      expect(texts(wrapper, "design-critique-screen-label")).toEqual([alt.split(", ")[1]]);
      const shot = wrapper.get('[data-testid="design-critique-shot"]');
      expect(shot.attributes("src")).toBe("blob:shot-1");
      expect(shot.attributes("alt")).toBe(alt);
      const verdicts = wrapper.findAll('[data-testid="design-critique-verdict"]');
      expect(verdicts.map((item) => [item.text(), item.attributes("data-verdict")])).toEqual([
        [verdict, "SLOWS"],
      ]);
      expect(texts(wrapper, "design-critique-twin-name")).toEqual(["Giulia"]);
      expect(texts(wrapper, "design-critique-twin-summary")).toEqual([
        "I find the times quickly, but the booking button is far from them.",
      ]);
      expect(texts(wrapper, "design-critique-severity")).toEqual([severity]);
      expect(texts(wrapper, "design-critique-finding-summary")).toEqual([
        "The booking button sits below the fold.",
      ]);
      expect(texts(wrapper, "design-critique-action")).toEqual([action]);
      expect(wrapper.find('[data-testid="design-critique-place"]').exists()).toBe(false);
      const unknown = wrapper.get('[data-testid="design-critique-gaps"]');
      expect(unknown.get("p").text()).toBe(gaps);
      expect(unknown.findAll("li").map((item) => item.text())).toEqual([
        "The colour contrast, from a single picture.",
      ]);
      expect(wrapper.get('[data-testid="design-critique-cost"]').text()).toBe(cost);
      expect(wrapper.get('[data-testid="design-critique-ask"]').attributes("aria-disabled")).toBe(
        "true",
      );
      expect(
        (wrapper.get('[data-testid="design-critique-file"]').element as HTMLInputElement).value,
      ).toBe("");
    },
  );

  it.each([
    [
      "en",
      ["Screen 1 · 1440 px", "Screen 2 · 390 px"],
      ["Works for me", "Works for me", "Slows me down", "Blocks me"],
      ["Critical"],
      "What to do: Show one day at a time on “Screen 2 · 390 px”.",
      "Opinion in 95 s · $0.45",
    ],
    [
      "it",
      ["Schermata 1 · 1440 px", "Schermata 2 · 390 px"],
      ["Funziona per me", "Funziona per me", "Mi rallenta", "Mi blocca"],
      ["Critica"],
      "Cosa fare: Show one day at a time on «Schermata 2 · 390 px».",
      "Parere in 95 s · 0,45 USD",
    ],
  ] as const)(
    "gives the verdict of every twin on every screen of a web page, with names instead of codes (%s)",
    async (locale, screens, verdicts, severities, action, cost) => {
      const wrapper = mountPanel({ locale, api: fakeApi([PAGE_RUN]) });
      await open(wrapper);

      expect(texts(wrapper, "design-critique-screen-label")).toEqual(screens);
      expect(texts(wrapper, "design-critique-verdict")).toEqual(verdicts);
      const rows = wrapper
        .findAll('[data-testid="design-critique-screen"]')
        .map((screen) => screen.findAll("li").map((row) => row.text()));
      expect(rows).toEqual([
        [`Giulia: ${verdicts[0]}`, `Marco: ${verdicts[1]}`],
        [`Giulia: ${verdicts[2]}`, `Marco: ${verdicts[3]}`],
      ]);
      expect(texts(wrapper, "design-critique-verdict-twin")).toEqual([
        "Giulia",
        "Marco",
        "Giulia",
        "Marco",
      ]);
      expect(texts(wrapper, "design-critique-twin-name")).toEqual(["Giulia", "Marco"]);
      const marco = wrapper.findAll('[data-testid="design-critique-twin"]')[1];
      expect(
        marco?.findAll('[data-testid="design-critique-severity"]').map((item) => item.text()),
      ).toEqual(severities);
      expect(marco?.get('[data-testid="design-critique-place"]').text()).toBe(screens[1]);
      expect(marco?.get('[data-testid="design-critique-action"]').text()).toBe(action);
      expect(marco?.text()).not.toContain("SCR-002");
      expect(wrapper.get('[data-testid="design-critique-meta"]').text()).toContain(
        "https://gym.example.org/timetable",
      );
      expect(wrapper.get('[data-testid="design-critique-cost"]').text().replace(/\s+/g, " ")).toBe(
        cost,
      );
      expect(wrapper.findAll('[data-testid="design-critique-shot"]')).toHaveLength(2);
    },
  );

  it("derives a verdict from the observations when the Studio does not give it", async () => {
    const run: DesignCritiqueRunPayload = { ...PAGE_RUN, verdicts: [] };
    const wrapper = mountPanel({ api: fakeApi([run]) });
    await open(wrapper);

    expect(
      wrapper
        .findAll('[data-testid="design-critique-verdict"]')
        .map((item) => item.attributes("data-verdict")),
    ).toEqual(["SLOWS", "WORKS", "WORKS", "BLOCKS"]);
  });

  it("emits the redraw with the source and the title of the critique shown", async () => {
    const wrapper = mountPanel({ api: fakeApi([IMAGE_RUN]), redrawReady: true });
    await open(wrapper);

    const redraw = wrapper.get('[data-testid="design-critique-redraw"]');
    expect(redraw.text()).toBe("Redraw as a mockup");
    expect(redraw.attributes("aria-disabled")).toBeUndefined();
    expect(wrapper.get('[data-testid="design-critique-redraw-time"]').text()).toBe(
      "Estimated time: about 7 minutes.",
    );
    expect(wrapper.find('[data-testid="design-critique-redraw-missing"]').exists()).toBe(false);
    await redraw.trigger("click");

    expect(wrapper.emitted("redraw")).toEqual([[SOURCE_ID, "Booking page"]]);
  });

  it.each([
    [
      "en",
      "To redraw you need a Studio design with its mockup: prepare the design, then redraw.",
      "Another change of the design is in progress or waiting for your decision: redraw once it is settled.",
    ],
    [
      "it",
      "Per ridisegnare serve un design dello Studio con il suo mockup: prepara il design, poi ridisegna.",
      "Un'altra modifica del design è in corso o aspetta la tua decisione: ridisegna quando è conclusa.",
    ],
  ] as const)(
    "keeps the redraw unavailable and says why without a Studio mockup or during another change (%s)",
    async (locale, missing, busy) => {
      const wrapper = mountPanel({ locale, api: fakeApi([IMAGE_RUN]) });
      await open(wrapper);
      const redraw = () => wrapper.get('[data-testid="design-critique-redraw"]');

      const note = wrapper.get('[data-testid="design-critique-redraw-missing"]');
      expect(note.text()).toBe(missing);
      expect(redraw().attributes("aria-disabled")).toBe("true");
      expect(redraw().attributes("aria-describedby")?.split(" ")).toContain(note.attributes("id"));
      await redraw().trigger("click");

      await wrapper.setProps({ redrawReady: true, redrawBusy: true });
      expect(wrapper.find('[data-testid="design-critique-redraw-missing"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="design-critique-redraw-busy"]').text()).toBe(busy);
      expect(redraw().attributes("aria-disabled")).toBe("true");
      await redraw().trigger("click");

      expect(wrapper.emitted("redraw")).toBeUndefined();
    },
  );

  it("lists the earlier critiques, opens one and goes back to the latest", async () => {
    const api = fakeApi([IMAGE_RUN, PAGE_RUN]);
    const wrapper = mountPanel({ api, redrawReady: true, attach: true });
    await open(wrapper);

    const history = wrapper.get('[data-testid="design-critique-history"]');
    expect(history.element.tagName).toBe("DETAILS");
    expect(
      wrapper.get('[data-testid="design-critique-history-summary"] span:not([aria-hidden])').text(),
    ).toBe("Earlier critiques (1)");
    const item = wrapper.get('[data-testid="design-critique-history-item"]');
    expect(item.text()).toMatch(/^Gym timetable · /);
    expect(item.attributes("aria-current")).toBeUndefined();

    await item.trigger("click");
    await flushPromises();
    const heading = wrapper.get('[data-testid="design-critique-run"] h3');
    expect(heading.text()).toBe("Gym timetable");
    expect(document.activeElement).toBe(heading.element);
    expect(item.attributes("aria-current")).toBe("true");
    expect(api.shot).toHaveBeenCalledWith(PROJECT_ID, PAGE_ID, "SCR-002", "access-token");
    await wrapper.get('[data-testid="design-critique-redraw"]').trigger("click");
    expect(wrapper.emitted("redraw")).toEqual([[PAGE_ID, "Gym timetable"]]);

    await wrapper.get('[data-testid="design-critique-latest"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="design-critique-run"] h3').text()).toBe("Booking page");
    expect(wrapper.find('[data-testid="design-critique-latest"]').exists()).toBe(false);
  });

  it.each([
    [
      "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED",
      503,
      "The model connected to the Studio cannot look at images: whoever manages the Studio has to connect Claude Code.",
    ],
    [
      "DESIGN_CRITIQUE_TWINS_REQUIRED",
      409,
      "Approve the twins first: they are the ones who give the opinion.",
    ],
    [
      "DESIGN_REVIEWER_NOT_CONFIGURED",
      503,
      "The model that plays the twins is not connected, so the twins cannot give their opinion.",
    ],
    [
      "DESIGN_CRITIQUE_FAILED",
      502,
      "The opinion of the twins did not arrive. Try again in a moment.",
    ],
    [
      "TOO_MANY_GENERATIONS",
      429,
      "Too many generations are already running. Try again when one of them has finished.",
    ],
    ["invalid_authentication", 401, "Your session has expired. Log in again."],
    [null, 502, "The opinion of the twins did not arrive. Try again in a moment."],
  ] as const)("explains a refusal %s in plain words", async (code, status, message) => {
    const api = fakeApi();
    api.critique.mockRejectedValueOnce(
      new DesignCritiqueApiError("The design critique request failed", {
        status,
        code,
        payload: code === null ? null : { detail: { code } },
      }),
    );
    const wrapper = mountPanel({ api });
    await open(wrapper);

    await choose(wrapper, image());
    await wrapper.get('[data-testid="design-critique-ask"]').trigger("click");
    await flushPromises();

    const error = wrapper.get('[data-testid="design-critique-error"]');
    expect(error.text()).toBe(message);
    expect(error.attributes("role")).toBe("alert");
    expect(error.text()).not.toMatch(/[A-Z]+_[A-Z]+/);
    expect(wrapper.get('[data-testid="design-critique-status"]').text()).toBe("");
    expect(wrapper.find('[data-testid="design-critique-run"]').exists()).toBe(false);
    expect(wrapper.emitted("critiqued")).toBeUndefined();
  });

  it("says when a screenshot cannot be shown", async () => {
    const api = fakeApi([IMAGE_RUN]);
    api.shot.mockRejectedValueOnce(
      new DesignCritiqueApiError("The design critique request failed", {
        status: 404,
        code: "DESIGN_CRITIQUE_SOURCE_NOT_FOUND",
        payload: null,
      }),
    );
    const wrapper = mountPanel({ api, locale: "it" });
    await open(wrapper);

    expect(wrapper.find('[data-testid="design-critique-shot"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="design-critique-shot-missing"]').text()).toBe(
      "L'anteprima di questa schermata non si può mostrare.",
    );
  });

  it("revokes the addresses of the screenshots when it goes away", async () => {
    const wrapper = mountPanel({ api: fakeApi([IMAGE_RUN]) });
    await open(wrapper);
    expect(wrapper.get('[data-testid="design-critique-shot"]').attributes("src")).toBe(
      "blob:shot-1",
    );
    expect(revokeObjectURL).not.toHaveBeenCalled();

    mounted.pop()?.unmount();

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:shot-1");
  });

  it.each(["en", "it"] as const)(
    "has no axe violations, closed and with an opinion shown (%s)",
    async (locale) => {
      const wrapper = mountPanel({
        locale,
        api: fakeApi([PAGE_RUN, IMAGE_RUN]),
        twinsReady: false,
      });
      await expectAccessible(wrapper.element);

      await open(wrapper);
      await choose(wrapper, image("logo.gif", "image/gif"));
      const history = wrapper.get('[data-testid="design-critique-history"]');
      (history.element as HTMLDetailsElement).open = true;
      await history.trigger("toggle");

      await expectAccessible(wrapper.element);
    },
  );
});
