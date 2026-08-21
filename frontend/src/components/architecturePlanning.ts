import type { ArchitecturePackagePayload } from "../types/architecture";

export function normalizeArchitectureOpenQuestions(value: string): string[] {
  const questions = value
    .split(/\r?\n/)
    .map((question) => question.trim().replace(/\s+/g, " "))
    .filter((question) => question.length > 0);

  return [...new Set(questions)];
}

export function buildArchitecturePackageRevision(
  current: ArchitecturePackagePayload,
  openQuestions: string,
): ArchitecturePackagePayload {
  return {
    ...current,
    open_questions: normalizeArchitectureOpenQuestions(openQuestions),
  };
}
