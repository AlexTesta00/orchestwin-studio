import { defineStore } from "pinia";
import { ref } from "vue";

import type { DesignChangeTarget } from "../api/designIterations";
import { designOpinionsApi, type DesignOpinionsApi } from "../api/designOpinions";
import type { DesignPackageVersionPayload } from "../types/design";
import type { ChangeOpinionRun } from "../types/designOpinions";
import { targetCodes } from "./designIterations";
import { errorCodeOf } from "./jobWatch";

export type AuthorizedOpinionRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

export type OpinionVersion = Pick<DesignPackageVersionPayload, "id" | "content_hash">;

export interface OpinionSubject {
  contentHash: string;
  codes: string[];
  request: string;
}

export const CHANGE_OPINION_FAILED = "DESIGN_CHANGE_OPINION_FAILED";

function subjectOf(
  contentHash: string,
  target: DesignChangeTarget,
  request: string,
): OpinionSubject {
  return {
    contentHash,
    codes: targetCodes(target),
    request: request.trim().replace(/\s+/g, " "),
  };
}

function sameSubject(left: OpinionSubject, right: OpinionSubject): boolean {
  return (
    left.contentHash === right.contentHash &&
    left.request === right.request &&
    left.codes.length === right.codes.length &&
    left.codes.every((code, index) => code === right.codes[index])
  );
}

export const useDesignOpinionsStore = defineStore("designOpinions", () => {
  const current = ref<ChangeOpinionRun | null>(null);
  const busy = ref(false);
  const error = ref<string | null>(null);
  const askedFor = ref<OpinionSubject | null>(null);
  let round = 0;

  function clear(): void {
    round += 1;
    current.value = null;
    askedFor.value = null;
    error.value = null;
    busy.value = false;
  }

  async function receive(
    turn: number,
    answer: Promise<ChangeOpinionRun>,
  ): Promise<ChangeOpinionRun | null> {
    try {
      const run = await answer;

      if (turn !== round) {
        return null;
      }

      current.value = run;
      return run;
    } catch (caught) {
      if (turn === round) {
        error.value = errorCodeOf(caught) ?? CHANGE_OPINION_FAILED;
      }
      throw caught;
    } finally {
      if (turn === round) {
        busy.value = false;
      }
    }
  }

  async function ask(
    project: string,
    version: OpinionVersion,
    request: string,
    target: DesignChangeTarget,
    locale: string,
    authorize: AuthorizedOpinionRequest,
    api: DesignOpinionsApi = designOpinionsApi,
  ): Promise<ChangeOpinionRun | null> {
    if (busy.value) {
      return null;
    }

    clear();
    const subject = subjectOf(version.content_hash, target, request);
    const body = {
      design_version_id: version.id,
      design_content_hash: version.content_hash,
      request: subject.request,
      target,
      locale,
    };
    busy.value = true;
    askedFor.value = subject;
    const answer = authorize((token) => api.ask(project, body, token));
    return receive(round, answer);
  }

  function isStale(version: OpinionVersion, target: DesignChangeTarget, request: string): boolean {
    const asked = askedFor.value;
    return asked === null || !sameSubject(asked, subjectOf(version.content_hash, target, request));
  }

  return {
    current,
    busy,
    error,
    askedFor,
    ask,
    isStale,
    clear,
  };
});
