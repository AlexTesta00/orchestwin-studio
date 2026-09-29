import { defineStore } from "pinia";
import {
  computed,
  getCurrentScope,
  onBeforeUnmount,
  onMounted,
  onScopeDispose,
  ref,
  watch,
  type ComputedRef,
  type Ref,
} from "vue";

import { ApiError } from "../api/client";
import {
  followedGenerationJobs,
  GENERATION_FAILED,
  GENERATION_JOB_NOT_FOUND,
  GENERATION_POLL_TIMEOUT,
  generationJobsApi,
  isGenerationLost,
  onFollowedGenerationJob,
  pause,
  POLL_LIMIT_MILLISECONDS,
  pollInterval,
  type GenerationJobEvent,
  type GenerationJobsApi,
  type GenerationRequestJob,
} from "../api/generationJobs";
import { ApiRequestError } from "../api/requestError";
import type { GenerationOperation } from "../types/designMockups";

export type AuthorizedGenerationRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

export type GenerationSettlement =
  | { kind: "finished"; job: GenerationRequestJob }
  | { kind: "lost" }
  | { kind: "expired" }
  | { kind: "refused"; code: string | null }
  | { kind: "inactive" };

export interface GenerationResumeFailure {
  operation: GenerationOperation;
  code: string;
  lost: boolean;
}

export interface GenerationResumeOptions {
  projectId: () => string;
  operations: readonly GenerationOperation[];
  authorize: AuthorizedGenerationRequest;
  onSettled: (settlement: GenerationSettlement) => unknown;
  api?: GenerationJobsApi | undefined;
}

export interface GenerationResume {
  job: ComputedRef<GenerationRequestJob | null>;
  checked: Ref<boolean>;
  failure: Ref<GenerationResumeFailure | null>;
  dismiss: () => void;
}

interface TrackedJob {
  projectId: string;
  job: GenerationRequestJob;
  own: boolean;
}

interface RunningListing {
  project: string;
  epoch: number;
  api: GenerationJobsApi;
  at: number;
  promise: Promise<GenerationRequestJob[]>;
}

const LISTING_REUSE_MILLISECONDS = 2000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function firstText(...values: unknown[]): string | null {
  const found = values.find((value) => typeof value === "string" && value.length > 0);

  return typeof found === "string" ? found : null;
}

function bodyCode(body: unknown): string | null {
  if (!isRecord(body)) {
    return null;
  }

  if (typeof body.detail === "string") {
    return body.detail;
  }

  return isRecord(body.detail) ? firstText(body.detail.code) : null;
}

export function settledCode(job: GenerationRequestJob): string | null {
  const response = job.response;

  if (response === null) {
    return job.failure?.code ?? (job.status === "SUCCEEDED" ? null : GENERATION_FAILED);
  }

  if (response.status_code >= 400) {
    return bodyCode(response.body) ?? GENERATION_FAILED;
  }

  const body = response.body;

  if (isRecord(body) && body.status === "REJECTED") {
    return firstText(body.proposal_issue, body.candidate_issue, body.issue) ?? GENERATION_FAILED;
  }

  return null;
}

function failureOf(
  operation: GenerationOperation,
  settlement: GenerationSettlement,
): GenerationResumeFailure | null {
  if (settlement.kind === "lost") {
    return { operation, code: GENERATION_JOB_NOT_FOUND, lost: true };
  }

  if (settlement.kind === "expired") {
    return { operation, code: GENERATION_POLL_TIMEOUT, lost: false };
  }

  if (settlement.kind === "refused") {
    return { operation, code: settlement.code ?? GENERATION_FAILED, lost: false };
  }

  if (settlement.kind !== "finished") {
    return null;
  }

  const code = settledCode(settlement.job);

  return code === null ? null : { operation, code, lost: isGenerationLost(code) };
}

function errorCode(error: unknown): string | null {
  if (error instanceof ApiRequestError) {
    return error.code;
  }

  return error instanceof ApiError ? error.detail : null;
}

function isTransient(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return true;
  }

  return error.status === 408 || error.status === 429 || error.status >= 500;
}

export const useGenerationJobsStore = defineStore("generationJobs", () => {
  const projectId = ref<string | null>(null);
  const projectEpoch = ref(0);
  const tracked = ref<Record<string, TrackedJob>>({});
  const waits = new Map<string, Promise<GenerationSettlement>>();
  let listing: RunningListing | null = null;

  function track(event: GenerationJobEvent): void {
    const { job } = event;

    if (event.following && job.status === "RUNNING") {
      tracked.value[job.job_id] = { projectId: event.projectId, job, own: true };
      return;
    }

    if (tracked.value[job.job_id]?.own === true) {
      delete tracked.value[job.job_id];
    }
  }

  for (const event of followedGenerationJobs()) {
    track(event);
  }

  const stopTracking = onFollowedGenerationJob(track);

  if (getCurrentScope() !== undefined) {
    onScopeDispose(stopTracking);
  }

  function isCurrent(project: string, epoch: number): boolean {
    return projectId.value === project && projectEpoch.value === epoch;
  }

  function activate(project: string): void {
    if (projectId.value === project) {
      return;
    }

    projectId.value = project;
    projectEpoch.value += 1;

    for (const [jobId, entry] of Object.entries(tracked.value)) {
      if (!entry.own) {
        delete tracked.value[jobId];
      }
    }
  }

  function isOwn(jobId: string): boolean {
    return tracked.value[jobId]?.own === true;
  }

  function runningFor(
    project: string,
    operations: readonly GenerationOperation[],
  ): GenerationRequestJob | null {
    const matching = Object.values(tracked.value)
      .filter(
        (entry) =>
          entry.projectId === project &&
          entry.job.status === "RUNNING" &&
          operations.includes(entry.job.operation),
      )
      .map((entry) => entry.job)
      .sort((left, right) => left.started_at.localeCompare(right.started_at));

    return matching[0] ?? null;
  }

  function untrack(jobId: string): void {
    if (tracked.value[jobId]?.own === false) {
      delete tracked.value[jobId];
    }
  }

  function runningJobs(
    project: string,
    epoch: number,
    authorize: AuthorizedGenerationRequest,
    api: GenerationJobsApi,
  ): Promise<GenerationRequestJob[]> {
    const now = Date.now();

    if (
      listing !== null &&
      listing.project === project &&
      listing.epoch === epoch &&
      listing.api === api &&
      now - listing.at < LISTING_REUSE_MILLISECONDS
    ) {
      return listing.promise;
    }

    const promise = authorize((token) => api.list(project, token, "RUNNING"));
    const current: RunningListing = { project, epoch, api, at: now, promise };

    listing = current;
    promise.catch(() => {
      if (listing === current) {
        listing = null;
      }
    });
    return promise;
  }

  async function resume(
    project: string,
    operations: readonly GenerationOperation[],
    authorize: AuthorizedGenerationRequest,
    api: GenerationJobsApi = generationJobsApi,
  ): Promise<GenerationRequestJob[]> {
    activate(project);
    const epoch = projectEpoch.value;
    const jobs = await runningJobs(project, epoch, authorize, api);

    if (!isCurrent(project, epoch)) {
      return [];
    }

    const found = jobs.filter(
      (job) => job.status === "RUNNING" && operations.includes(job.operation),
    );

    for (const job of found) {
      if (!isOwn(job.job_id)) {
        tracked.value[job.job_id] = { projectId: project, job, own: false };
      }
    }

    return found.filter((job) => !isOwn(job.job_id));
  }

  async function follow(
    project: string,
    epoch: number,
    jobId: string,
    authorize: AuthorizedGenerationRequest,
    api: GenerationJobsApi,
  ): Promise<GenerationSettlement> {
    const since = Date.now();

    for (;;) {
      await pause(pollInterval(Date.now() - since));

      if (!isCurrent(project, epoch)) {
        return { kind: "inactive" };
      }

      if (Date.now() - since >= POLL_LIMIT_MILLISECONDS) {
        untrack(jobId);
        return { kind: "expired" };
      }

      let job: GenerationRequestJob;

      try {
        job = await authorize((token) => api.job(project, jobId, token));
      } catch (error) {
        if (!isCurrent(project, epoch)) {
          return { kind: "inactive" };
        }

        if (error instanceof ApiError && error.status === 404) {
          untrack(jobId);
          return { kind: "lost" };
        }

        if (isTransient(error)) {
          continue;
        }

        untrack(jobId);
        return { kind: "refused", code: errorCode(error) };
      }

      if (!isCurrent(project, epoch)) {
        return { kind: "inactive" };
      }

      if (job.status === "RUNNING") {
        if (!isOwn(jobId)) {
          tracked.value[jobId] = { projectId: project, job, own: false };
        }
        continue;
      }

      untrack(jobId);
      return { kind: "finished", job };
    }
  }

  function wait(
    project: string,
    jobId: string,
    authorize: AuthorizedGenerationRequest,
    api: GenerationJobsApi = generationJobsApi,
  ): Promise<GenerationSettlement> {
    if (projectId.value !== project) {
      return Promise.resolve({ kind: "inactive" });
    }

    const epoch = projectEpoch.value;
    const key = `${epoch}|${jobId}`;
    const known = waits.get(key);

    if (known !== undefined) {
      return known;
    }

    const promise = follow(project, epoch, jobId, authorize, api);
    const release = () => {
      if (waits.get(key) === promise) {
        waits.delete(key);
      }
    };

    waits.set(key, promise);
    promise.then(release, release);
    return promise;
  }

  return {
    projectId,
    projectEpoch,
    tracked,
    activate,
    isOwn,
    runningFor,
    resume,
    wait,
  };
});

export function useGenerationResume(options: GenerationResumeOptions): GenerationResume {
  const store = useGenerationJobsStore();
  const checked = ref(false);
  const failure = ref<GenerationResumeFailure | null>(null);
  let mounted = true;
  let round = 0;

  const job = computed(() => {
    const project = options.projectId().trim();

    return project.length === 0 ? null : store.runningFor(project, options.operations);
  });

  function currentProject(): string {
    return options.projectId().trim();
  }

  function settle(
    project: string,
    operation: GenerationOperation,
    settlement: GenerationSettlement,
  ): void {
    if (!mounted || settlement.kind === "inactive" || currentProject() !== project) {
      return;
    }

    failure.value = failureOf(operation, settlement);
    void Promise.resolve()
      .then(() => options.onSettled(settlement))
      .catch(() => undefined);
  }

  async function check(): Promise<void> {
    const project = currentProject();
    const current = ++round;
    checked.value = false;

    if (project.length === 0) {
      return;
    }

    let found: GenerationRequestJob[];

    try {
      found = await store.resume(project, options.operations, options.authorize, options.api);
    } catch {
      found = [];
    }

    if (!mounted || current !== round) {
      return;
    }

    checked.value = true;

    for (const running of found) {
      void store
        .wait(project, running.job_id, options.authorize, options.api)
        .then((settlement) => settle(project, running.operation, settlement));
    }
  }

  const stopListening = onFollowedGenerationJob((event) => {
    const { job: ended } = event;

    if (
      event.projectId !== currentProject() ||
      !options.operations.includes(ended.operation) ||
      event.following
    ) {
      return;
    }

    if (event.ended === "lost" || isGenerationLost(ended.failure?.code)) {
      settle(event.projectId, ended.operation, { kind: "lost" });
    } else if (event.ended === "expired") {
      settle(event.projectId, ended.operation, { kind: "expired" });
    }
  });

  onMounted(() => {
    void check();
  });

  watch(currentProject, () => {
    failure.value = null;
    void check();
  });

  onBeforeUnmount(() => {
    mounted = false;
    stopListening();
  });

  return {
    job,
    checked,
    failure,
    dismiss: () => {
      failure.value = null;
    },
  };
}
