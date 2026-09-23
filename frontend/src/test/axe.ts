import axe, { type AxeResults, type RunOptions } from "axe-core";
import { expect } from "vitest";

const PAGE_RULES = ["page-has-heading-one", "landmark-one-main", "region", "bypass"];

export interface AccessibilityOptions {
  page?: boolean;
  disabledRules?: string[];
}

function describeViolations(results: AxeResults): string[] {
  return results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact ?? "unknown"}): ${violation.help} -> ${violation.nodes
        .map((node) => node.target.join(" "))
        .join(" | ")}`,
  );
}

export async function expectAccessible(
  root: Element,
  options: AccessibilityOptions = {},
): Promise<void> {
  const disabled = [
    ...(options.page ? [] : PAGE_RULES),
    "color-contrast",
    ...(options.disabledRules ?? []),
  ];
  const runOptions: RunOptions = {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] },
    rules: Object.fromEntries(disabled.map((rule) => [rule, { enabled: false }])),
  };
  const detached = !root.isConnected;
  if (detached) {
    document.body.appendChild(root);
  }
  try {
    const results = await axe.run(root, runOptions);
    const violations = describeViolations(results);
    expect(violations.join(" || ")).toBe("");
  } finally {
    if (detached) {
      root.remove();
    }
  }
}
