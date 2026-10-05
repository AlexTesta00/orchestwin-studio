import type { InjectionKey } from "vue";
import type { WhyApi } from "../api/why";

export interface WhyContext {
  projectId: () => string;
  authorize: <T>(operation: (token: string) => Promise<T>) => Promise<T>;
  api: WhyApi;
}

export const whyContextKey: InjectionKey<WhyContext> = Symbol("artifact-why");

export function twinClaimCode(twinId: string, version: number, observationKey: string): string {
  return `UT-${twinId.replaceAll("-", "").slice(0, 8).toUpperCase()}-v${version}:${observationKey}`;
}
