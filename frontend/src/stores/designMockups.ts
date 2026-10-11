import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { designMockupsApi, type DesignMockupsApi } from "../api/designMockups";
import { designReviewPinsApi, type DesignReviewPinsApi } from "../api/designReviewPins";
import { isRecord } from "../api/http";
import type { DesignPackageVersionPayload } from "../types/design";
import type {
  DesignMockupCapabilitiesPayload,
  GenerationJobPayload,
  MockupDocumentPayload,
  MockupDocumentSource,
  MockupIssuePayload,
  MockupResultPayload,
  ReviewPinsPayload,
} from "../types/designMockups";
import {
  JobWatch,
  errorCodeOf,
  errorStatusOf,
  isFinishedStatus,
  isTransientError,
  pollingHolder,
  readSessionValue,
  writeSessionValue,
} from "./jobWatch";

export * from "./designMockupMessages";
export * from "./jobWatch";

export type AuthorizedMockupRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

export const GENERATION_POLL_TIMEOUT = "GENERATION_POLL_TIMEOUT";
export const GENERATION_JOB_NOT_FOUND = "GENERATION_JOB_NOT_FOUND";
export const GENERATION_STATUS_UNAVAILABLE = "GENERATION_STATUS_UNAVAILABLE";
export const GENERATION_START_FAILED = "GENERATION_START_FAILED";
export const MOCKUP_STATUS_UNAVAILABLE = "MOCKUP_STATUS_UNAVAILABLE";
export const MOCKUP_REJECTED = "MOCKUP_REJECTED";
export const GENERATION_FAILED = "GENERATION_FAILED";
export const INVALID_API_RESPONSE = "INVALID_API_RESPONSE";

export type MockupEntry =
  | { state: "idle" }
  | { state: "drawing"; job: GenerationJobPayload; startedAt: string }
  | { state: "ready"; result: MockupResultPayload }
  | {
      state: "rejected";
      code: string;
      reasons: MockupIssuePayload[];
      job: GenerationJobPayload | null;
    }
  | {
      state: "failed";
      code: string;
      reasons: MockupIssuePayload[];
      job: GenerationJobPayload | null;
    };

export type MockupEnsureOutcome =
  | "started"
  | "running"
  | "ready"
  | "earlier"
  | "applied"
  | "chosen"
  | "attempted"
  | "refused"
  | "failed"
  | "unavailable"
  | "missing"
  | "inactive";

export interface MockupDesignContext {
  projectId: string;
  versionId: string;
  contentHash: string;
  alternativeIds: string[];
  appliedAlternativeId: string | null;
}

export interface MockupRequestOptions {
  api?: DesignMockupsApi;
  signal?: AbortSignal;
  draw?: boolean;
}

export interface MockupDocumentOptions {
  source?: MockupDocumentSource;
  entryScreen?: string;
  revision?: string;
  api?: DesignMockupsApi;
  force?: boolean;
}

export interface MockupDocumentLookup {
  source?: MockupDocumentSource;
  entryScreen?: string;
  revision?: string;
}

export interface ReviewPinsOptions {
  api?: DesignReviewPinsApi;
  force?: boolean;
}

export interface ReviewDocumentOptions {
  entryScreen?: string;
  api?: DesignReviewPinsApi;
  force?: boolean;
}

interface RememberedJob {
  jobId: string;
  hash: string;
}

interface MockupMemory {
  requested: string[];
  drawn: string[];
  jobs: Record<string, RememberedJob>;
}

interface WatchAccess {
  authorize: AuthorizedMockupRequest;
  api: DesignMockupsApi;
}

const MEMORY_KEY = "orchestwin.designMockups";
const MEMORY_LIMIT = 200;
const IDLE: MockupEntry = Object.freeze({ state: "idle" });

function isRememberedJob(value: unknown): value is RememberedJob {
  return isRecord(value) && typeof value.jobId === "string" && typeof value.hash === "string";
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").slice(-MEMORY_LIMIT)
    : [];
}

function readMockupMemory(): MockupMemory {
  const value = readSessionValue(MEMORY_KEY);

  if (!isRecord(value)) {
    return { requested: [], drawn: [], jobs: {} };
  }

  const jobs = isRecord(value.jobs)
    ? Object.fromEntries(
        Object.entries(value.jobs)
          .filter((entry): entry is [string, RememberedJob] => isRememberedJob(entry[1]))
          .slice(-MEMORY_LIMIT),
      )
    : {};

  return { requested: stringList(value.requested), drawn: stringList(value.drawn), jobs };
}

function memoryKey(...parts: string[]): string {
  return parts.join("|");
}

function designContext(version: DesignPackageVersionPayload): MockupDesignContext {
  const packageValue = version.package;
  const generated = packageValue.generated_mockup ?? null;

  return {
    projectId: version.project_id,
    versionId: version.id,
    contentHash: version.content_hash,
    alternativeIds: packageValue.alternatives.map((alternative) => alternative.id),
    appliedAlternativeId: generated === null ? null : packageValue.owner_selected_alternative_id,
  };
}

function isGeneratedResult(result: MockupResultPayload): boolean {
  return (result.package.generated_mockup ?? null) !== null;
}

function failedEntry(
  code: string,
  job: GenerationJobPayload | null,
  reasons: MockupIssuePayload[] = [],
): MockupEntry {
  return { state: "failed", code, reasons, job };
}

function documentCacheKey(document: MockupDocumentPayload): string {
  return memoryKey(document.content_hash, document.entry_screen);
}

export const useDesignMockupsStore = defineStore("designMockups", () => {
  const projectId = ref<string | null>(null);
  const projectEpoch = ref(0);
  const design = ref<MockupDesignContext | null>(null);
  const capabilities = ref<DesignMockupCapabilitiesPayload | null>(null);
  const capabilitiesError = ref<string | null>(null);
  const entries = ref<Record<string, MockupEntry>>({});
  const checking = ref<Record<string, boolean>>({});
  const drawn = ref<Record<string, boolean>>({});
  const documents = ref<Record<string, MockupDocumentPayload>>({});
  const documentKeys = ref<Record<string, string>>({});
  const reviewPins = ref<Record<string, ReviewPinsPayload>>({});
  const reviewRevisions = ref<Record<string, number>>({});

  const memory = readMockupMemory();
  const watches = new Map<string, JobWatch>();
  const accesses = new Map<string, WatchAccess>();
  const inflight = new Map<
    string,
    { hash: string; draw: boolean; promise: Promise<MockupEnsureOutcome> }
  >();
  const prepared = new Set<string>();
  const documentRequests = new Map<string, Promise<MockupDocumentPayload>>();
  let capabilityRequest: Promise<DesignMockupCapabilitiesPayload | null> | null = null;

  const generatedMockupsEnabled = computed(() => capabilities.value?.generated_mockups === true);
  const iterationsEnabled = computed(() => capabilities.value?.iterations === true);
  const appliedAlternativeId = computed(() => design.value?.appliedAlternativeId ?? null);
  const isDrawing = computed(() =>
    Object.values(entries.value).some((value) => value.state === "drawing"),
  );

  function persistMemory(): void {
    writeSessionValue(MEMORY_KEY, {
      requested: memory.requested.slice(-MEMORY_LIMIT),
      drawn: memory.drawn.slice(-MEMORY_LIMIT),
      jobs: Object.fromEntries(Object.entries(memory.jobs).slice(-MEMORY_LIMIT)),
    });
  }

  function markRequested(project: string, hash: string, alternativeId: string): void {
    const key = memoryKey(project, hash, alternativeId);

    if (!memory.requested.includes(key)) {
      memory.requested.push(key);
      persistMemory();
    }
  }

  function isRequested(project: string, hash: string, alternativeId: string): boolean {
    return memory.requested.includes(memoryKey(project, hash, alternativeId));
  }

  function markDrawn(project: string, alternativeId: string): void {
    const key = memoryKey(project, alternativeId);

    if (projectId.value === project) {
      drawn.value[alternativeId] = true;
    }

    if (!memory.drawn.includes(key)) {
      memory.drawn.push(key);
      persistMemory();
    }
  }

  function isDrawn(project: string, alternativeId: string): boolean {
    return memory.drawn.includes(memoryKey(project, alternativeId));
  }

  function rememberJob(project: string, alternativeId: string, jobId: string, hash: string): void {
    memory.jobs[memoryKey(project, alternativeId)] = { jobId, hash };
    persistMemory();
  }

  function rememberedJob(project: string, alternativeId: string): RememberedJob | null {
    return memory.jobs[memoryKey(project, alternativeId)] ?? null;
  }

  function forgetJob(project: string, alternativeId: string): void {
    const key = memoryKey(project, alternativeId);

    if (key in memory.jobs) {
      delete memory.jobs[key];
      persistMemory();
    }
  }

  function drawnFromMemory(project: string): Record<string, boolean> {
    const prefix = memoryKey(project, "");

    return Object.fromEntries(
      memory.drawn
        .filter((key) => key.startsWith(prefix))
        .map((key) => [key.slice(prefix.length), true]),
    );
  }

  function isCurrentProject(project: string, epoch: number): boolean {
    return projectId.value === project && projectEpoch.value === epoch;
  }

  function isRelevant(project: string, epoch: number, alternativeId: string): boolean {
    return (
      isCurrentProject(project, epoch) &&
      design.value !== null &&
      design.value.alternativeIds.includes(alternativeId)
    );
  }

  function entry(alternativeId: string): MockupEntry {
    return entries.value[alternativeId] ?? IDLE;
  }

  function setEntry(alternativeId: string, value: MockupEntry): void {
    entries.value[alternativeId] = value;
  }

  function isChecking(alternativeId: string): boolean {
    return checking.value[alternativeId] === true;
  }

  function setChecking(alternativeId: string, value: boolean): void {
    if (value) {
      checking.value[alternativeId] = true;
    } else {
      delete checking.value[alternativeId];
    }
  }

  function drawnBefore(alternativeId: string): boolean {
    return drawn.value[alternativeId] === true;
  }

  function readiness(result: MockupResultPayload): MockupEnsureOutcome {
    return result.design_content_hash === design.value?.contentHash ? "ready" : "earlier";
  }

  function applicableResult(alternativeId: string): MockupResultPayload | null {
    const current = entry(alternativeId);
    const context = design.value;

    if (current.state !== "ready" || context === null) {
      return null;
    }

    return current.result.design_version_id === context.versionId &&
      current.result.design_content_hash === context.contentHash
      ? current.result
      : null;
  }

  function closeWatch(alternativeId: string): void {
    watches.get(alternativeId)?.close();
    watches.delete(alternativeId);
    accesses.delete(alternativeId);
  }

  function closeWatches(): void {
    for (const watch of watches.values()) {
      watch.close();
    }

    watches.clear();
    accesses.clear();
  }

  function acceptResult(project: string, alternativeId: string, result: MockupResultPayload): void {
    setEntry(alternativeId, { state: "ready", result });
    markDrawn(project, alternativeId);
    forgetJob(project, alternativeId);
  }

  function applyJob(project: string, alternativeId: string, job: GenerationJobPayload): void {
    if (job.status === "SUCCEEDED") {
      if (job.result === null) {
        setEntry(alternativeId, failedEntry(INVALID_API_RESPONSE, job));
      } else {
        acceptResult(project, alternativeId, job.result);
      }
      return;
    }

    if (job.status === "REJECTED") {
      setEntry(alternativeId, {
        state: "rejected",
        code: job.failure?.code ?? MOCKUP_REJECTED,
        reasons: job.failure?.reasons ?? [],
        job,
      });
      return;
    }

    if (job.status === "FAILED") {
      setEntry(
        alternativeId,
        failedEntry(job.failure?.code ?? GENERATION_FAILED, job, job.failure?.reasons ?? []),
      );
      return;
    }

    setEntry(alternativeId, { state: "drawing", job, startedAt: job.started_at });
  }

  function isTracking(
    alternativeId: string,
    jobId: string,
    project: string,
    epoch: number,
  ): boolean {
    const current = entry(alternativeId);

    return (
      isCurrentProject(project, epoch) &&
      current.state === "drawing" &&
      current.job.job_id === jobId
    );
  }

  async function jobLost(
    alternativeId: string,
    job: GenerationJobPayload,
    project: string,
    epoch: number,
    access: WatchAccess,
  ): Promise<void> {
    forgetJob(project, alternativeId);

    try {
      const latest = await access.authorize((token) =>
        access.api.latest(project, alternativeId, token),
      );

      if (isCurrentProject(project, epoch) && latest !== null) {
        acceptResult(project, alternativeId, latest);
        return;
      }
    } catch {
      if (isCurrentProject(project, epoch)) {
        setEntry(alternativeId, failedEntry(GENERATION_JOB_NOT_FOUND, job));
      }
      return;
    }

    if (isCurrentProject(project, epoch)) {
      setEntry(alternativeId, failedEntry(GENERATION_JOB_NOT_FOUND, job));
    }
  }

  async function poll(
    alternativeId: string,
    jobId: string,
    project: string,
    epoch: number,
  ): Promise<boolean> {
    const access = accesses.get(alternativeId);
    const current = entry(alternativeId);

    if (
      access === undefined ||
      current.state !== "drawing" ||
      !isTracking(alternativeId, jobId, project, epoch)
    ) {
      return true;
    }

    try {
      const job = await access.authorize((token) => access.api.job(project, jobId, token));

      if (!isTracking(alternativeId, jobId, project, epoch)) {
        return true;
      }

      applyJob(project, alternativeId, job);
      return isFinishedStatus(job.status);
    } catch (error) {
      if (!isTracking(alternativeId, jobId, project, epoch)) {
        return true;
      }

      if (errorStatusOf(error) === 404) {
        await jobLost(alternativeId, current.job, project, epoch, access);
        return true;
      }

      if (isTransientError(error)) {
        return false;
      }

      setEntry(
        alternativeId,
        failedEntry(errorCodeOf(error) ?? GENERATION_STATUS_UNAVAILABLE, current.job),
      );
      return true;
    }
  }

  function expire(alternativeId: string, jobId: string, project: string, epoch: number): void {
    const current = entry(alternativeId);

    if (current.state === "drawing" && isTracking(alternativeId, jobId, project, epoch)) {
      setEntry(alternativeId, failedEntry(GENERATION_POLL_TIMEOUT, current.job));
    }
  }

  function follow(
    alternativeId: string,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
    holder: AbortSignal | undefined,
  ): void {
    const current = entry(alternativeId);
    const project = projectId.value;

    if (current.state !== "drawing" || project === null) {
      return;
    }

    const jobId = current.job.job_id;
    const epoch = projectEpoch.value;
    let watch = watches.get(alternativeId);

    if (watch === undefined || watch.isClosed || watch.jobId !== jobId) {
      watch?.close();
      watch = new JobWatch(
        jobId,
        () => poll(alternativeId, jobId, project, epoch),
        () => expire(alternativeId, jobId, project, epoch),
      );
      watches.set(alternativeId, watch);
    }

    accesses.set(alternativeId, { authorize, api });
    watch.hold(holder);
  }

  function serialized(
    alternativeId: string,
    run: () => Promise<MockupEnsureOutcome>,
    draw: boolean,
  ): Promise<MockupEnsureOutcome> {
    const hash = design.value?.contentHash ?? "";
    const key = memoryKey(String(projectEpoch.value), alternativeId);
    const previous = inflight.get(key);

    if (previous !== undefined && previous.hash === hash && (previous.draw || !draw)) {
      return previous.promise;
    }

    const before: Promise<unknown> = previous?.promise ?? Promise.resolve();
    const promise = before.then(run, run);
    const tracked = { hash, draw, promise };
    const release = () => {
      if (inflight.get(key) === tracked) {
        inflight.delete(key);
      }
    };

    inflight.set(key, tracked);
    promise.then(release, release);
    return promise;
  }

  async function fetchCapabilities(
    project: string,
    epoch: number,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
  ): Promise<DesignMockupCapabilitiesPayload | null> {
    try {
      const payload = await authorize((token) => api.capabilities(project, token));

      if (isCurrentProject(project, epoch)) {
        capabilities.value = payload;
        capabilitiesError.value = null;
      }

      return payload;
    } catch (error) {
      if (isCurrentProject(project, epoch)) {
        capabilitiesError.value = errorCodeOf(error) ?? MOCKUP_STATUS_UNAVAILABLE;
      }

      return null;
    }
  }

  function loadCapabilities(
    authorize: AuthorizedMockupRequest,
    options: { api?: DesignMockupsApi; force?: boolean } = {},
  ): Promise<DesignMockupCapabilitiesPayload | null> {
    const project = projectId.value;

    if (project === null) {
      return Promise.resolve(null);
    }

    if (options.force !== true) {
      if (capabilities.value !== null) {
        return Promise.resolve(capabilities.value);
      }

      if (capabilityRequest !== null) {
        return capabilityRequest;
      }
    }

    const request = fetchCapabilities(
      project,
      projectEpoch.value,
      authorize,
      options.api ?? designMockupsApi,
    );
    const release = () => {
      if (capabilityRequest === request) {
        capabilityRequest = null;
      }
    };

    capabilityRequest = request;
    void request.then(release);
    return request;
  }

  async function generatedMockupsAvailable(
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
  ): Promise<boolean> {
    const loaded = await loadCapabilities(authorize, { api });

    return loaded?.generated_mockups === true;
  }

  async function readJob(
    project: string,
    jobId: string,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
  ): Promise<GenerationJobPayload | null> {
    try {
      return await authorize((token) => api.job(project, jobId, token));
    } catch (error) {
      if (errorStatusOf(error) === 404) {
        return null;
      }

      throw error;
    }
  }

  function documentRequestKey(
    alternativeId: string,
    source: MockupDocumentSource,
    entryScreen: string,
    revision: string | undefined,
  ): string {
    const current = entry(alternativeId);
    const computedRevision =
      source === "applied"
        ? (design.value?.contentHash ?? "none")
        : current.state === "ready"
          ? current.result.generation_id
          : "none";

    return memoryKey(alternativeId, source, entryScreen, revision ?? computedRevision);
  }

  function storeDocument(requestKey: string, document: MockupDocumentPayload): void {
    const cacheKey = documentCacheKey(document);

    documents.value[cacheKey] = document;
    documentKeys.value[requestKey] = cacheKey;
  }

  function cachedDocument(requestKey: string): MockupDocumentPayload | null {
    const cacheKey = documentKeys.value[requestKey];

    return cacheKey === undefined ? null : (documents.value[cacheKey] ?? null);
  }

  async function earlierMockupExists(
    alternativeId: string,
    project: string,
    epoch: number,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
  ): Promise<boolean> {
    try {
      const document = await authorize((token) =>
        api.document(project, { alternative_id: alternativeId, source: "latest" }, token),
      );

      if (isCurrentProject(project, epoch)) {
        storeDocument(documentRequestKey(alternativeId, "latest", "", undefined), document);
        markDrawn(project, alternativeId);
      }

      return true;
    } catch (error) {
      if (errorStatusOf(error) === 404) {
        return false;
      }

      throw error;
    }
  }

  async function start(
    alternativeId: string,
    context: MockupDesignContext,
    project: string,
    epoch: number,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
  ): Promise<MockupEnsureOutcome> {
    markRequested(project, context.contentHash, alternativeId);
    let job: GenerationJobPayload;

    try {
      job = await authorize((token) =>
        api.startJob(
          project,
          {
            design_version_id: context.versionId,
            design_content_hash: context.contentHash,
            alternative_id: alternativeId,
          },
          token,
        ),
      );
    } catch (error) {
      if (!isRelevant(project, epoch, alternativeId)) {
        return "inactive";
      }

      setEntry(alternativeId, failedEntry(errorCodeOf(error) ?? GENERATION_START_FAILED, null));
      return "refused";
    }

    markDrawn(project, alternativeId);
    rememberJob(project, alternativeId, job.job_id, context.contentHash);

    if (!isRelevant(project, epoch, alternativeId)) {
      return "inactive";
    }

    applyJob(project, alternativeId, job);
    return "started";
  }

  async function check(
    alternativeId: string,
    context: MockupDesignContext,
    project: string,
    epoch: number,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
    draw: boolean,
  ): Promise<MockupEnsureOutcome> {
    const remembered = rememberedJob(project, alternativeId);
    let finished: GenerationJobPayload | null = null;

    if (remembered !== null) {
      const job = await readJob(project, remembered.jobId, authorize, api);

      if (!isRelevant(project, epoch, alternativeId)) {
        return "inactive";
      }

      if (job === null) {
        forgetJob(project, alternativeId);
      } else if (job.status === "SUCCEEDED" && job.result !== null) {
        acceptResult(project, alternativeId, job.result);
        return readiness(job.result);
      } else if (isFinishedStatus(job.status)) {
        finished = job;
      } else {
        applyJob(project, alternativeId, job);
        return "running";
      }
    }

    const latest = await authorize((token) => api.latest(project, alternativeId, token));

    if (!isRelevant(project, epoch, alternativeId)) {
      return "inactive";
    }

    if (latest !== null) {
      acceptResult(project, alternativeId, latest);
      return readiness(latest);
    }

    if (finished !== null) {
      applyJob(project, alternativeId, finished);
      return "attempted";
    }

    if (isDrawn(project, alternativeId)) {
      return "earlier";
    }

    if (isRequested(project, context.contentHash, alternativeId)) {
      return "attempted";
    }

    if (await earlierMockupExists(alternativeId, project, epoch, authorize, api)) {
      return isRelevant(project, epoch, alternativeId) ? "earlier" : "inactive";
    }

    if (
      !isRelevant(project, epoch, alternativeId) ||
      design.value?.contentHash !== context.contentHash
    ) {
      return "inactive";
    }

    if (context.appliedAlternativeId !== null) {
      return "chosen";
    }

    if (!draw) {
      return "missing";
    }

    return start(alternativeId, context, project, epoch, authorize, api);
  }

  async function guarded(
    alternativeId: string,
    project: string,
    epoch: number,
    run: () => Promise<MockupEnsureOutcome>,
  ): Promise<MockupEnsureOutcome> {
    setChecking(alternativeId, true);

    try {
      return await run();
    } catch (error) {
      if (!isRelevant(project, epoch, alternativeId)) {
        return "inactive";
      }

      setEntry(alternativeId, failedEntry(errorCodeOf(error) ?? MOCKUP_STATUS_UNAVAILABLE, null));
      return "failed";
    } finally {
      if (isCurrentProject(project, epoch)) {
        setChecking(alternativeId, false);
      }
    }
  }

  async function runEnsure(
    alternativeId: string,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
    draw: boolean,
  ): Promise<MockupEnsureOutcome> {
    const project = projectId.value;
    const epoch = projectEpoch.value;

    if (project === null) {
      return "inactive";
    }

    const available = await generatedMockupsAvailable(authorize, api);
    const context = design.value;

    if (!isRelevant(project, epoch, alternativeId) || context === null) {
      return "inactive";
    }

    if (!available) {
      return "unavailable";
    }

    const current = entry(alternativeId);

    if (current.state === "drawing") {
      return "running";
    }

    if (context.appliedAlternativeId === alternativeId) {
      markDrawn(project, alternativeId);
      return "applied";
    }

    if (current.state === "ready") {
      return readiness(current.result);
    }

    if (
      (current.state === "rejected" || current.state === "failed") &&
      (isDrawn(project, alternativeId) || isRequested(project, context.contentHash, alternativeId))
    ) {
      return "attempted";
    }

    return guarded(alternativeId, project, epoch, () =>
      check(alternativeId, context, project, epoch, authorize, api, draw),
    );
  }

  async function redraw(
    alternativeId: string,
    context: MockupDesignContext,
    project: string,
    epoch: number,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
  ): Promise<MockupEnsureOutcome> {
    const current = entry(alternativeId);
    const knownJobId =
      (current.state === "rejected" || current.state === "failed") && current.job !== null
        ? current.job.job_id
        : (rememberedJob(project, alternativeId)?.jobId ?? null);

    if (knownJobId !== null) {
      const job = await readJob(project, knownJobId, authorize, api);

      if (!isRelevant(project, epoch, alternativeId)) {
        return "inactive";
      }

      if (job !== null && job.status === "SUCCEEDED" && job.result !== null) {
        acceptResult(project, alternativeId, job.result);
        return readiness(job.result);
      }

      if (job !== null && !isFinishedStatus(job.status)) {
        applyJob(project, alternativeId, job);
        return "running";
      }
    }

    const latest = await authorize((token) => api.latest(project, alternativeId, token));

    if (!isRelevant(project, epoch, alternativeId)) {
      return "inactive";
    }

    if (latest !== null && isGeneratedResult(latest)) {
      acceptResult(project, alternativeId, latest);
      return readiness(latest);
    }

    if (design.value?.contentHash !== context.contentHash) {
      return "inactive";
    }

    return start(alternativeId, context, project, epoch, authorize, api);
  }

  async function runRetry(
    alternativeId: string,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
  ): Promise<MockupEnsureOutcome> {
    const project = projectId.value;
    const epoch = projectEpoch.value;

    if (project === null) {
      return "inactive";
    }

    const available = await generatedMockupsAvailable(authorize, api);
    const context = design.value;

    if (!isRelevant(project, epoch, alternativeId) || context === null) {
      return "inactive";
    }

    if (!available) {
      return "unavailable";
    }

    const current = entry(alternativeId);

    if (current.state === "drawing") {
      return "running";
    }

    if (context.appliedAlternativeId === alternativeId) {
      return "applied";
    }

    if (
      current.state === "ready" &&
      isGeneratedResult(current.result) &&
      current.result.design_content_hash === context.contentHash
    ) {
      return "ready";
    }

    return guarded(alternativeId, project, epoch, () =>
      redraw(alternativeId, context, project, epoch, authorize, api),
    );
  }

  async function settled(
    alternativeId: string,
    run: () => Promise<MockupEnsureOutcome>,
    authorize: AuthorizedMockupRequest,
    api: DesignMockupsApi,
    holder: AbortSignal | undefined,
    draw: boolean,
  ): Promise<MockupEnsureOutcome> {
    const outcome = await serialized(alternativeId, run, draw);

    follow(alternativeId, authorize, api, holder);
    return outcome;
  }

  function ensure(
    alternativeId: string,
    authorize: AuthorizedMockupRequest,
    options: MockupRequestOptions = {},
  ): Promise<MockupEnsureOutcome> {
    const holder = pollingHolder(options.signal);
    const api = options.api ?? designMockupsApi;
    const draw = options.draw === true;

    return settled(
      alternativeId,
      () => runEnsure(alternativeId, authorize, api, draw),
      authorize,
      api,
      holder,
      draw,
    );
  }

  function retry(
    alternativeId: string,
    authorize: AuthorizedMockupRequest,
    options: MockupRequestOptions = {},
  ): Promise<MockupEnsureOutcome> {
    const holder = pollingHolder(options.signal);
    const api = options.api ?? designMockupsApi;

    return settled(
      alternativeId,
      () => runRetry(alternativeId, authorize, api),
      authorize,
      api,
      holder,
      true,
    );
  }

  function preparedKey(project: string, versionId: string, contentHash: string): string {
    return memoryKey(project, versionId, contentHash);
  }

  function markPrepared(project: string, versionId: string, contentHash: string): void {
    prepared.add(preparedKey(project, versionId, contentHash));
  }

  function wasPrepared(project: string, versionId: string, contentHash: string): boolean {
    return prepared.has(preparedKey(project, versionId, contentHash));
  }

  function documentFor(
    alternativeId: string,
    lookup: MockupDocumentLookup = {},
  ): MockupDocumentPayload | null {
    return cachedDocument(
      documentRequestKey(
        alternativeId,
        lookup.source ?? "latest",
        lookup.entryScreen ?? "",
        lookup.revision,
      ),
    );
  }

  function remember<T>(
    key: string,
    load: () => Promise<T>,
    requests: Map<string, Promise<T>>,
  ): Promise<T> {
    const pending = requests.get(key);

    if (pending !== undefined) {
      return pending;
    }

    const request = load();
    const release = () => {
      if (requests.get(key) === request) {
        requests.delete(key);
      }
    };

    requests.set(key, request);
    request.then(release, release);
    return request;
  }

  function loadDocument(
    alternativeId: string,
    authorize: AuthorizedMockupRequest,
    options: MockupDocumentOptions = {},
  ): Promise<MockupDocumentPayload> {
    const project = projectId.value;

    if (project === null) {
      return Promise.reject(new Error("No project is active for the design mockups"));
    }

    const source = options.source ?? "latest";
    const entryScreen = options.entryScreen ?? "";
    const requestKey = documentRequestKey(alternativeId, source, entryScreen, options.revision);
    const cached = options.force === true ? null : cachedDocument(requestKey);

    if (cached !== null) {
      return Promise.resolve(cached);
    }

    const epoch = projectEpoch.value;
    const api = options.api ?? designMockupsApi;
    const load = async () => {
      const document = await authorize((token) =>
        api.document(
          project,
          {
            alternative_id: alternativeId,
            source,
            ...(entryScreen === "" ? {} : { entry_screen: entryScreen }),
          },
          token,
        ),
      );

      if (isCurrentProject(project, epoch)) {
        storeDocument(requestKey, document);
      }

      return document;
    };

    return options.force === true ? load() : remember(requestKey, load, documentRequests);
  }

  function reviewKey(runId: string): string {
    return memoryKey(runId, String(reviewRevisions.value[runId] ?? 0));
  }

  function pinsFor(runId: string): ReviewPinsPayload | null {
    return reviewPins.value[reviewKey(runId)] ?? null;
  }

  async function loadReviewPins(
    runId: string,
    authorize: AuthorizedMockupRequest,
    options: ReviewPinsOptions = {},
  ): Promise<ReviewPinsPayload> {
    const project = projectId.value;

    if (project === null) {
      throw new Error("No project is active for the design mockups");
    }

    const key = reviewKey(runId);
    const cached = reviewPins.value[key];

    if (cached !== undefined && options.force !== true) {
      return cached;
    }

    const epoch = projectEpoch.value;
    const api = options.api ?? designReviewPinsApi;
    const payload = await authorize((token) => api.pins(project, runId, token));

    if (isCurrentProject(project, epoch)) {
      reviewPins.value[key] = payload;
    }

    return payload;
  }

  function reviewDocumentKey(runId: string, entryScreen: string): string {
    return memoryKey("review", reviewKey(runId), entryScreen);
  }

  function reviewDocumentFor(runId: string, entryScreen = ""): MockupDocumentPayload | null {
    return cachedDocument(reviewDocumentKey(runId, entryScreen));
  }

  function loadReviewDocument(
    runId: string,
    authorize: AuthorizedMockupRequest,
    options: ReviewDocumentOptions = {},
  ): Promise<MockupDocumentPayload> {
    const project = projectId.value;

    if (project === null) {
      return Promise.reject(new Error("No project is active for the design mockups"));
    }

    const entryScreen = options.entryScreen ?? "";
    const requestKey = reviewDocumentKey(runId, entryScreen);
    const cached = options.force === true ? null : cachedDocument(requestKey);

    if (cached !== null) {
      return Promise.resolve(cached);
    }

    const epoch = projectEpoch.value;
    const api = options.api ?? designReviewPinsApi;
    const load = async () => {
      const document = await authorize((token) =>
        api.document(project, runId, entryScreen === "" ? null : entryScreen, token),
      );

      if (isCurrentProject(project, epoch)) {
        storeDocument(requestKey, document);
      }

      return document;
    };

    return options.force === true ? load() : remember(requestKey, load, documentRequests);
  }

  function forgetReview(runId: string): void {
    reviewRevisions.value[runId] = (reviewRevisions.value[runId] ?? 0) + 1;
  }

  function clearProjectState(): void {
    closeWatches();
    inflight.clear();
    documentRequests.clear();
    capabilityRequest = null;
    design.value = null;
    capabilities.value = null;
    capabilitiesError.value = null;
    entries.value = {};
    checking.value = {};
    drawn.value = {};
    documents.value = {};
    documentKeys.value = {};
    reviewPins.value = {};
    reviewRevisions.value = {};
  }

  function activate(nextProjectId: string, version: DesignPackageVersionPayload | null): void {
    if (projectId.value !== nextProjectId) {
      clearProjectState();
      projectId.value = nextProjectId;
      projectEpoch.value += 1;
      drawn.value = drawnFromMemory(nextProjectId);
    }

    const next =
      version !== null && version.project_id === nextProjectId ? designContext(version) : null;
    const previous = design.value;

    if (next === null) {
      design.value = null;
      return;
    }

    if (
      previous !== null &&
      previous.versionId === next.versionId &&
      previous.contentHash === next.contentHash
    ) {
      return;
    }

    design.value = next;

    for (const [alternativeId, value] of Object.entries(entries.value)) {
      if (!next.alternativeIds.includes(alternativeId)) {
        closeWatch(alternativeId);
        delete entries.value[alternativeId];
        setChecking(alternativeId, false);
      } else if (value.state === "failed" && value.job === null) {
        setEntry(alternativeId, IDLE);
      }
    }
  }

  function reset(): void {
    clearProjectState();
    prepared.clear();
    projectId.value = null;
    projectEpoch.value += 1;
  }

  return {
    projectId,
    projectEpoch,
    design,
    capabilities,
    capabilitiesError,
    entries,
    checking,
    drawn,
    documents,
    documentKeys,
    reviewPins,
    reviewRevisions,
    generatedMockupsEnabled,
    iterationsEnabled,
    appliedAlternativeId,
    isDrawing,
    entry,
    isChecking,
    drawnBefore,
    applicableResult,
    documentFor,
    pinsFor,
    reviewDocumentFor,
    activate,
    loadCapabilities,
    ensure,
    retry,
    markPrepared,
    wasPrepared,
    loadDocument,
    loadReviewPins,
    loadReviewDocument,
    forgetReview,
    reset,
  };
});
