export interface GateReference {
  artifact: { artifact_id: string; version: number; content_hash: string };
}

export interface VersionReference {
  id: string;
  version_number: number;
  content_hash: string;
}

export function gateTargets(gate: GateReference | null, version: VersionReference | null): boolean {
  return (
    gate !== null &&
    version !== null &&
    gate.artifact.artifact_id === version.id &&
    gate.artifact.version === version.version_number &&
    gate.artifact.content_hash === version.content_hash
  );
}
