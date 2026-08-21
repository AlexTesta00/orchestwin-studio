import type {
  DeclarativePrototypePayload,
  DesignAlternativePayload,
  DesignPackagePayload,
  PrototypeElementPayload,
  PrototypeScreenPayload,
  PrototypeTransitionPayload,
} from "../types/design";

const UUID_WORD_SEEDS = [0x811c9dc5, 0x9e3779b9, 0x85ebca6b, 0xc2b2ae35] as const;
const MAX_PROTOTYPE_TITLE_LENGTH = 200;
const MAX_ELEMENT_CONTENT_LENGTH = 4000;

function hashWord(value: string, seed: number): number {
  let hash = seed >>> 0;

  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }

  return hash;
}

function stableUuid(value: string): string {
  const hexadecimal = UUID_WORD_SEEDS.map((seed) =>
    hashWord(value, seed).toString(16).padStart(8, "0"),
  ).join("");
  const versioned = `${hexadecimal.slice(0, 12)}5${hexadecimal.slice(13, 16)}8${hexadecimal.slice(17)}`;

  return [
    versioned.slice(0, 8),
    versioned.slice(8, 12),
    versioned.slice(12, 16),
    versioned.slice(16, 20),
    versioned.slice(20, 32),
  ].join("-");
}

function normalizedText(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function boundedText(value: string, maximumLength: number): string {
  const normalized = normalizedText(value);

  if (normalized.length <= maximumLength) {
    return normalized;
  }

  return `${normalized.slice(0, maximumLength - 3).trimEnd()}...`;
}

function codedValue(prefix: string, ordinal: number): string {
  return `${prefix}-${ordinal.toString().padStart(3, "0")}`;
}

function alternativeFor(
  packageValue: DesignPackagePayload,
  alternativeId: string,
): DesignAlternativePayload {
  const alternative = packageValue.alternatives.find((candidate) => candidate.id === alternativeId);

  if (alternative === undefined) {
    throw new Error("The selected design alternative does not belong to the current package");
  }

  return alternative;
}

function screenNarrative(alternative: DesignAlternativePayload, screenIndex: number): string {
  const workflow = alternative.workflows[screenIndex % Math.max(alternative.workflows.length, 1)];
  const workflowNarrative = workflow?.steps.join(" ") ?? alternative.rationale;

  return boundedText(`${alternative.summary} ${workflowNarrative}`, MAX_ELEMENT_CONTENT_LENGTH);
}

function staticElement(
  alternative: DesignAlternativePayload,
  kind: "HEADING" | "TEXT" | "STATUS",
  content: string,
  ordinal: number,
  screenIndex: number,
): PrototypeElementPayload {
  return {
    id: stableUuid(`${alternative.id}:screen:${screenIndex}:element:${ordinal}:${kind}`),
    code: codedValue("ELM", ordinal),
    kind,
    content: boundedText(content, MAX_ELEMENT_CONTENT_LENGTH),
    accessible_name: null,
    requirement_ids: [],
    user_story_ids: [],
    acceptance_criterion_ids: [],
    field_name: null,
    required: false,
    options: [],
  };
}

function navigationElement(
  alternative: DesignAlternativePayload,
  content: string,
  ordinal: number,
  screenIndex: number,
): PrototypeElementPayload {
  const normalized = boundedText(content, MAX_ELEMENT_CONTENT_LENGTH);

  return {
    id: stableUuid(`${alternative.id}:screen:${screenIndex}:element:${ordinal}:BUTTON`),
    code: codedValue("ELM", ordinal),
    kind: "BUTTON",
    content: normalized,
    accessible_name: normalized,
    requirement_ids: [...alternative.requirement_ids],
    user_story_ids: [...alternative.user_story_ids],
    acceptance_criterion_ids: [...alternative.acceptance_criterion_ids],
    field_name: null,
    required: false,
    options: [],
  };
}

function createPrototype(alternative: DesignAlternativePayload): DeclarativePrototypePayload {
  let elementOrdinal = 1;
  const triggerElementIds: string[] = [];
  const screens: PrototypeScreenPayload[] = alternative.information_architecture.map(
    (section, screenIndex) => {
      const heading = staticElement(alternative, "HEADING", section, elementOrdinal, screenIndex);
      elementOrdinal += 1;
      const narrative = staticElement(
        alternative,
        "TEXT",
        screenNarrative(alternative, screenIndex),
        elementOrdinal,
        screenIndex,
      );
      elementOrdinal += 1;
      const isLast = screenIndex === alternative.information_architecture.length - 1;
      const finalElement = isLast
        ? staticElement(
            alternative,
            "STATUS",
            "Prototype flow complete.",
            elementOrdinal,
            screenIndex,
          )
        : navigationElement(
            alternative,
            `Continue to ${alternative.information_architecture[screenIndex + 1] ?? "next step"}`,
            elementOrdinal,
            screenIndex,
          );
      elementOrdinal += 1;

      if (!isLast) {
        triggerElementIds.push(finalElement.id);
      }

      return {
        id: stableUuid(`${alternative.id}:screen:${screenIndex}`),
        code: codedValue("SCR", screenIndex + 1),
        title: boundedText(section, MAX_PROTOTYPE_TITLE_LENGTH),
        state: isLast ? "SUCCESS" : "DEFAULT",
        elements: [heading, narrative, finalElement],
        requirement_ids: [...alternative.requirement_ids],
        user_story_ids: [...alternative.user_story_ids],
        acceptance_criterion_ids: [...alternative.acceptance_criterion_ids],
      };
    },
  );
  const transitions: PrototypeTransitionPayload[] = triggerElementIds.map(
    (triggerElementId, index) => ({
      id: stableUuid(`${alternative.id}:transition:${index}`),
      code: codedValue("TRN", index + 1),
      source_screen_id: screens[index]?.id ?? "",
      trigger_element_id: triggerElementId,
      target_screen_id: screens[index + 1]?.id ?? "",
      outcome: boundedText(
        `The ${screens[index + 1]?.title ?? "next"} screen becomes visible.`,
        MAX_ELEMENT_CONTENT_LENGTH,
      ),
    }),
  );

  return {
    id: stableUuid(`${alternative.id}:prototype`),
    code: "PRT-001",
    title: boundedText(`${alternative.title} prototype`, MAX_PROTOTYPE_TITLE_LENGTH),
    design_alternative_id: alternative.id,
    entry_screen_id: screens[0]?.id ?? "",
    screens,
    transitions,
    supported_viewports: ["DESKTOP", "MOBILE", "TABLET"],
  };
}

export function buildSelectedDesignPackage(
  packageValue: DesignPackagePayload,
  alternativeId: string,
): DesignPackagePayload {
  const alternative = alternativeFor(packageValue, alternativeId);

  return {
    ...packageValue,
    owner_selected_alternative_id: alternative.id,
    prototype: createPrototype(alternative),
  };
}
