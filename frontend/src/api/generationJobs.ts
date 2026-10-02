import { ApiRequestError } from "./requestError";

import type {
  GenerationFailurePayload,
  GenerationJobKind,
  GenerationJobPayload,
  GenerationJobResponsePayload,
  GenerationJobStage,
  GenerationJobStatus,
  GenerationOperation,
  MockupIssuePayload,
} from "../types/designMockups";

const DEFAULT_API_BASE_PATH = "/api/v1";
const ACCEPTED = 202;
const NULL_BODY_STATUSES: ReadonlySet<number> = new Set([204, 205, 304]);

export const RESPOND_ASYNC = "respond-async";
export const FAST_POLL_INTERVAL_MILLISECONDS = 2000;
export const FAST_POLL_WINDOW_MILLISECONDS = 30 * 1000;
export const SLOW_POLL_INTERVAL_MILLISECONDS = 3000;
export const POLL_LIMIT_MILLISECONDS = 20 * 60 * 1000;

export const GENERATION_JOB_NOT_FOUND = "GENERATION_JOB_NOT_FOUND";
export const GENERATION_JOB_CANCELLED = "GENERATION_JOB_CANCELLED";
export const GENERATION_POLL_TIMEOUT = "GENERATION_POLL_TIMEOUT";
export const GENERATION_FAILED = "GENERATION_FAILED";
export const INVALID_API_RESPONSE = "INVALID_API_RESPONSE";

export const GENERATION_OPERATIONS: readonly GenerationOperation[] = [
  "MOCKUP",
  "ITERATION",
  "PERSONA_PROPOSAL",
  "USER_TWIN_GENERATION",
  "REQUIREMENTS_PROPOSAL",
  "REQUIREMENTS_CHANGE",
  "DESIGN_PROPOSAL",
  "DESIGN_REGENERATION",
  "DESIGN_EVALUATION",
  "DISCUSSION_START",
  "DISCUSSION_ROUND",
  "CODE_CHANGE_REVIEW",
  "TEST_PLAN",
  "TEST_REVIEW",
  "TWIN_UPDATE",
];

const JOB_KINDS: readonly GenerationJobKind[] = ["MOCKUP", "ITERATION", "REQUEST"];
const JOB_STATUSES: readonly GenerationJobStatus[] = ["RUNNING", "SUCCEEDED", "REJECTED", "FAILED"];
const JOB_STAGES: readonly GenerationJobStage[] = ["GENERATING", "VALIDATING", "RETRYING"];

export interface GenerationRequestJob extends Omit<
  GenerationJobPayload,
  "operation" | "response" | "result"
> {
  operation: GenerationOperation;
  response: GenerationJobResponsePayload | null;
}

export type GenerationEnd = "finished" | "lost" | "expired" | "released";

export interface GenerationJobEvent {
  projectId: string;
  job: GenerationRequestJob;
  following: boolean;
  ended: GenerationEnd | null;
}

export type GenerationJobListener = (event: GenerationJobEvent) => void;

export interface GenerationRequestOptions {
  fetchImpl: typeof fetch;
  basePath: string;
  projectId: string;
}

export interface GenerationJobsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class GenerationJobsApiError extends ApiRequestError {}

export interface GenerationJobsApi {
  job(projectId: string, jobId: string, accessToken: string): Promise<GenerationRequestJob>;
  list(
    projectId: string,
    accessToken: string,
    status?: GenerationJobStatus,
  ): Promise<GenerationRequestJob[]>;
}

interface Outcome {
  status: number;
  body: string | null;
}

interface FollowedGeneration {
  key: string;
  projectId: string;
  jobUrl: string;
  since: number;
  job: GenerationRequestJob;
  outcome: Promise<Outcome> | null;
}

type Reading =
  | { kind: "retry" }
  | { kind: "lost" }
  | { kind: "refused"; outcome: Outcome }
  | { kind: "job"; job: GenerationRequestJob };

const followed = new Map<string, FollowedGeneration>();
const listeners = new Set<GenerationJobListener>();

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function oneOf<T extends string>(values: readonly T[], value: unknown): T | null {
  return values.find((candidate) => candidate === value) ?? null;
}

function isHttpStatus(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 200 && value <= 599;
}

function responseOf(value: unknown): GenerationJobResponsePayload | null {
  if (!isRecord(value) || typeof value.status_code !== "number") {
    return null;
  }

  return { status_code: value.status_code, body: value.body ?? null };
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function reasonOf(value: unknown): MockupIssuePayload | null {
  if (!isRecord(value) || typeof value.code !== "string") {
    return null;
  }

  return {
    code: value.code,
    screen_code: optionalText(value.screen_code),
    detail: optionalText(value.detail) ?? "",
  };
}

function failureOf(value: unknown): GenerationFailurePayload | null {
  if (!isRecord(value) || typeof value.code !== "string") {
    return null;
  }

  const reasons = Array.isArray(value.reasons) ? value.reasons : [];

  return {
    code: value.code,
    reasons: reasons
      .map((reason) => reasonOf(reason))
      .filter((reason): reason is MockupIssuePayload => reason !== null),
  };
}

export function generationJobOf(value: unknown): GenerationRequestJob | null {
  if (!isRecord(value) || typeof value.job_id !== "string" || value.job_id.length === 0) {
    return null;
  }

  const status = oneOf(JOB_STATUSES, value.status);
  const kind = oneOf(JOB_KINDS, value.kind ?? "REQUEST");
  const operation =
    oneOf(GENERATION_OPERATIONS, value.operation) ??
    (kind === "MOCKUP" || kind === "ITERATION" ? kind : null);

  if (status === null || kind === null || operation === null) {
    return null;
  }

  if (typeof value.started_at !== "string") {
    return null;
  }

  return {
    job_id: value.job_id,
    kind,
    operation,
    status,
    stage: oneOf(JOB_STAGES, value.stage),
    attempt: typeof value.attempt === "number" ? value.attempt : 1,
    started_at: value.started_at,
    finished_at: optionalText(value.finished_at),
    alternative_id: optionalText(value.alternative_id),
    failure: failureOf(value.failure),
    response: responseOf(value.response),
  };
}

export function isGenerationLost(code: string | null | undefined): boolean {
  return code === GENERATION_JOB_NOT_FOUND || code === GENERATION_JOB_CANCELLED;
}

export function isGenerationInterrupted(code: string | null | undefined): boolean {
  return isGenerationLost(code) || code === GENERATION_POLL_TIMEOUT;
}

export function pollInterval(elapsedMilliseconds: number): number {
  return elapsedMilliseconds < FAST_POLL_WINDOW_MILLISECONDS
    ? FAST_POLL_INTERVAL_MILLISECONDS
    : SLOW_POLL_INTERVAL_MILLISECONDS;
}

export function pause(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

export function isTransientStatus(status: number | null): boolean {
  return status === null || status === 0 || status === 408 || status === 429 || status >= 500;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Generation Jobs API base path must not be empty");
  }

  return normalized;
}

export function generationJobsPath(basePath: string, projectId: string): string {
  return `${normalizedBasePath(basePath)}/projects/${encodeURIComponent(projectId)}/generation-jobs`;
}

function requestKey(url: string, init: RequestInit): string {
  return [init.method ?? "GET", url, typeof init.body === "string" ? init.body : ""].join("\n");
}

function preferring(headers: HeadersInit | undefined): HeadersInit {
  if (headers instanceof Headers) {
    const copy = new Headers(headers);
    copy.set("Prefer", RESPOND_ASYNC);
    return copy;
  }

  if (Array.isArray(headers)) {
    const preference: [string, string] = ["Prefer", RESPOND_ASYNC];
    return [...headers, preference];
  }

  return { ...headers, Prefer: RESPOND_ASYNC };
}

function authorizationOf(init: RequestInit): string | null {
  return new Headers(init.headers).get("Authorization");
}

function pollHeaders(authorization: string | null): Record<string, string> {
  return authorization === null
    ? { Accept: "application/json" }
    : { Accept: "application/json", Authorization: authorization };
}

async function bodyText(response: Response): Promise<string | null> {
  try {
    return await response.text();
  } catch {
    return null;
  }
}

function parsed(text: string | null): unknown {
  if (text === null || text.trim().length === 0) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function errorOutcome(status: number, code: string): Outcome {
  return { status, body: JSON.stringify({ detail: { code } }) };
}

function serializedBody(body: unknown): string | null {
  if (body === null || body === undefined) {
    return null;
  }

  return typeof body === "string" ? body : JSON.stringify(body);
}

function jobOutcome(job: GenerationRequestJob): Outcome {
  if (job.response !== null) {
    return isHttpStatus(job.response.status_code)
      ? { status: job.response.status_code, body: serializedBody(job.response.body) }
      : errorOutcome(502, INVALID_API_RESPONSE);
  }

  return job.failure === null
    ? errorOutcome(502, INVALID_API_RESPONSE)
    : errorOutcome(500, job.failure.code);
}

function toResponse(outcome: Outcome): Response {
  return new Response(NULL_BODY_STATUSES.has(outcome.status) ? null : outcome.body, {
    status: outcome.status,
    headers: { "Content-Type": "application/json" },
  });
}

function publish(entry: FollowedGeneration, ended: GenerationEnd | null): void {
  const event: GenerationJobEvent = {
    projectId: entry.projectId,
    job: entry.job,
    following: ended === null,
    ended,
  };

  for (const listener of [...listeners]) {
    try {
      listener(event);
    } catch {
      continue;
    }
  }
}

function forget(entry: FollowedGeneration, ended: GenerationEnd): void {
  if (followed.get(entry.key) === entry) {
    followed.delete(entry.key);
  }

  publish(entry, ended);
}

function isExpired(entry: FollowedGeneration): boolean {
  return Date.now() - entry.since >= POLL_LIMIT_MILLISECONDS;
}

function knownGeneration(key: string): FollowedGeneration | null {
  const entry = followed.get(key);

  if (entry === undefined) {
    return null;
  }

  if (entry.outcome === null && isExpired(entry)) {
    forget(entry, "expired");
    return null;
  }

  return entry;
}

async function readJob(
  entry: FollowedGeneration,
  authorization: string | null,
  fetchImpl: typeof fetch,
): Promise<Reading> {
  let response: Response;

  try {
    response = await fetchImpl(entry.jobUrl, {
      method: "GET",
      headers: pollHeaders(authorization),
      credentials: "include",
    });
  } catch {
    return { kind: "retry" };
  }

  if (response.status === 404) {
    return { kind: "lost" };
  }

  if (isTransientStatus(response.status)) {
    return { kind: "retry" };
  }

  const text = await bodyText(response);

  if (!response.ok) {
    return { kind: "refused", outcome: { status: response.status, body: text } };
  }

  const job = generationJobOf(parsed(text));

  return job === null || job.job_id !== entry.job.job_id ? { kind: "retry" } : { kind: "job", job };
}

async function watch(
  entry: FollowedGeneration,
  authorization: string | null,
  fetchImpl: typeof fetch,
): Promise<Outcome> {
  for (;;) {
    await pause(pollInterval(Date.now() - entry.since));

    if (isExpired(entry)) {
      forget(entry, "expired");
      return errorOutcome(504, GENERATION_POLL_TIMEOUT);
    }

    const reading = await readJob(entry, authorization, fetchImpl);

    if (reading.kind === "retry") {
      continue;
    }

    if (reading.kind === "lost") {
      forget(entry, "lost");
      return errorOutcome(404, GENERATION_JOB_NOT_FOUND);
    }

    if (reading.kind === "refused") {
      publish(entry, "released");
      return reading.outcome;
    }

    entry.job = reading.job;

    if (reading.job.status === "RUNNING") {
      publish(entry, null);
      continue;
    }

    forget(entry, "finished");
    return jobOutcome(reading.job);
  }
}

function follow(
  entry: FollowedGeneration,
  authorization: string | null,
  fetchImpl: typeof fetch,
): Promise<Response> {
  let outcome = entry.outcome;

  if (outcome === null) {
    const started = watch(entry, authorization, fetchImpl);
    const release = () => {
      if (entry.outcome === started) {
        entry.outcome = null;
      }
    };

    entry.outcome = started;
    started.then(release, release);
    outcome = started;
    publish(entry, null);
  }

  return outcome.then(toResponse);
}

export async function sendGeneration(
  url: string,
  init: RequestInit,
  options: GenerationRequestOptions,
): Promise<Response> {
  const { fetchImpl } = options;
  const key = requestKey(url, init);
  const authorization = authorizationOf(init);
  const known = knownGeneration(key);

  if (known !== null) {
    return follow(known, authorization, fetchImpl);
  }

  const response = await fetchImpl(url, { ...init, headers: preferring(init.headers) });

  if (response.status !== ACCEPTED) {
    return response;
  }

  const job = generationJobOf(parsed(await bodyText(response)));

  if (job === null) {
    return toResponse(errorOutcome(502, INVALID_API_RESPONSE));
  }

  const racing = followed.get(key);

  if (racing !== undefined && racing.job.job_id === job.job_id) {
    return follow(racing, authorization, fetchImpl);
  }

  const entry: FollowedGeneration = {
    key,
    projectId: options.projectId,
    jobUrl: `${generationJobsPath(options.basePath, options.projectId)}/${encodeURIComponent(job.job_id)}`,
    since: Date.now(),
    job,
    outcome: null,
  };

  if (job.status !== "RUNNING") {
    publish(entry, "finished");
    return toResponse(jobOutcome(job));
  }

  followed.set(key, entry);
  return follow(entry, authorization, fetchImpl);
}

export function onFollowedGenerationJob(listener: GenerationJobListener): () => void {
  listeners.add(listener);

  return () => {
    listeners.delete(listener);
  };
}

export function followedGenerationJobs(): GenerationJobEvent[] {
  return [...followed.values()]
    .filter((entry) => entry.outcome !== null)
    .map((entry) => ({ projectId: entry.projectId, job: entry.job, following: true, ended: null }));
}

export function clearFollowedGenerations(): void {
  followed.clear();
}

function errorCode(payload: unknown): string | null {
  if (!isRecord(payload)) {
    return null;
  }

  if (typeof payload.detail === "string") {
    return payload.detail;
  }

  return isRecord(payload.detail) && typeof payload.detail.code === "string"
    ? payload.detail.code
    : null;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new GenerationJobsApiError("Authentication is required", {
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
      payload: null,
    });
  }

  return normalized;
}

function invalidResponse(status: number, payload: unknown): GenerationJobsApiError {
  return new GenerationJobsApiError("The Generation Jobs API returned an invalid answer", {
    status,
    code: INVALID_API_RESPONSE,
    payload,
  });
}

export function createGenerationJobsApi(options: GenerationJobsApiOptions = {}): GenerationJobsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  async function read(path: string, accessToken: string): Promise<unknown> {
    const token = requiredAccessToken(accessToken);
    const fetchImpl = options.fetchImpl ?? globalThis.fetch;
    const response = await fetchImpl(path, {
      method: "GET",
      headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
      credentials: "include",
    });
    const text = await bodyText(response);
    const payload = parsed(text);

    if (!response.ok) {
      const code = errorCode(payload);

      throw new GenerationJobsApiError(
        code ?? `Generation Jobs API request failed with status ${response.status}`,
        { status: response.status, code, payload: payload ?? text },
      );
    }

    return payload;
  }

  return {
    async job(projectId, jobId, accessToken) {
      const payload = await read(
        `${generationJobsPath(basePath, projectId)}/${encodeURIComponent(jobId)}`,
        accessToken,
      );
      const job = generationJobOf(payload);

      if (job === null) {
        throw invalidResponse(200, payload);
      }

      return job;
    },

    async list(projectId, accessToken, status) {
      const path = generationJobsPath(basePath, projectId);
      const payload = await read(
        status === undefined ? path : `${path}?status=${encodeURIComponent(status)}`,
        accessToken,
      );

      if (!isRecord(payload) || !Array.isArray(payload.items)) {
        throw invalidResponse(200, payload);
      }

      return payload.items
        .map((item) => generationJobOf(item))
        .filter((job): job is GenerationRequestJob => job !== null);
    },
  };
}

export const generationJobsApi = createGenerationJobsApi();
