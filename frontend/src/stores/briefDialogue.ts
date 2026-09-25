import { defineStore } from "pinia";

import {
  briefDialogueApi,
  BriefDialogueApiError,
  type BriefDialogueApi,
} from "../api/briefDialogue";
import type { ProjectBriefVersionResponse } from "../api/contracts";
import type { BriefAssumptionResponse } from "../api/workflow-contracts";
import type {
  BriefDialogueOutcome,
  BriefDialoguePayload,
  BriefDialogueProgress,
  BriefDialogueResponse,
  DialogueAnswerInput,
} from "../types/briefDialogue";

export type AuthorizedBriefDialogueRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

export const MODEL_NOT_CONFIGURED = "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED";

interface BriefDialogueStoreState {
  projectId: string | null;
  dialogue: BriefDialoguePayload | null;
  progress: BriefDialogueProgress | null;
  briefVersion: ProjectBriefVersionResponse | null;
  assumptions: BriefAssumptionResponse[];
  lastOutcome: BriefDialogueOutcome | null;
  busy: boolean;
  loaded: boolean;
  modelUnavailable: boolean;
  error: string | null;
}

function errorMessage(error: unknown): string {
  if (error instanceof BriefDialogueApiError) {
    return error.code ?? error.message;
  }
  return error instanceof Error ? error.message : "BRIEF_DIALOGUE_REQUEST_FAILED";
}

export const useBriefDialogueStore = defineStore("briefDialogue", {
  state: (): BriefDialogueStoreState => ({
    projectId: null,
    dialogue: null,
    progress: null,
    briefVersion: null,
    assumptions: [],
    lastOutcome: null,
    busy: false,
    loaded: false,
    modelUnavailable: false,
    error: null,
  }),

  getters: {
    isActive: (state) =>
      state.dialogue !== null &&
      (state.dialogue.status === "OPEN" || state.dialogue.status === "READY"),
    pendingTurn: (state) => {
      const turns = state.dialogue?.turns ?? [];
      const last = turns[turns.length - 1];
      return last !== undefined && last.answer === null ? last : null;
    },
    answeredTurns: (state) => (state.dialogue?.turns ?? []).filter((turn) => turn.answer !== null),
    turnCount: (state) => state.dialogue?.turns.length ?? 0,
  },

  actions: {
    reset(projectId: string): void {
      this.projectId = projectId;
      this.dialogue = null;
      this.progress = null;
      this.briefVersion = null;
      this.assumptions = [];
      this.lastOutcome = null;
      this.busy = false;
      this.loaded = false;
      this.modelUnavailable = false;
      this.error = null;
    },

    apply(response: BriefDialogueResponse | null): void {
      if (response === null) {
        this.dialogue = null;
        this.progress = null;
        this.lastOutcome = null;
        return;
      }
      this.dialogue = response.snapshot;
      this.progress = response.progress;
      this.briefVersion = response.brief_version;
      this.assumptions = response.assumptions;
      this.lastOutcome = response.status;
    },

    async perform(
      projectId: string,
      operation: () => Promise<BriefDialogueResponse | null>,
    ): Promise<BriefDialogueResponse | null> {
      if (this.projectId !== projectId) {
        this.reset(projectId);
      }
      this.busy = true;
      this.error = null;
      try {
        const response = await operation();
        this.apply(response);
        return response;
      } catch (error) {
        const message = errorMessage(error);
        if (message === MODEL_NOT_CONFIGURED) {
          this.modelUnavailable = true;
        }
        this.error = message;
        throw error;
      } finally {
        this.busy = false;
      }
    },

    async load(
      projectId: string,
      authorize: AuthorizedBriefDialogueRequest,
      api: BriefDialogueApi = briefDialogueApi,
    ): Promise<BriefDialogueResponse | null> {
      try {
        return await this.perform(projectId, () =>
          authorize((token) => api.current(projectId, token)),
        );
      } finally {
        this.loaded = true;
      }
    },

    async start(
      projectId: string,
      statement: string,
      authorize: AuthorizedBriefDialogueRequest,
      api: BriefDialogueApi = briefDialogueApi,
    ): Promise<BriefDialogueResponse | null> {
      return this.perform(projectId, () =>
        authorize((token) => api.start(projectId, statement, token)),
      );
    },

    async answer(
      projectId: string,
      input: Omit<DialogueAnswerInput, "expected_turn_count">,
      authorize: AuthorizedBriefDialogueRequest,
      api: BriefDialogueApi = briefDialogueApi,
    ): Promise<BriefDialogueResponse | null> {
      const expected = this.turnCount;
      return this.perform(projectId, () =>
        authorize((token) =>
          api.answer(projectId, { ...input, expected_turn_count: expected }, token),
        ),
      );
    },

    async nextQuestion(
      projectId: string,
      authorize: AuthorizedBriefDialogueRequest,
      api: BriefDialogueApi = briefDialogueApi,
    ): Promise<BriefDialogueResponse | null> {
      const expected = this.turnCount;
      return this.perform(projectId, () =>
        authorize((token) => api.nextQuestion(projectId, expected, token)),
      );
    },

    async synthesize(
      projectId: string,
      authorize: AuthorizedBriefDialogueRequest,
      api: BriefDialogueApi = briefDialogueApi,
    ): Promise<BriefDialogueResponse | null> {
      const expected = this.turnCount;
      return this.perform(projectId, () =>
        authorize((token) => api.synthesize(projectId, expected, token)),
      );
    },

    async close(
      projectId: string,
      authorize: AuthorizedBriefDialogueRequest,
      api: BriefDialogueApi = briefDialogueApi,
    ): Promise<BriefDialogueResponse | null> {
      const expected = this.turnCount;
      return this.perform(projectId, () =>
        authorize((token) => api.close(projectId, expected, token)),
      );
    },
  },
});
