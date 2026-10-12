import type { ChangeOpinionVerdict } from "../types/designOpinions";

export const VERDICT_STYLES: Readonly<Record<ChangeOpinionVerdict, string>> = {
  HELPS: "bg-petrol-on-night/12 text-petrol-on-night-2",
  SLOWS: "bg-warn-on-night/12 text-warn-on-night",
  BLOCKS: "bg-fail-on-night/12 text-fail-on-night",
};
