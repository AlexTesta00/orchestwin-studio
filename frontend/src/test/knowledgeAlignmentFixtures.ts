import type { DesignPackageDiffPayload } from "../types/design";
import type {
  AlignmentLatestRunPayload,
  AlignmentProposalListPayload,
  AlignmentProposalPayload,
  DesignChangeResultPayload,
  KnowledgeAlignmentRunSummaryPayload,
  ProposalApplyPayload,
  ProposalSection,
} from "../types/knowledgeAlignment";
import type {
  RequirementsRevisionPayload,
  RequirementsSpecificationDiffPayload,
} from "../types/requirements";

export const ALIGNMENT_PROJECT_ID = "11111111-1111-4111-8111-111111111111";
export const ALIGNMENT_RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const ALIGNMENT_FROM_COMMIT = "a1a1a1a2a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
export const ALIGNMENT_TO_COMMIT = "c0ffee1234567890abcdef1234567890abcdef12";
export const ALIGNMENT_MIDDLE_COMMIT = "b0b0b0b1b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0";

export const ALIGNMENT_EXCERPT = [
  "+  if (reservations.length === 0) {",
  '+    return <EmptyDay message="No reservation today" />;',
  "+  }",
].join("\n");

export function alignmentProposal(
  code: string,
  section: ProposalSection,
  overrides: Partial<AlignmentProposalPayload> = {},
): AlignmentProposalPayload {
  return {
    id: `00000000-0000-4000-8000-${code.replace("ALN-", "").padStart(12, "0")}`,
    run_id: ALIGNMENT_RUN_ID,
    code,
    section,
    title: `Proposal ${code}`,
    request: `Request of ${code}.`,
    rationale: `The diff of ${code} motivates it.`,
    subjects: { requirements: [], screens: [], criteria: [] },
    origin: {
      commits: [ALIGNMENT_TO_COMMIT],
      files: ["src/reservations.js"],
      excerpt: ALIGNMENT_EXCERPT,
    },
    status: "PROPOSED",
    created_at: "2026-10-06T09:00:00+00:00",
    decided_at: null,
    decision_note: null,
    applied_text: null,
    applied_diff_id: null,
    ...overrides,
  };
}

export const REQUIREMENTS_PROPOSAL = alignmentProposal("ALN-001", "REQUIREMENTS", {
  title: "The day without reservations",
  request:
    "Add to the requirement on the list of the day that an empty day shows a sentence instead of a blank page.",
  rationale: "The commit adds an empty state to the list of the reservations.",
  subjects: { requirements: ["REQ-003"], screens: ["SCR-001"], criteria: [] },
  origin: {
    commits: [ALIGNMENT_TO_COMMIT, ALIGNMENT_MIDDLE_COMMIT],
    files: ["src/reservations.js", "src/reservations.css"],
    excerpt: ALIGNMENT_EXCERPT,
  },
});

export const SECOND_REQUIREMENTS_PROPOSAL = alignmentProposal("ALN-004", "REQUIREMENTS", {
  title: "Search by surname",
  request: "Add a requirement: the reception finds a guest by surname.",
  rationale: "The commit adds a search box over the list.",
  origin: {
    commits: [ALIGNMENT_TO_COMMIT],
    files: ["src/search.js"],
    excerpt: "+export function findBySurname(guests, surname) {",
  },
});

export const DESIGN_PROPOSAL = alignmentProposal("ALN-002", "DESIGN", {
  title: "The empty state of the list screen",
  request: "Describe in the list screen the sentence shown when the day has no reservation.",
  rationale: "The screen of the code shows a sentence that the design does not mention.",
  subjects: { requirements: [], screens: ["SCR-001"], criteria: [] },
});

export const TESTS_PROPOSAL = alignmentProposal("ALN-003", "TESTS", {
  title: "Cover the empty day",
  request: "The test plan has to cover a day without reservations.",
  rationale: "No path of the plan opens the list on an empty day.",
  subjects: { requirements: ["REQ-003"], screens: [], criteria: ["AC-002"] },
});

export const LATEST_RUN: AlignmentLatestRunPayload = {
  id: ALIGNMENT_RUN_ID,
  from_commit: ALIGNMENT_FROM_COMMIT,
  to_commit: ALIGNMENT_TO_COMMIT,
  created_at: "2026-10-06T09:00:00+00:00",
  requirements_version_number: 2,
  design_version_number: 3,
  alternative_code: "DES-001",
  summary: "The code added an empty state and a search that the knowledge does not describe.",
};

export const RUN_SUMMARY: KnowledgeAlignmentRunSummaryPayload = {
  id: ALIGNMENT_RUN_ID,
  project_id: ALIGNMENT_PROJECT_ID,
  from_commit: ALIGNMENT_FROM_COMMIT,
  to_commit: ALIGNMENT_TO_COMMIT,
  commits: [ALIGNMENT_MIDDLE_COMMIT, ALIGNMENT_TO_COMMIT],
  locale: "it-IT",
  requirements_version_number: 2,
  design_version_number: 3,
  alternative_code: "DES-001",
  summary: LATEST_RUN.summary,
  created_at: "2026-10-06T09:00:00+00:00",
  cost_microusd: 420000,
  generation_ids: ["99999999-9999-4999-8999-999999999999"],
  waiting: 3,
  proposals_count: 4,
};

export function proposalList(
  items: AlignmentProposalPayload[],
  latestRun: AlignmentLatestRunPayload | null = LATEST_RUN,
): AlignmentProposalListPayload {
  return { items, latest_run: latestRun };
}

export function requirementsRevision(diffId: string | null): RequirementsRevisionPayload {
  return {
    status: diffId === null ? "NO_CHANGE" : "CREATED",
    diff:
      diffId === null
        ? null
        : ({ id: diffId, status: "PROPOSED" } as unknown as RequirementsSpecificationDiffPayload),
    version: null,
    issue: null,
    proposal_issue: null,
    diff_persistence_status: diffId === null ? null : "APPENDED",
    version_persistence_status: null,
  };
}

export function designChangeResult(diffId: string, changes: string[]): DesignChangeResultPayload {
  return {
    revision: {
      status: "CREATED",
      diff: { id: diffId, status: "PROPOSED" } as unknown as DesignPackageDiffPayload,
      version: null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: null,
      version_persistence_status: null,
    },
    changes,
  };
}

export function appliedProposal(
  proposal: AlignmentProposalPayload,
  text: string | null,
  diffId: string | null,
): AlignmentProposalPayload {
  return {
    ...proposal,
    status: "APPLIED",
    decided_at: "2026-10-06T10:00:00+00:00",
    applied_text: text ?? proposal.request,
    applied_diff_id: diffId,
  };
}

export function skippedProposal(
  proposal: AlignmentProposalPayload,
  reason: string | null,
): AlignmentProposalPayload {
  return {
    ...proposal,
    status: "SKIPPED",
    decided_at: "2026-10-06T10:00:00+00:00",
    decision_note: reason,
  };
}

export function applyAnswer(
  proposal: AlignmentProposalPayload,
  text: string | null,
  diffId: string | null,
): ProposalApplyPayload {
  const applied = appliedProposal(proposal, text, diffId);

  if (proposal.section === "TESTS" || diffId === null) {
    return { proposal: applied, revision: null };
  }

  return {
    proposal: applied,
    revision:
      proposal.section === "DESIGN"
        ? designChangeResult(diffId, ["The list screen describes the empty day."])
        : requirementsRevision(diffId),
  };
}
