import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createDesignOpinionsApi, DesignOpinionsApiError } from "./designOpinions";
import {
  clearFollowedGenerations,
  GENERATION_POLL_TIMEOUT,
  generationJobOf,
  INVALID_API_RESPONSE,
  POLL_LIMIT_MILLISECONDS,
} from "./generationJobs";
import type { ChangeOpinionRun, DesignOpinionRequest } from "../types/designOpinions";

const PROJECT = "project 1";
const OPINIONS_URL = "/api/v1/projects/project%201/design/opinions";
const JOB_ID = "00000000-0000-4000-8000-0000000000aa";
const JOB_URL = `/api/v1/projects/project%201/generation-jobs/${JOB_ID}`;

const BODY: DesignOpinionRequest = {
  design_version_id: "00000000-0000-4000-8000-000000000001",
  design_content_hash: "a".repeat(64),
  request: "Rendi la barra rossa con il testo blu",
  target: {
    screen_code: "SCR-001",
    element_code: "ELM-018",
    label: "Forno Ravasi",
    html: "<a href='#SCR-002'>Forno Ravasi</a>",
  },
  locale: "it-IT",
};

const RUN: ChangeOpinionRun = {
  run_id: "00000000-0000-4000-8000-0000000000bb",
  design_version_id: BODY.design_version_id,
  design_content_hash: BODY.design_content_hash,
  design_version_number: 7,
  request: BODY.request,
  target: BODY.target,
  locale: "it-IT",
  requested_at: "2026-10-12T10:00:00+00:00",
  opinions: [
    {
      twin_id: "00000000-0000-4000-8000-0000000000c1",
      twin_version: 2,
      twin_name: "Giulia",
      verdict: "BLOCKS",
      why: "Il testo blu sulla barra rossa non si legge.",
      what_to_do: "Tieni il testo bianco sulla barra rossa.",
      try_this: "Rendi la barra rossa con il testo bianco",
      profile_keys: ["goals"],
      confidence: 0.8,
      generation_id: "00000000-0000-4000-8000-0000000000d1",
    },
  ],
  contrast: {
    mode: "LIGHT",
    text_threshold: 4.5,
    large_text_threshold: 3,
    control_border_threshold: 3,
  },
  cost_microusd: null,
};

interface JobAnswer {
  status_code: number;
  body: unknown;
}

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function job(answer: JobAnswer | null) {
  return {
    job_id: JOB_ID,
    kind: "REQUEST",
    operation: "DESIGN_CHANGE_OPINION",
    status: answer === null ? "RUNNING" : answer.status_code < 400 ? "SUCCEEDED" : "FAILED",
    stage: answer === null ? "GENERATING" : null,
    attempt: 1,
    started_at: "2026-10-12T10:00:00+00:00",
    finished_at: answer === null ? null : "2026-10-12T10:01:30+00:00",
    alternative_id: null,
    result: null,
    failure: null,
    response: answer,
  };
}

function server(answer: JobAnswer | null, readings = 1) {
  const times: number[] = [];
  const startedAt = Date.now();
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void input;

    if (init?.method === "POST") {
      return response(202, job(null));
    }

    times.push(Date.now() - startedAt);
    return response(200, job(times.length < readings ? null : answer));
  });

  return { fetchImpl, times };
}

function calls(fetchImpl: ReturnType<typeof server>["fetchImpl"], method: "GET" | "POST") {
  return fetchImpl.mock.calls.filter(([, init]) => init?.method === method);
}

describe("design opinions api", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    clearFollowedGenerations();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("asks the twins in the background and resolves with the opinions they gave", async () => {
    const { fetchImpl } = server({ status_code: 201, body: RUN });
    const api = createDesignOpinionsApi({ fetchImpl });

    const pending = api.ask(PROJECT, BODY, "token");
    await vi.advanceTimersByTimeAsync(1999);
    expect(calls(fetchImpl, "GET")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);

    await expect(pending).resolves.toEqual(RUN);
    const [path, init] = calls(fetchImpl, "POST")[0] ?? [];
    expect(String(path)).toBe(OPINIONS_URL);
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toEqual({
      Accept: "application/json",
      Authorization: "Bearer token",
      "Content-Type": "application/json",
      Prefer: "respond-async",
    });
    expect(JSON.parse(String(init?.body))).toEqual(BODY);
    const readings = calls(fetchImpl, "GET");
    expect(readings.map(([url]) => String(url))).toEqual([JOB_URL]);
    expect(readings[0]?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: "Bearer token",
    });
  });

  it("reads the job every two seconds for thirty seconds and every three seconds afterwards", async () => {
    const { fetchImpl, times } = server({ status_code: 201, body: RUN }, 16);

    const pending = createDesignOpinionsApi({ fetchImpl }).ask(PROJECT, BODY, "token");
    await vi.advanceTimersByTimeAsync(33_000);

    await expect(pending).resolves.toEqual(RUN);
    expect(times).toEqual([
      ...Array.from({ length: 15 }, (_, index) => (index + 1) * 2000),
      33_000,
    ]);
    expect(calls(fetchImpl, "POST")).toHaveLength(1);
  });

  it("stops waiting after twenty minutes without asking twice", async () => {
    const { fetchImpl } = server(null);

    const pending = createDesignOpinionsApi({ fetchImpl })
      .ask(PROJECT, BODY, "token")
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(POLL_LIMIT_MILLISECONDS + 3000);
    const failure = await pending;

    expect(failure).toBeInstanceOf(DesignOpinionsApiError);
    expect(failure).toMatchObject({ status: 504, code: GENERATION_POLL_TIMEOUT });
    expect(calls(fetchImpl, "POST")).toHaveLength(1);
  });

  it("throws the refusal carried by the job with its status and its code", async () => {
    const refusal = { detail: { code: "DESIGN_REVIEWER_NOT_CONFIGURED" } };
    const { fetchImpl } = server({ status_code: 503, body: refusal });

    const pending = createDesignOpinionsApi({ fetchImpl })
      .ask(PROJECT, BODY, "token")
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(2000);
    const failure = await pending;

    expect(failure).toBeInstanceOf(DesignOpinionsApiError);
    expect(failure).toMatchObject({
      status: 503,
      code: "DESIGN_REVIEWER_NOT_CONFIGURED",
      payload: refusal,
    });
  });

  it("knows the job of an opinion among the generation jobs", () => {
    expect(generationJobOf(job(null))?.operation).toBe("DESIGN_CHANGE_OPINION");
  });

  it("keeps the opinions of a synchronous answer", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => response(201, RUN));

    await expect(
      createDesignOpinionsApi({ fetchImpl }).ask(PROJECT, BODY, "token"),
    ).resolves.toEqual(RUN);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("refuses an answer that is not a set of opinions", async () => {
    const api = createDesignOpinionsApi({
      fetchImpl: async () => response(201, { status: "RECORDED" }),
    });

    await expect(api.ask(PROJECT, BODY, "token")).rejects.toMatchObject({
      status: 201,
      code: INVALID_API_RESPONSE,
    });
  });

  it("requires an access token and sends nothing without it", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createDesignOpinionsApi({ fetchImpl });

    for (const token of [" ", ""]) {
      const refusal = api.ask(PROJECT, BODY, token);
      await expect(refusal).rejects.toBeInstanceOf(DesignOpinionsApiError);
      await expect(refusal).rejects.toMatchObject({ code: "ACCESS_TOKEN_REQUIRED" });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
