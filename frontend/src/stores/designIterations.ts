import { defineStore } from "pinia";
import { computed, ref } from "vue";

import {
  designIterationsApi,
  type DesignChangeTarget,
  type DesignChangeTargetElement,
  type DesignIterationItem,
  type DesignIterationsApi,
  type IterationJobBody,
} from "../api/designIterations";
import { designMockupsApi, type DesignMockupsApi } from "../api/designMockups";
import { isRecord } from "../api/http";
import type { DesignPackageVersionPayload } from "../types/design";
import type {
  GenerationJobPayload,
  MockupIssuePayload,
  MockupResultPayload,
} from "../types/designMockups";
import {
  GENERATION_FAILED,
  GENERATION_JOB_NOT_FOUND,
  GENERATION_POLL_TIMEOUT,
  GENERATION_START_FAILED,
  GENERATION_STATUS_UNAVAILABLE,
  INVALID_API_RESPONSE,
  JobWatch,
  MOCKUP_REJECTED,
  errorCodeOf,
  errorStatusOf,
  isFinishedStatus,
  isTransientError,
  pollingHolder,
  readSessionValue,
  writeSessionValue,
  type AuthorizedMockupRequest,
} from "./designMockups";

export const ITERATION_REQUEST_LIMIT = 1000;
export const ITERATION_ASSERTION_LIMIT = 300;
export const ITERATION_ASSERTIONS_PER_REQUEST = 5;
export const TARGET_LABEL_LIMIT = 120;
export const TARGET_HTML_LIMIT = 2048;
export const TARGET_PARTS_LIMIT = 8;
export const PART_CODE = /^(ELM|ZON)-\d{3,6}$/;
export const DESIGN_CONTEXT_CHANGED = "DESIGN_CONTEXT_CHANGED";
export const DESIGN_ITERATIONS_UNAVAILABLE = "DESIGN_ITERATIONS_UNAVAILABLE";

const SCREEN_CODE = /^SCR-\d{3}$/;
const TARGET_PARTS_MINIMUM = 2;

export type IterationState = "idle" | "drawing" | "ready" | "rejected" | "failed";

export interface IterationRequest {
  request: string;
  assertions: string[];
  target?: DesignChangeTarget;
  critiqueSourceId?: string;
  opinionId?: string;
}

export interface IterationRequestInput {
  request: string;
  assertions?: readonly string[];
  target?: DesignChangeTarget | null;
  opinionId?: string;
}

export interface IterationFailure {
  code: string;
  reasons: MockupIssuePayload[];
}

export type IterationOutcome =
  | "started"
  | "running"
  | "ready"
  | "pending"
  | "invalid"
  | "refused"
  | "failed"
  | "unavailable"
  | "inactive";

export interface IterationDesignContext {
  projectId: string;
  versionId: string;
  contentHash: string;
  selectedAlternativeId: string | null;
  hasGeneratedMockup: boolean;
}

export interface IterationRequestOptions {
  api?: DesignIterationsApi;
  mockupsApi?: DesignMockupsApi;
  signal?: AbortSignal;
}

export interface IterationStartOptions extends IterationRequestOptions {
  replace?: boolean;
}

interface RememberedIteration extends IterationRequest {
  jobId: string;
  hash: string;
}

interface IterationMemory {
  jobs: Record<string, RememberedIteration>;
  discarded: string[];
}

interface IterationAccess {
  authorize: AuthorizedMockupRequest;
  api: DesignIterationsApi;
  mockupsApi: DesignMockupsApi;
}

type TargetPart = Pick<DesignChangeTarget, "element_code" | "label" | "html">;

type TargetText = Pick<DesignChangeTarget, "label" | "html">;

const MEMORY_KEY = "orchestwin.designIterations";
const MEMORY_LIMIT = 200;

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isOptionalString(value: unknown): boolean {
  return value === undefined || typeof value === "string";
}

function hasPartFields(value: Record<string, unknown>): boolean {
  return (
    isOptionalString(value.element_code) &&
    isOptionalString(value.label) &&
    isOptionalString(value.html)
  );
}

function isTargetElement(value: unknown): value is DesignChangeTargetElement {
  return isRecord(value) && typeof value.element_code === "string" && hasPartFields(value);
}

function isTarget(value: unknown): value is DesignChangeTarget {
  return (
    isRecord(value) &&
    typeof value.screen_code === "string" &&
    hasPartFields(value) &&
    (value.elements === undefined ||
      (Array.isArray(value.elements) && value.elements.every(isTargetElement)))
  );
}

function isRememberedIteration(value: unknown): value is RememberedIteration {
  return (
    isRecord(value) &&
    typeof value.jobId === "string" &&
    typeof value.hash === "string" &&
    typeof value.request === "string" &&
    isStringList(value.assertions) &&
    (value.target === undefined || isTarget(value.target)) &&
    isOptionalString(value.critiqueSourceId) &&
    isOptionalString(value.opinionId)
  );
}

function readIterationMemory(): IterationMemory {
  const value = readSessionValue(MEMORY_KEY);

  if (!isRecord(value)) {
    return { jobs: {}, discarded: [] };
  }

  const jobs = isRecord(value.jobs)
    ? Object.fromEntries(
        Object.entries(value.jobs)
          .filter((entry): entry is [string, RememberedIteration] =>
            isRememberedIteration(entry[1]),
          )
          .slice(-MEMORY_LIMIT),
      )
    : {};
  const discarded = isStringList(value.discarded) ? value.discarded.slice(-MEMORY_LIMIT) : [];

  return { jobs, discarded };
}

function characterCount(value: string): number {
  return [...value].length;
}

function withinLimit(value: string, limit: number): boolean {
  const count = characterCount(value);
  return count > 0 && count <= limit;
}

function validPart(part: TargetPart): boolean {
  return (
    (part.element_code === undefined || PART_CODE.test(part.element_code)) &&
    (part.label === undefined || withinLimit(part.label.trim(), TARGET_LABEL_LIMIT)) &&
    (part.html === undefined || withinLimit(part.html, TARGET_HTML_LIMIT))
  );
}

function validElements(elements: readonly DesignChangeTargetElement[]): boolean {
  return (
    elements.length >= TARGET_PARTS_MINIMUM &&
    elements.length <= TARGET_PARTS_LIMIT &&
    new Set(elements.map((part) => part.element_code)).size === elements.length &&
    elements.every(validPart)
  );
}

function described(part: TargetText): TargetText {
  return {
    ...(part.label === undefined ? {} : { label: part.label.trim() }),
    ...(part.html === undefined ? {} : { html: part.html }),
  };
}

export function targetCodes(target: DesignChangeTarget): string[] {
  if (target.elements !== undefined) {
    return target.elements.map((part) => part.element_code);
  }
  return target.element_code === undefined ? [] : [target.element_code];
}

function normalizedTarget(value: DesignChangeTarget): DesignChangeTarget | null {
  const { screen_code: screen, element_code: code, elements } = value;

  if (!SCREEN_CODE.test(screen) || !validPart(value)) {
    return null;
  }

  if (elements === undefined) {
    return {
      screen_code: screen,
      ...(code === undefined ? {} : { element_code: code }),
      ...described(value),
    };
  }

  if (
    code !== undefined ||
    value.label !== undefined ||
    value.html !== undefined ||
    !validElements(elements)
  ) {
    return null;
  }

  return {
    screen_code: screen,
    elements: elements.map((part) => ({ element_code: part.element_code, ...described(part) })),
  };
}

export function normalizedIterationRequest(input: IterationRequestInput): IterationRequest | null {
  const request = input.request.trim();
  const assertions = [
    ...new Set((input.assertions ?? []).map((item) => item.trim()).filter(Boolean)),
  ];

  if (characterCount(request) === 0 || characterCount(request) > ITERATION_REQUEST_LIMIT) {
    return null;
  }

  if (
    assertions.length > ITERATION_ASSERTIONS_PER_REQUEST ||
    assertions.some((item) => characterCount(item) > ITERATION_ASSERTION_LIMIT)
  ) {
    return null;
  }

  const opinion = input.opinionId === undefined ? {} : { opinionId: input.opinionId };

  if (input.target === undefined || input.target === null) {
    return { request, assertions, ...opinion };
  }

  const target = normalizedTarget(input.target);

  return target === null ? null : { request, assertions, target, ...opinion };
}

function iterationContext(version: DesignPackageVersionPayload): IterationDesignContext {
  return {
    projectId: version.project_id,
    versionId: version.id,
    contentHash: version.content_hash,
    selectedAlternativeId: version.package.owner_selected_alternative_id,
    hasGeneratedMockup: (version.package.generated_mockup ?? null) !== null,
  };
}

export const useDesignIterationsStore = defineStore("designIterations", () => {
  const projectId = ref<string | null>(null);
  const projectEpoch = ref(0);
  const design = ref<IterationDesignContext | null>(null);
  const state = ref<IterationState>("idle");
  const job = ref<GenerationJobPayload | null>(null);
  const startedAt = ref<string | null>(null);
  const request = ref<IterationRequest | null>(null);
  const result = ref<MockupResultPayload | null>(null);
  const failure = ref<IterationFailure | null>(null);
  const items = ref<DesignIterationItem[]>([]);
  const loaded = ref(false);
  const listing = ref(false);
  const listError = ref<string | null>(null);
  const starting = ref(false);

  const memory = readIterationMemory();
  let watch: JobWatch | null = null;
  let access: IterationAccess | null = null;
  let inflight: Promise<IterationOutcome> | null = null;

  const isApplicable = computed(
    () =>
      state.value === "ready" &&
      result.value !== null &&
      design.value !== null &&
      result.value.design_version_id === design.value.versionId &&
      result.value.design_content_hash === design.value.contentHash,
  );
  const isBusy = computed(() => state.value === "drawing" || starting.value);

  function persistMemory(): void {
    writeSessionValue(MEMORY_KEY, {
      jobs: Object.fromEntries(Object.entries(memory.jobs).slice(-MEMORY_LIMIT)),
      discarded: memory.discarded.slice(-MEMORY_LIMIT),
    });
  }

  function rememberIteration(project: string, value: RememberedIteration): void {
    memory.jobs[project] = value;
    persistMemory();
  }

  function forgetIteration(project: string): void {
    if (project in memory.jobs) {
      delete memory.jobs[project];
      persistMemory();
    }
  }

  function discardedKey(project: string, generationId: string): string {
    return `${project}|${generationId}`;
  }

  function rememberDiscarded(project: string, generationId: string): void {
    const key = discardedKey(project, generationId);

    if (!memory.discarded.includes(key)) {
      memory.discarded.push(key);
      persistMemory();
    }
  }

  function isCurrentProject(project: string, epoch: number): boolean {
    return projectId.value === project && projectEpoch.value === epoch;
  }

  function isTracking(jobId: string, project: string, epoch: number): boolean {
    return (
      isCurrentProject(project, epoch) && state.value === "drawing" && job.value?.job_id === jobId
    );
  }

  function closeWatch(): void {
    watch?.close();
    watch = null;
    access = null;
  }

  function clearIteration(): void {
    state.value = "idle";
    job.value = null;
    startedAt.value = null;
    request.value = null;
    result.value = null;
    failure.value = null;
  }

  function fail(code: string, reasons: MockupIssuePayload[] = []): void {
    startedAt.value = null;
    result.value = null;
    failure.value = { code, reasons };
    state.value = "failed";
  }

  function applyJob(project: string, value: GenerationJobPayload): IterationState {
    job.value = value;

    if (value.status === "SUCCEEDED") {
      forgetIteration(project);

      if (value.result === null) {
        fail(INVALID_API_RESPONSE);
      } else if (
        design.value !== null &&
        value.result.design_content_hash !== design.value.contentHash
      ) {
        fail(DESIGN_CONTEXT_CHANGED);
      } else {
        startedAt.value = null;
        result.value = value.result;
        failure.value = null;
        state.value = "ready";
      }
      return state.value;
    }

    if (value.status === "REJECTED") {
      startedAt.value = null;
      result.value = null;
      failure.value = {
        code: value.failure?.code ?? MOCKUP_REJECTED,
        reasons: value.failure?.reasons ?? [],
      };
      state.value = "rejected";
      return state.value;
    }

    if (value.status === "FAILED") {
      fail(value.failure?.code ?? GENERATION_FAILED, value.failure?.reasons ?? []);
      return state.value;
    }

    result.value = null;
    failure.value = null;
    startedAt.value = value.started_at;
    state.value = "drawing";
    return state.value;
  }

  function isPendingProposal(
    candidate: MockupResultPayload,
    context: IterationDesignContext,
    project: string,
  ): boolean {
    return (
      candidate.changes.length > 0 &&
      candidate.design_content_hash === context.contentHash &&
      (candidate.package.generated_mockup ?? null) !== null &&
      !memory.discarded.includes(discardedKey(project, candidate.generation_id))
    );
  }

  async function recoverProposal(
    project: string,
    epoch: number,
    context: IterationDesignContext,
    authorize: AuthorizedMockupRequest,
    mockupsApi: DesignMockupsApi,
  ): Promise<boolean> {
    const alternativeId = context.selectedAlternativeId;

    if (alternativeId === null || !context.hasGeneratedMockup) {
      return false;
    }

    try {
      const latest = await authorize((token) => mockupsApi.latest(project, alternativeId, token));

      if (
        !isCurrentProject(project, epoch) ||
        latest === null ||
        !isPendingProposal(latest, context, project)
      ) {
        return false;
      }

      job.value = null;
      startedAt.value = null;
      result.value = latest;
      failure.value = null;
      state.value = "ready";
      return true;
    } catch {
      return false;
    }
  }

  async function loadList(
    authorize: AuthorizedMockupRequest,
    options: { api?: DesignIterationsApi } = {},
  ): Promise<DesignIterationItem[]> {
    const project = projectId.value;

    if (project === null) {
      return [];
    }

    const epoch = projectEpoch.value;
    const api = options.api ?? designIterationsApi;
    listing.value = true;
    listError.value = null;

    try {
      const payload = await authorize((token) => api.list(project, token));

      if (isCurrentProject(project, epoch)) {
        items.value = payload.items;
        loaded.value = true;
      }

      return payload.items;
    } catch (error) {
      if (isCurrentProject(project, epoch)) {
        listError.value = errorCodeOf(error) ?? DESIGN_ITERATIONS_UNAVAILABLE;
      }

      throw error;
    } finally {
      if (isCurrentProject(project, epoch)) {
        listing.value = false;
      }
    }
  }

  function refreshList(project: string, epoch: number, currentAccess: IterationAccess): void {
    if (isCurrentProject(project, epoch)) {
      loadList(currentAccess.authorize, { api: currentAccess.api }).catch(() => undefined);
    }
  }

  async function lost(
    project: string,
    epoch: number,
    currentAccess: IterationAccess,
  ): Promise<void> {
    forgetIteration(project);
    const context = design.value;

    if (
      context !== null &&
      (await recoverProposal(
        project,
        epoch,
        context,
        currentAccess.authorize,
        currentAccess.mockupsApi,
      ))
    ) {
      return;
    }

    if (isCurrentProject(project, epoch)) {
      fail(GENERATION_JOB_NOT_FOUND);
    }
  }

  async function poll(jobId: string, project: string, epoch: number): Promise<boolean> {
    const currentAccess = access;

    if (currentAccess === null || !isTracking(jobId, project, epoch)) {
      return true;
    }

    try {
      const value = await currentAccess.authorize((token) =>
        currentAccess.api.job(project, jobId, token),
      );

      if (!isTracking(jobId, project, epoch)) {
        return true;
      }

      applyJob(project, value);

      if (isFinishedStatus(value.status)) {
        refreshList(project, epoch, currentAccess);
        return true;
      }

      return false;
    } catch (error) {
      if (!isTracking(jobId, project, epoch)) {
        return true;
      }

      if (errorStatusOf(error) === 404) {
        await lost(project, epoch, currentAccess);
        return true;
      }

      if (isTransientError(error)) {
        return false;
      }

      fail(errorCodeOf(error) ?? GENERATION_STATUS_UNAVAILABLE);
      return true;
    }
  }

  function expire(jobId: string, project: string, epoch: number): void {
    if (isTracking(jobId, project, epoch)) {
      fail(GENERATION_POLL_TIMEOUT);
    }
  }

  function follow(
    authorize: AuthorizedMockupRequest,
    api: DesignIterationsApi,
    mockupsApi: DesignMockupsApi,
    holder: AbortSignal | undefined,
  ): void {
    const project = projectId.value;
    const current = job.value;

    if (state.value !== "drawing" || project === null || current === null) {
      return;
    }

    const epoch = projectEpoch.value;
    const jobId = current.job_id;

    if (watch === null || watch.isClosed || watch.jobId !== jobId) {
      watch?.close();
      watch = new JobWatch(
        jobId,
        () => poll(jobId, project, epoch),
        () => expire(jobId, project, epoch),
      );
    }

    access = { authorize, api, mockupsApi };
    watch.hold(holder);
  }

  function serialized(run: () => Promise<IterationOutcome>): Promise<IterationOutcome> {
    if (inflight !== null) {
      return inflight;
    }

    const promise = run();
    const release = () => {
      if (inflight === promise) {
        inflight = null;
      }
    };

    inflight = promise;
    promise.then(release, release);
    return promise;
  }

  async function settled(
    run: () => Promise<IterationOutcome>,
    options: IterationRequestOptions,
    authorize: AuthorizedMockupRequest,
    holder: AbortSignal | undefined,
  ): Promise<IterationOutcome> {
    const outcome = await serialized(run);

    follow(
      authorize,
      options.api ?? designIterationsApi,
      options.mockupsApi ?? designMockupsApi,
      holder,
    );
    return outcome;
  }

  async function post(
    value: IterationRequest,
    context: IterationDesignContext,
    project: string,
    epoch: number,
    authorize: AuthorizedMockupRequest,
    api: DesignIterationsApi,
  ): Promise<IterationOutcome> {
    const replaced = result.value;
    const target = value.target === undefined ? {} : { target: value.target };
    const source = value.critiqueSourceId;
    const opinion = value.opinionId;
    const body: IterationJobBody = {
      design_version_id: context.versionId,
      design_content_hash: context.contentHash,
      request: value.request,
      assertions: value.assertions,
      ...target,
      ...(source === undefined ? {} : { critique_source_id: source }),
      ...(opinion === undefined ? {} : { opinion_id: opinion }),
    };
    starting.value = true;
    request.value = value;

    try {
      const created = await authorize((token) => api.startJob(project, body, token));

      rememberIteration(project, { ...value, jobId: created.job_id, hash: context.contentHash });

      if (replaced !== null) {
        rememberDiscarded(project, replaced.generation_id);
      }

      if (!isCurrentProject(project, epoch)) {
        return "inactive";
      }

      applyJob(project, created);
      return "started";
    } catch (error) {
      if (!isCurrentProject(project, epoch)) {
        return "inactive";
      }

      job.value = null;
      fail(errorCodeOf(error) ?? GENERATION_START_FAILED);
      return "refused";
    } finally {
      if (isCurrentProject(project, epoch)) {
        starting.value = false;
      }
    }
  }

  async function runStart(
    input: IterationRequestInput,
    replace: boolean,
    authorize: AuthorizedMockupRequest,
    api: DesignIterationsApi,
    critiqueSourceId: string | null,
  ): Promise<IterationOutcome> {
    const project = projectId.value;
    const epoch = projectEpoch.value;
    const context = design.value;

    if (project === null || context === null) {
      return "inactive";
    }

    const normalized = normalizedIterationRequest(input);
    const source = critiqueSourceId?.trim() ?? null;

    if (normalized === null || source === "") {
      return "invalid";
    }

    const value = source === null ? normalized : { ...normalized, critiqueSourceId: source };

    if (state.value === "drawing") {
      return "running";
    }

    if (state.value === "ready" && !replace) {
      return "pending";
    }

    if (!context.hasGeneratedMockup) {
      return "unavailable";
    }

    return post(value, context, project, epoch, authorize, api);
  }

  async function runRetry(
    authorize: AuthorizedMockupRequest,
    api: DesignIterationsApi,
  ): Promise<IterationOutcome> {
    const project = projectId.value;
    const epoch = projectEpoch.value;
    const context = design.value;
    const previous = request.value;

    if (project === null || context === null || previous === null) {
      return "inactive";
    }

    if (state.value === "drawing") {
      return "running";
    }

    if (state.value === "ready") {
      return "pending";
    }

    if (!context.hasGeneratedMockup) {
      return "unavailable";
    }

    const known = job.value;

    if (known !== null) {
      try {
        const value = await authorize((token) => api.job(project, known.job_id, token));

        if (!isCurrentProject(project, epoch)) {
          return "inactive";
        }

        if (!isFinishedStatus(value.status)) {
          applyJob(project, value);
          return "running";
        }

        if (value.status === "SUCCEEDED" && applyJob(project, value) === "ready") {
          return "ready";
        }
      } catch (error) {
        if (!isCurrentProject(project, epoch)) {
          return "inactive";
        }

        if (errorStatusOf(error) !== 404) {
          fail(errorCodeOf(error) ?? GENERATION_STATUS_UNAVAILABLE);
          return "failed";
        }
      }
    }

    return post(previous, context, project, epoch, authorize, api);
  }

  async function runRecover(
    authorize: AuthorizedMockupRequest,
    api: DesignIterationsApi,
    mockupsApi: DesignMockupsApi,
  ): Promise<IterationOutcome> {
    const project = projectId.value;
    const epoch = projectEpoch.value;
    const context = design.value;

    if (project === null || context === null) {
      return "inactive";
    }

    if (state.value === "drawing") {
      return "running";
    }

    if (state.value === "ready") {
      return "ready";
    }

    const remembered = memory.jobs[project] ?? null;

    if (remembered !== null) {
      request.value = {
        request: remembered.request,
        assertions: [...remembered.assertions],
        ...(remembered.target === undefined ? {} : { target: { ...remembered.target } }),
        ...(remembered.critiqueSourceId === undefined
          ? {}
          : { critiqueSourceId: remembered.critiqueSourceId }),
        ...(remembered.opinionId === undefined ? {} : { opinionId: remembered.opinionId }),
      };

      try {
        const value = await authorize((token) => api.job(project, remembered.jobId, token));

        if (!isCurrentProject(project, epoch)) {
          return "inactive";
        }

        const reached = applyJob(project, value);

        if (reached === "drawing") {
          return "running";
        }

        return reached === "ready" ? "ready" : "failed";
      } catch (error) {
        if (!isCurrentProject(project, epoch)) {
          return "inactive";
        }

        if (errorStatusOf(error) !== 404) {
          fail(errorCodeOf(error) ?? GENERATION_STATUS_UNAVAILABLE);
          return "failed";
        }

        forgetIteration(project);
        request.value = null;
      }
    }

    return (await recoverProposal(project, epoch, context, authorize, mockupsApi))
      ? "ready"
      : "inactive";
  }

  function start(
    input: IterationRequestInput,
    authorize: AuthorizedMockupRequest,
    options: IterationStartOptions = {},
    critiqueSourceId: string | null = null,
  ): Promise<IterationOutcome> {
    const holder = pollingHolder(options.signal);

    return settled(
      () =>
        runStart(
          input,
          options.replace === true,
          authorize,
          options.api ?? designIterationsApi,
          critiqueSourceId,
        ),
      options,
      authorize,
      holder,
    );
  }

  function retry(
    authorize: AuthorizedMockupRequest,
    options: IterationRequestOptions = {},
  ): Promise<IterationOutcome> {
    const holder = pollingHolder(options.signal);

    return settled(
      () => runRetry(authorize, options.api ?? designIterationsApi),
      options,
      authorize,
      holder,
    );
  }

  function recover(
    authorize: AuthorizedMockupRequest,
    options: IterationRequestOptions = {},
  ): Promise<IterationOutcome> {
    const holder = pollingHolder(options.signal);

    return settled(
      () =>
        runRecover(
          authorize,
          options.api ?? designIterationsApi,
          options.mockupsApi ?? designMockupsApi,
        ),
      options,
      authorize,
      holder,
    );
  }

  function discard(): void {
    const project = projectId.value;

    if (state.value === "drawing" || project === null) {
      return;
    }

    if (result.value !== null) {
      rememberDiscarded(project, result.value.generation_id);
    }

    forgetIteration(project);
    closeWatch();
    clearIteration();
  }

  function settleApplied(): void {
    const project = projectId.value;

    if (project !== null) {
      forgetIteration(project);
    }

    closeWatch();
    clearIteration();
  }

  function clearProjectState(): void {
    closeWatch();
    inflight = null;
    design.value = null;
    clearIteration();
    items.value = [];
    loaded.value = false;
    listing.value = false;
    listError.value = null;
    starting.value = false;
  }

  function activate(nextProjectId: string, version: DesignPackageVersionPayload | null): void {
    if (projectId.value !== nextProjectId) {
      clearProjectState();
      projectId.value = nextProjectId;
      projectEpoch.value += 1;
    }

    const next =
      version !== null && version.project_id === nextProjectId ? iterationContext(version) : null;
    const previous = design.value;

    design.value = next;

    if (
      next !== null &&
      previous !== null &&
      previous.contentHash !== next.contentHash &&
      state.value === "ready" &&
      result.value !== null &&
      result.value.design_content_hash !== next.contentHash
    ) {
      clearIteration();
    }
  }

  function reset(): void {
    clearProjectState();
    projectId.value = null;
    projectEpoch.value += 1;
  }

  return {
    projectId,
    projectEpoch,
    design,
    state,
    job,
    startedAt,
    request,
    result,
    failure,
    items,
    loaded,
    listing,
    listError,
    starting,
    isApplicable,
    isBusy,
    activate,
    start,
    retry,
    recover,
    discard,
    settleApplied,
    loadList,
    reset,
  };
});
