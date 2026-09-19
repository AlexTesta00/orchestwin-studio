const labels: Record<string, readonly [string, string]> = {
  NOT_SUBMITTED: ["Da confermare", "Not yet submitted"],
  DRAFT: ["Bozza", "Draft"],
  PROPOSED: ["Da valutare", "Ready for review"],
  PENDING_APPROVAL: ["In attesa della tua conferma", "Waiting for your approval"],
  APPROVED: ["Approvato", "Approved"],
  ACCEPTED: ["Accettato", "Accepted"],
  REJECTED: ["Rifiutato", "Rejected"],
  REVISION_REQUESTED: ["Modifiche richieste", "Changes requested"],
  PAUSED: ["In pausa", "Paused"],
  PAUSED_NEEDS_HUMAN: ["Serve il tuo intervento", "Your input is needed"],
  CANCELLED: ["Annullato", "Cancelled"],
  STALE: ["Da aggiornare", "Needs updating"],
  READY: ["Pronto", "Ready"],
  COMPLETED: ["Completato", "Complete"],
  RUNNING: ["In corso", "In progress"],
  FAILED: ["Non completato", "Not completed"],
  BLOCKED: ["Serve una modifica", "A change is needed"],
};

export function workflowStatusLabel(status: string | null | undefined, locale: string): string {
  const entry = labels[status ?? "NOT_SUBMITTED"];
  return (
    entry?.[locale.startsWith("it") ? 0 : 1] ??
    (locale.startsWith("it") ? "Da verificare" : "Needs review")
  );
}
