import { defineStore } from "pinia";
import { computed, ref } from "vue";

import {
  KnowledgeAlignmentApiError,
  knowledgeAlignmentApi,
  type KnowledgeAlignmentApi,
} from "../api/knowledgeAlignment";
import type {
  AlignmentLatestRunPayload,
  AlignmentProposalPayload,
  KnowledgeAlignmentRunSummaryPayload,
  ProposalRevisionPayload,
  ProposalSection,
} from "../types/knowledgeAlignment";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type KnowledgeAlignmentOperation = "load" | "runs" | "apply" | "skip";

export type ProposalDecision = "apply" | "skip";

export interface KnowledgeAlignmentStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface LoadKey {
  projectId: string;
  epoch: number;
  api: KnowledgeAlignmentApi;
}

interface RunningLoad extends LoadKey {
  promise: Promise<AlignmentProposalPayload[]>;
}

function matches(
  key: LoadKey,
  project: string,
  epoch: number,
  api: KnowledgeAlignmentApi,
): boolean {
  return key.projectId === project && key.epoch === epoch && key.api === api;
}

function emptyPending(): Record<KnowledgeAlignmentOperation, boolean> {
  return {
    load: false,
    runs: false,
    apply: false,
    skip: false,
  };
}

function storeError(error: unknown): KnowledgeAlignmentStoreError {
  if (error instanceof KnowledgeAlignmentApiError) {
    return {
      message: error.message,
      code: error.code,
      status: error.status,
    };
  }

  if (error instanceof Error) {
    return {
      message: error.message,
      code: null,
      status: null,
    };
  }

  return {
    message: "An unexpected knowledge alignment error occurred",
    code: null,
    status: null,
  };
}

export function revisionDiffId(revision: ProposalRevisionPayload | null): string | null {
  if (revision === null) {
    return null;
  }

  if ("revision" in revision) {
    return revision.revision.diff?.id ?? null;
  }

  return revision.diff?.id ?? null;
}

export const useKnowledgeAlignmentStore = defineStore("knowledgeAlignment", () => {
  const projectId = ref<string | null>(null);
  const projectEpoch = ref(0);
  const loadSequence = ref(0);
  const proposals = ref<AlignmentProposalPayload[]>([]);
  const latestRun = ref<AlignmentLatestRunPayload | null>(null);
  const runs = ref<KnowledgeAlignmentRunSummaryPayload[] | null>(null);
  const deciding = ref<Record<string, ProposalDecision>>({});
  const pending = ref<Record<KnowledgeAlignmentOperation, boolean>>(emptyPending());
  const error = ref<KnowledgeAlignmentStoreError | null>(null);
  let loading: RunningLoad | null = null;
  let held: LoadKey | null = null;

  const isBusy = computed(() => Object.values(pending.value).some(Boolean));

  const waiting = computed(() =>
    proposals.value.filter((proposal) => proposal.status === "PROPOSED"),
  );

  function bySection(section: ProposalSection): AlignmentProposalPayload[] {
    return proposals.value.filter((proposal) => proposal.section === section);
  }

  function decisionOf(code: string): ProposalDecision | null {
    return deciding.value[code] ?? null;
  }

  function activateProject(project: string): void {
    if (projectId.value === project) {
      return;
    }

    projectId.value = project;
    projectEpoch.value += 1;
    proposals.value = [];
    latestRun.value = null;
    runs.value = null;
    deciding.value = {};
    pending.value = emptyPending();
    error.value = null;
    held = null;
  }

  function isCurrent(project: string, epoch: number): boolean {
    return projectId.value === project && projectEpoch.value === epoch;
  }

  function begin(operation: KnowledgeAlignmentOperation): void {
    pending.value[operation] = true;
    error.value = null;
  }

  function finish(operation: KnowledgeAlignmentOperation, project: string, epoch: number): void {
    if (isCurrent(project, epoch)) {
      pending.value[operation] = false;
    }
  }

  function settleDecision(
    code: string,
    decision: ProposalDecision,
    project: string,
    epoch: number,
  ): void {
    if (!isCurrent(project, epoch)) {
      return;
    }

    const remaining = { ...deciding.value };
    delete remaining[code];
    deciding.value = remaining;
    pending.value[decision] = Object.values(remaining).includes(decision);
  }

  function capture(failure: unknown, project: string, epoch: number): void {
    if (isCurrent(project, epoch)) {
      error.value = storeError(failure);
    }
  }

  function replaceProposal(proposal: AlignmentProposalPayload): void {
    const index = proposals.value.findIndex((known) => known.code === proposal.code);

    if (index < 0) {
      proposals.value = [...proposals.value, proposal];
      return;
    }

    proposals.value = proposals.value.map((known, position) =>
      position === index ? proposal : known,
    );
  }

  async function readProposals(
    project: string,
    authorize: AuthorizedRequest,
    api: KnowledgeAlignmentApi,
    epoch: number,
  ): Promise<AlignmentProposalPayload[]> {
    const sequence = ++loadSequence.value;
    const latest = () => isCurrent(project, epoch) && sequence === loadSequence.value;
    begin("load");

    try {
      const answer = await authorize((token) => api.proposals(project, "waiting", token));

      if (latest()) {
        proposals.value = [...answer.items];
        latestRun.value = answer.latest_run ?? null;
        held = { projectId: project, epoch, api };
      }

      return answer.items;
    } catch (failure) {
      if (latest()) {
        capture(failure, project, epoch);
      }
      throw failure;
    } finally {
      if (latest()) {
        finish("load", project, epoch);
      }
    }
  }

  function startLoad(
    project: string,
    authorize: AuthorizedRequest,
    api: KnowledgeAlignmentApi,
    epoch: number,
  ): Promise<AlignmentProposalPayload[]> {
    const running = loading;

    if (running !== null && matches(running, project, epoch, api)) {
      return running.promise;
    }

    const promise = readProposals(project, authorize, api, epoch);
    const current: RunningLoad = { projectId: project, epoch, api, promise };
    const release = () => {
      if (loading === current) {
        loading = null;
      }
    };

    loading = current;
    promise.then(release, release);
    return promise;
  }

  function load(
    project: string,
    authorize: AuthorizedRequest,
    api: KnowledgeAlignmentApi = knowledgeAlignmentApi,
  ): Promise<AlignmentProposalPayload[]> {
    activateProject(project);
    const epoch = projectEpoch.value;

    if (held !== null && matches(held, project, epoch, api)) {
      return Promise.resolve([...proposals.value]);
    }

    return startLoad(project, authorize, api, epoch);
  }

  function reload(
    project: string,
    authorize: AuthorizedRequest,
    api: KnowledgeAlignmentApi = knowledgeAlignmentApi,
  ): Promise<AlignmentProposalPayload[]> {
    activateProject(project);

    return startLoad(project, authorize, api, projectEpoch.value);
  }

  async function loadRuns(
    project: string,
    authorize: AuthorizedRequest,
    api: KnowledgeAlignmentApi = knowledgeAlignmentApi,
  ): Promise<KnowledgeAlignmentRunSummaryPayload[]> {
    activateProject(project);
    const epoch = projectEpoch.value;
    begin("runs");

    try {
      const answer = await authorize((token) => api.runs(project, token));

      if (isCurrent(project, epoch)) {
        runs.value = [...answer.items];
      }

      return answer.items;
    } catch (failure) {
      capture(failure, project, epoch);
      throw failure;
    } finally {
      finish("runs", project, epoch);
    }
  }

  async function apply(
    project: string,
    code: string,
    text: string | null,
    authorize: AuthorizedRequest,
    api: KnowledgeAlignmentApi = knowledgeAlignmentApi,
  ): Promise<string | null> {
    activateProject(project);
    const epoch = projectEpoch.value;
    deciding.value = { ...deciding.value, [code]: "apply" };
    begin("apply");

    try {
      const answer = await authorize((token) => api.apply(project, code, text, token));

      if (isCurrent(project, epoch)) {
        replaceProposal(answer.proposal);
      }

      return revisionDiffId(answer.revision);
    } catch (failure) {
      capture(failure, project, epoch);
      throw failure;
    } finally {
      settleDecision(code, "apply", project, epoch);
    }
  }

  async function skip(
    project: string,
    code: string,
    reason: string | null,
    authorize: AuthorizedRequest,
    api: KnowledgeAlignmentApi = knowledgeAlignmentApi,
  ): Promise<AlignmentProposalPayload> {
    activateProject(project);
    const epoch = projectEpoch.value;
    deciding.value = { ...deciding.value, [code]: "skip" };
    begin("skip");

    try {
      const answer = await authorize((token) => api.skip(project, code, reason, token));

      if (isCurrent(project, epoch)) {
        replaceProposal(answer.proposal);
      }

      return answer.proposal;
    } catch (failure) {
      capture(failure, project, epoch);
      throw failure;
    } finally {
      settleDecision(code, "skip", project, epoch);
    }
  }

  return {
    projectId,
    projectEpoch,
    loadSequence,
    proposals,
    latestRun,
    runs,
    deciding,
    pending,
    error,
    isBusy,
    waiting,
    bySection,
    decisionOf,
    activateProject,
    isCurrent,
    begin,
    finish,
    settleDecision,
    capture,
    replaceProposal,
    load,
    reload,
    loadRuns,
    apply,
    skip,
  };
});
