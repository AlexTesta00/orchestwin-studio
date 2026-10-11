import { computed, type ComputedRef } from "vue";

import { gateTargets, type GateReference, type VersionReference } from "@/components/gateTargets";
import { formatDate } from "@/components/textFormat";
import { workflowStatusLabel } from "@/components/workflowLabels";
import type { HumanGateStatus } from "@/types/design";

export const QUOTE_CLASS =
  "m-0 border-l-2 border-on-night/40 pl-3 leading-normal whitespace-pre-line text-on-night-2";

interface Gate extends GateReference {
  id: string;
  iteration: number;
  status: HumanGateStatus;
}

interface GateVersion extends VersionReference {
  based_on_version_number: number | null;
  created_at: string;
  ready_for_gate?: boolean;
}

interface GateCopy {
  revisionTitle: string;
  rejectedTitle: string;
  cancelledTitle: string;
  decisionCounter: string;
  contentHash: string;
  basedOn: string;
  none: string;
  created: string;
  approval: string;
}

interface GateStateOptions {
  store: {
    gate: Gate | null;
    gateEvents: readonly { gate_id: string; kind: string; reason: string | null }[];
  };
  version: ComputedRef<GateVersion | null>;
  copy: ComputedRef<GateCopy>;
  locale: () => string;
  revision: () => boolean;
  readyForGate?: boolean;
}

export function useGateState({
  store,
  version,
  copy,
  locale,
  revision,
  readyForGate = false,
}: GateStateOptions) {
  const gateTargetsCurrent = computed(() => gateTargets(store.gate, version.value));
  const canSubmitGate = computed(() => {
    const current = version.value;
    if (current === null || (readyForGate && !current.ready_for_gate)) {
      return false;
    }
    if (store.gate === null || !gateTargetsCurrent.value) {
      return true;
    }
    return store.gate.status === "DRAFT" || store.gate.status === "STALE";
  });
  const gatePending = computed(
    () => gateTargetsCurrent.value && store.gate?.status === "PENDING_APPROVAL",
  );
  const gatePaused = computed(() => gateTargetsCurrent.value && store.gate?.status === "PAUSED");
  const gateStatus = computed<HumanGateStatus | null>(() =>
    gateTargetsCurrent.value ? (store.gate?.status ?? null) : null,
  );
  const closedTitle = computed(() => {
    if (revision()) {
      return copy.value.revisionTitle;
    }
    return gateStatus.value === "REJECTED" ? copy.value.rejectedTitle : copy.value.cancelledTitle;
  });
  const closedNote = computed(() => {
    const kind = revision() ? "REQUEST_REVISION" : "REJECT";
    const gateId = store.gate?.id;
    return (
      store.gateEvents
        .filter((event) => event.gate_id === gateId && event.kind === kind)
        .at(-1)
        ?.reason?.trim() ?? ""
    );
  });
  const versionRows = computed(() => {
    const current = version.value;
    if (current === null) {
      return [];
    }
    const text = copy.value;
    const gate = store.gate;
    const counter = text.decisionCounter.replace("{n}", String(gate?.iteration ?? 1));
    return [
      { label: text.contentHash, value: current.content_hash },
      {
        label: text.basedOn,
        value:
          current.based_on_version_number === null
            ? text.none
            : String(current.based_on_version_number),
      },
      { label: text.created, value: formatDate(current.created_at, locale()) },
      {
        label: text.approval,
        value:
          gate === null
            ? workflowStatusLabel(null, locale())
            : `${workflowStatusLabel(gate.status, locale())} · ${counter}`,
      },
    ];
  });
  return {
    canSubmitGate,
    gatePending,
    gatePaused,
    gateStatus,
    closedTitle,
    closedNote,
    versionRows,
  };
}
