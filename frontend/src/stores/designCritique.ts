import { defineStore } from "pinia";
import { computed, reactive, ref } from "vue";

import {
  designCritiqueApi,
  DesignCritiqueApiError,
  type DesignCritiqueApi,
} from "../api/designCritique";
import type {
  DesignCritiqueRunPayload,
  DesignCritiqueSourcePayload,
} from "../types/designCritique";
import { errorCodeOf, errorStatusOf } from "./designMockups";

export type AuthorizedCritiqueRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

export const CRITIQUE_FILE_TYPE = "DESIGN_CRITIQUE_FILE_TYPE";
export const CRITIQUE_FILE_TOO_LARGE = "DESIGN_CRITIQUE_FILE_TOO_LARGE";
export const CRITIQUE_IMAGE_TOO_LARGE = "DESIGN_CRITIQUE_IMAGE_TOO_LARGE";
export const CRITIQUE_FAILED = "DESIGN_CRITIQUE_FAILED";
export const CRITIQUE_LOAD_FAILED = "DESIGN_CRITIQUE_LOAD_FAILED";
export const CRITIQUE_UPLOAD_FAILED = "DESIGN_CRITIQUE_UPLOAD_FAILED";
export const CRITIQUE_SHOT_DISCARDED = "DESIGN_CRITIQUE_SHOT_DISCARDED";
export const CRITIQUE_MAX_FILE_BYTES = 5 * 1024 * 1024;
export const CRITIQUE_FILE_TYPES: readonly string[] = ["image/png", "image/jpeg"];

const CONTENT_TOO_LARGE = 413;

export interface DesignCritiqueFailure {
  code: string;
  message: string;
}

export interface DesignCritiquePending {
  load: boolean;
  upload: boolean;
  critique: boolean;
}

interface UploadedSource {
  projectId: string;
  file: File;
  title: string | null;
  source: DesignCritiqueSourcePayload;
}

export function critiqueFileProblem(file: Blob): string | null {
  if (!CRITIQUE_FILE_TYPES.includes(file.type)) {
    return CRITIQUE_FILE_TYPE;
  }

  return file.size > CRITIQUE_MAX_FILE_BYTES ? CRITIQUE_FILE_TOO_LARGE : null;
}

export function critiqueForm(file: File, title: string | null): FormData {
  const form = new FormData();
  form.append("kind", "IMAGE");

  if (title !== null) {
    form.append("title", title);
  }

  form.append("shots", file);
  return form;
}

function failureOf(error: unknown, fallback: string): DesignCritiqueFailure {
  const code =
    errorCodeOf(error) ??
    (errorStatusOf(error) === CONTENT_TOO_LARGE ? CRITIQUE_IMAGE_TOO_LARGE : fallback);
  return { code, message: error instanceof Error ? error.message : code };
}

function cleanTitle(title: string | null): string | null {
  const value = title?.trim() ?? "";
  return value.length === 0 ? null : value;
}

export const useDesignCritiqueStore = defineStore("designCritique", () => {
  const projectId = ref<string | null>(null);
  const runs = ref<DesignCritiqueRunPayload[]>([]);
  const sources = ref<DesignCritiqueSourcePayload[]>([]);
  const pending = reactive<DesignCritiquePending>({ load: false, upload: false, critique: false });
  const error = ref<DesignCritiqueFailure | null>(null);
  const lastRun = ref<DesignCritiqueRunPayload | null>(null);
  const loaded = ref(false);

  const shotUrls = new Map<string, string>();
  const shotLoads = new Map<string, Promise<string>>();
  let epoch = 0;
  let shotEpoch = 0;
  let uploaded: UploadedSource | null = null;

  const latestRun = computed(() => runs.value[0] ?? null);
  const isBusy = computed(() => pending.load || pending.upload || pending.critique);

  function isCurrent(project: string, round: number): boolean {
    return projectId.value === project && epoch === round;
  }

  function revokeShotUrls(): void {
    shotEpoch += 1;
    for (const url of shotUrls.values()) {
      URL.revokeObjectURL(url);
    }
    shotUrls.clear();
    shotLoads.clear();
  }

  function reset(): void {
    revokeShotUrls();
    epoch += 1;
    projectId.value = null;
    runs.value = [];
    sources.value = [];
    pending.load = false;
    pending.upload = false;
    pending.critique = false;
    error.value = null;
    lastRun.value = null;
    loaded.value = false;
    uploaded = null;
  }

  function enter(project: string): number {
    if (projectId.value !== project) {
      reset();
      projectId.value = project;
    }

    return epoch;
  }

  function keepSource(source: DesignCritiqueSourcePayload): void {
    sources.value = [source, ...sources.value.filter((item) => item.id !== source.id)];
  }

  function keepRun(run: DesignCritiqueRunPayload): void {
    runs.value = [run, ...runs.value.filter((item) => item.id !== run.id)];
    lastRun.value = run;
  }

  async function load(
    project: string,
    authorize: AuthorizedCritiqueRequest,
    api: DesignCritiqueApi = designCritiqueApi,
  ): Promise<void> {
    const round = enter(project);
    pending.load = true;
    error.value = null;

    try {
      const [known, supplied] = await Promise.all([
        authorize((token) => api.runs(project, token)),
        authorize((token) => api.sources(project, token)).catch(() => null),
      ]);

      if (isCurrent(project, round)) {
        runs.value = known;
        sources.value = supplied ?? sources.value;
        loaded.value = true;
      }
    } catch (caught) {
      if (isCurrent(project, round)) {
        error.value = failureOf(caught, CRITIQUE_LOAD_FAILED);
      }
      throw caught;
    } finally {
      if (isCurrent(project, round)) {
        pending.load = false;
      }
    }
  }

  async function upload(
    project: string,
    round: number,
    file: File,
    title: string | null,
    authorize: AuthorizedCritiqueRequest,
    api: DesignCritiqueApi,
  ): Promise<DesignCritiqueSourcePayload> {
    const known = uploaded;

    if (
      known !== null &&
      known.projectId === project &&
      known.file === file &&
      known.title === title
    ) {
      return known.source;
    }

    pending.upload = true;

    try {
      const source = await authorize((token) =>
        api.uploadSource(project, critiqueForm(file, title), token),
      );

      if (isCurrent(project, round)) {
        uploaded = { projectId: project, file, title, source };
        keepSource(source);
      }

      return source;
    } catch (caught) {
      if (isCurrent(project, round)) {
        error.value = failureOf(caught, CRITIQUE_UPLOAD_FAILED);
      }
      throw caught;
    } finally {
      if (isCurrent(project, round)) {
        pending.upload = false;
      }
    }
  }

  async function critiqueImage(
    project: string,
    file: File,
    title: string | null,
    locale: string,
    authorize: AuthorizedCritiqueRequest,
    api: DesignCritiqueApi = designCritiqueApi,
  ): Promise<DesignCritiqueRunPayload> {
    const round = enter(project);
    const problem = critiqueFileProblem(file);
    error.value = null;

    if (problem !== null) {
      error.value = { code: problem, message: problem };
      throw new DesignCritiqueApiError("The image cannot be sent to the Studio", {
        status: 0,
        code: problem,
        payload: null,
      });
    }

    const named = cleanTitle(title);
    const source = await upload(project, round, file, named, authorize, api);

    if (!isCurrent(project, round)) {
      throw new DesignCritiqueApiError("The project changed before the critique", {
        status: 0,
        code: CRITIQUE_FAILED,
        payload: null,
      });
    }

    pending.critique = true;

    try {
      const result = await authorize((token) =>
        api.critique(project, { source_id: source.id, locale }, token),
      );

      if (isCurrent(project, round)) {
        uploaded = null;
        keepRun(result.run);
      }

      return result.run;
    } catch (caught) {
      if (isCurrent(project, round)) {
        error.value = failureOf(caught, CRITIQUE_FAILED);
      }
      throw caught;
    } finally {
      if (isCurrent(project, round)) {
        pending.critique = false;
      }
    }
  }

  async function fetchShot(
    key: string,
    project: string,
    sourceId: string,
    code: string,
    authorize: AuthorizedCritiqueRequest,
    api: DesignCritiqueApi,
  ): Promise<string> {
    const round = shotEpoch;
    const blob = await authorize((token) => api.shot(project, sourceId, code, token));
    const url = URL.createObjectURL(blob);

    if (round !== shotEpoch) {
      URL.revokeObjectURL(url);
      throw new DesignCritiqueApiError("The preview was dropped", {
        status: 0,
        code: CRITIQUE_SHOT_DISCARDED,
        payload: null,
      });
    }

    shotUrls.set(key, url);
    return url;
  }

  async function shotUrl(
    project: string,
    sourceId: string,
    code: string,
    authorize: AuthorizedCritiqueRequest,
    api: DesignCritiqueApi = designCritiqueApi,
  ): Promise<string> {
    const key = `${project}|${sourceId}|${code}`;
    const known = shotUrls.get(key);

    if (known !== undefined) {
      return known;
    }

    const loading = shotLoads.get(key);

    if (loading !== undefined) {
      return loading;
    }

    const request = fetchShot(key, project, sourceId, code, authorize, api);
    shotLoads.set(key, request);

    try {
      return await request;
    } finally {
      if (shotLoads.get(key) === request) {
        shotLoads.delete(key);
      }
    }
  }

  return {
    projectId,
    runs,
    sources,
    pending,
    error,
    lastRun,
    loaded,
    latestRun,
    isBusy,
    reset,
    load,
    critiqueImage,
    shotUrl,
    revokeShotUrls,
  };
});
