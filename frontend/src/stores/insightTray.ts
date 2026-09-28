import { defineStore } from "pinia";

import { DesignLoopApiError, type InsightBatchApi } from "../api/designLoop";
import type {
  InsightApplicationRequest,
  InsightBriefField,
  InsightSourceKind,
} from "../types/designLoop";
import type { AuthorizedDesignLoopRequest } from "./designLoop";

export const MAX_TRAY_ITEMS = 20;

export interface InsightTrayItem {
  sourceKind: InsightSourceKind;
  sourceId: string;
  sourceTwinId: string | null;
  text: string;
  briefField: InsightBriefField;
}

export interface InsightTrayResult {
  count: number;
  briefVersionNumber: number;
}

export interface InsightTrayFailure {
  code: string;
  sources: string[];
}

interface InsightTrayState {
  items: Record<string, InsightTrayItem[]>;
  results: Record<string, InsightTrayResult>;
  failures: Record<string, InsightTrayFailure>;
  applying: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function batchFailure(error: unknown): InsightTrayFailure {
  if (error instanceof DesignLoopApiError) {
    const detail = isRecord(error.payload) ? error.payload.detail : null;
    const sources = isRecord(detail) && Array.isArray(detail.sources) ? detail.sources : [];
    return {
      code: error.code ?? error.message,
      sources: sources.filter((source): source is string => typeof source === "string"),
    };
  }
  return {
    code: error instanceof Error ? error.message : "INSIGHT_BATCH_FAILED",
    sources: [],
  };
}

function sameSource(
  item: InsightTrayItem,
  sourceKind: InsightSourceKind,
  sourceId: string,
): boolean {
  return item.sourceKind === sourceKind && item.sourceId === sourceId;
}

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));
}

function briefRequest(item: InsightTrayItem): InsightApplicationRequest {
  return {
    source_kind: item.sourceKind,
    source_id: item.sourceId,
    source_twin_id: item.sourceTwinId,
    text: item.text,
    target: "BRIEF",
    brief_field: item.briefField,
  };
}

export const useInsightTrayStore = defineStore("insightTray", {
  state: (): InsightTrayState => ({
    items: {},
    results: {},
    failures: {},
    applying: [],
  }),

  getters: {
    itemsOf:
      (state) =>
      (projectId: string): InsightTrayItem[] =>
        state.items[projectId] ?? [],
    itemOf:
      (state) =>
      (
        projectId: string,
        sourceKind: InsightSourceKind,
        sourceId: string,
      ): InsightTrayItem | null =>
        (state.items[projectId] ?? []).find((item) => sameSource(item, sourceKind, sourceId)) ??
        null,
    isFull:
      (state) =>
      (projectId: string): boolean =>
        (state.items[projectId] ?? []).length >= MAX_TRAY_ITEMS,
    resultOf:
      (state) =>
      (projectId: string): InsightTrayResult | null =>
        state.results[projectId] ?? null,
    failureOf:
      (state) =>
      (projectId: string): InsightTrayFailure | null =>
        state.failures[projectId] ?? null,
    isApplying:
      (state) =>
      (projectId: string): boolean =>
        state.applying.includes(projectId),
    isVisible:
      (state) =>
      (projectId: string): boolean =>
        (state.items[projectId] ?? []).length > 0 || state.results[projectId] !== undefined,
  },

  actions: {
    add(projectId: string, item: InsightTrayItem): boolean {
      const items = this.items[projectId] ?? [];
      if (
        this.applying.includes(projectId) ||
        items.length >= MAX_TRAY_ITEMS ||
        items.some((known) => sameSource(known, item.sourceKind, item.sourceId))
      ) {
        return false;
      }
      this.items = { ...this.items, [projectId]: [...items, { ...item }] };
      this.results = without(this.results, projectId);
      this.failures = without(this.failures, projectId);
      return true;
    },

    remove(projectId: string, sourceKind: InsightSourceKind, sourceId: string): void {
      if (this.applying.includes(projectId)) return;
      const items = (this.items[projectId] ?? []).filter(
        (item) => !sameSource(item, sourceKind, sourceId),
      );
      this.items =
        items.length > 0 ? { ...this.items, [projectId]: items } : without(this.items, projectId);
      this.failures = without(this.failures, projectId);
    },

    clear(projectId: string): void {
      if (this.applying.includes(projectId)) return;
      this.items = without(this.items, projectId);
      this.failures = without(this.failures, projectId);
    },

    dismissResult(projectId: string): void {
      this.results = without(this.results, projectId);
    },

    async applyAll(
      projectId: string,
      api: InsightBatchApi,
      authorize: AuthorizedDesignLoopRequest,
    ): Promise<InsightTrayResult | null> {
      const items = this.items[projectId] ?? [];
      if (items.length === 0 || this.applying.includes(projectId)) return null;
      this.applying = [...this.applying, projectId];
      this.failures = without(this.failures, projectId);
      try {
        const payload = await authorize((token) =>
          api.applyInsightBatch(projectId, { items: items.map(briefRequest) }, token),
        );
        const result: InsightTrayResult = {
          count: payload.applications.length,
          briefVersionNumber: payload.brief_version_number,
        };
        this.items = without(this.items, projectId);
        this.results = { ...this.results, [projectId]: result };
        return result;
      } catch (error) {
        this.failures = { ...this.failures, [projectId]: batchFailure(error) };
        throw error;
      } finally {
        this.applying = this.applying.filter((item) => item !== projectId);
      }
    },
  },
});
