import { describe, expect, it, vi } from "vitest";
import { createHumanValidationApi } from "./humanValidation";
import {
  operationalHypothesis,
  validationOutcome,
  validationOverview,
  validationWalkthrough,
} from "../test/humanValidationFixtures";

const response = (payload: unknown, status = 200) =>
  ({ ok: status < 400, status, json: async () => payload }) as Response;
const input = {
  candidate_key: "claim:key",
  twin_key: "twin:key",
  scenario_key: "scenario:key",
  design_key: "design:key",
  question: "Owner question",
  observe: ["Owner observation"],
  limitations: "Synthetic contract fixture",
};

describe("Human validation API", () => {
  it("reads overview and an exact scenario context without sending a body", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response(validationOverview()))
      .mockResolvedValueOnce(response(validationWalkthrough()));
    const api = createHumanValidationApi({ fetchImpl });
    await api.overview("project/a", " token ");
    await api.walkthrough(
      "project/a",
      "SCENARIO:key",
      { alternativeId: "alternative/a", documentHash: "hash" },
      "token",
    );
    expect(fetchImpl.mock.calls[0]?.[0]).toBe("/api/v1/projects/project%2Fa/validation");
    expect(fetchImpl.mock.calls[1]?.[0]).toBe(
      "/api/v1/projects/project%2Fa/validation/walkthrough?scenario_key=SCENARIO%3Akey&alternative_id=alternative%2Fa&document_hash=hash",
    );
    for (const [, init] of fetchImpl.mock.calls)
      expect(init).toEqual({
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json", Authorization: "Bearer token" },
      });
  });

  it("sends only owner completed hypothesis and exact revision base to the authorised write routes", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        response({ status: "HYPOTHESIS_SAVED", hypothesis: operationalHypothesis() }, 201),
      )
      .mockResolvedValueOnce(
        response(
          {
            status: "HYPOTHESIS_REVISED",
            hypothesis: operationalHypothesis({ version_number: 2 }),
          },
          201,
        ),
      );
    const api = createHumanValidationApi({ fetchImpl });
    await api.createHypothesis("project", input, "token");
    const revised = {
      ...input,
      based_on_version_number: 1,
      based_on_content_hash: "original-hash",
    };
    await api.reviseHypothesis("project", "hypothesis/a", revised, "token");
    expect(fetchImpl.mock.calls[0]?.[0]).toBe("/api/v1/projects/project/validation/hypotheses");
    expect(fetchImpl.mock.calls[1]?.[0]).toBe(
      "/api/v1/projects/project/validation/hypotheses/hypothesis%2Fa/versions",
    );
    expect(JSON.parse(fetchImpl.mock.calls[1]?.[1].body)).toEqual(revised);
  });

  it("preserves quote whitespace and source version in an outcome without a generation request", async () => {
    const outcome = validationOutcome();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ status: "VALIDATION_OUTCOME_RECORDED", outcome }, 201));
    const api = createHumanValidationApi({ fetchImpl });
    const body = {
      hypothesis_id: outcome.hypothesis_id,
      hypothesis_version_number: 1,
      hypothesis_content_hash: outcome.hypothesis_content_hash,
      session_ref: "SYN-001",
      session_kind: outcome.session_kind,
      outcome: outcome.outcome,
      coverage: outcome.coverage,
      limitations: outcome.limitations,
      evidence_id: outcome.evidence_id,
      evidence_version: 1,
      quote: outcome.citation.quote,
      line: 1,
    };
    await api.recordOutcome("project", body, "token");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls[0]?.[0]).toBe("/api/v1/projects/project/validation/outcomes");
    expect(JSON.parse(fetchImpl.mock.calls[0]?.[1].body)).toEqual(body);
  });

  it.each([404, 409, 422])(
    "retains the %s machine code without copying submitted source text into errors",
    async (status) => {
      const fetchImpl = vi
        .fn()
        .mockResolvedValue(
          response(
            { detail: { code: "VALIDATION_SOURCE_RETIRED", source_text: "private" } },
            status,
          ),
        );
      await expect(
        createHumanValidationApi({ fetchImpl }).overview("project", "token"),
      ).rejects.toMatchObject({ status, code: "VALIDATION_SOURCE_RETIRED", payload: null });
    },
  );

  it("rejects absent authentication and malformed successful documents", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ kind: "orchestwin.human-validation", schema_version: 2 }));
    const api = createHumanValidationApi({ fetchImpl });
    await expect(api.overview("project", " ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    await expect(api.overview("project", "token")).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
    });
  });
});
