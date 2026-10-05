import { shallowReactive } from "vue";
import type { ProjectImportPayload } from "../types/projectImports";

const results = shallowReactive(new Map<string, ProjectImportPayload>());

export function rememberProjectImportResult(result: ProjectImportPayload): void {
  results.set(result.project.id, result);
}

export function projectImportResult(projectId: string): ProjectImportPayload | undefined {
  return results.get(projectId);
}
