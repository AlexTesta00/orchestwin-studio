import type { LayoutArchetype, VisualChoicesPayload, VisualLanguagePayload } from "../types/design";

export type VisualLocale = "en" | "it";

export const NEUTRAL_CHOICES: VisualChoicesPayload = {
  archetype: "SINGLE_CARD",
  hue_family: "SLATE",
  color_scheme: "NEUTRAL_ACCENT",
  color_mode: "LIGHT",
  saturation: "MUTED",
  surface_tone: "NEUTRAL",
  heading_family: "SYSTEM_UI",
  body_family: "SYSTEM_UI",
  type_scale: "REGULAR",
  heading_case: "SENTENCE",
  heading_weight: "SEMIBOLD",
  corners: "SOFT",
  density: "COMFORTABLE",
  buttons: "FILLED",
  inputs: "BOXED",
  elevation: "SUBTLE",
  borders: "HAIRLINE",
  navigation: "NONE",
  header: "COMPACT_BAR",
  background: "PLAIN",
  emphasis: "BALANCED",
  tone: "ESSENTIAL",
};

export const NEUTRAL_TOKENS: Record<string, string> = {
  "--vl-color-background": "#fafafa",
  "--vl-color-surface": "#fefefe",
  "--vl-color-surface-alt": "#f0f0f0",
  "--vl-color-border": "#dedede",
  "--vl-color-text": "#292929",
  "--vl-color-text-muted": "#636363",
  "--vl-color-primary": "#69737d",
  "--vl-color-on-primary": "#ffffff",
  "--vl-color-primary-soft": "#e2edf8",
  "--vl-color-accent": "#72777e",
  "--vl-color-on-accent": "#ffffff",
  "--vl-color-success": "#476e4f",
  "--vl-color-success-soft": "#d5f5da",
  "--vl-color-danger": "#85554e",
  "--vl-color-danger-soft": "#ffe4e0",
  "--vl-font-heading":
    'system-ui, -apple-system, "Segoe UI Variable", "Segoe UI", Roboto, sans-serif',
  "--vl-font-body": 'system-ui, -apple-system, "Segoe UI Variable", "Segoe UI", Roboto, sans-serif',
  "--vl-heading-weight": "700",
  "--vl-heading-transform": "none",
  "--vl-heading-variant": "normal",
  "--vl-heading-tracking": "0",
  "--vl-size-body": "16px",
  "--vl-size-title": "24px",
  "--vl-size-display": "32px",
  "--vl-line-height": "1.55",
  "--vl-space": "10px",
  "--vl-gap": "16px",
  "--vl-control-height": "44px",
  "--vl-radius-control": "8px",
  "--vl-radius-panel": "12px",
  "--vl-border-width": "1px",
  "--vl-shadow": "0 1px 2px rgba(0, 0, 0, 0.06)",
};

export const ARCHETYPE_LABELS: Record<VisualLocale, Record<LayoutArchetype, string>> = {
  en: {
    GUIDED_STEPS: "Guided steps",
    SINGLE_CARD: "Single card",
    LIST_DETAIL: "List and detail",
    DASHBOARD: "Dashboard",
    SPLIT_SCREEN: "Split screen",
    CONVERSATIONAL: "Conversational",
    TABLE_FIRST: "Table first",
    CARD_GALLERY: "Card gallery",
    FEED_TIMELINE: "Feed and timeline",
    KANBAN_BOARD: "Kanban board",
    SEARCH_FIRST: "Search first",
    FOCUS_MODE: "Focus mode",
  },
  it: {
    GUIDED_STEPS: "Passi guidati",
    SINGLE_CARD: "Scheda unica",
    LIST_DETAIL: "Elenco e dettaglio",
    DASHBOARD: "Cruscotto",
    SPLIT_SCREEN: "Schermo diviso",
    CONVERSATIONAL: "Conversazionale",
    TABLE_FIRST: "Tabella",
    CARD_GALLERY: "Galleria di schede",
    FEED_TIMELINE: "Flusso e cronologia",
    KANBAN_BOARD: "Bacheca kanban",
    SEARCH_FIRST: "Ricerca",
    FOCUS_MODE: "Un passo alla volta",
  },
};

const DIMENSION_LABELS: Record<VisualLocale, Record<string, string>> = {
  en: {
    color_mode: "Mode",
    tone: "Tone",
    density: "Density",
    corners: "Corners",
    heading_family: "Headings",
    body_family: "Body",
    navigation: "Navigation",
    hue_family: "Hue",
  },
  it: {
    color_mode: "Modalità",
    tone: "Tono",
    density: "Densità",
    corners: "Angoli",
    heading_family: "Titoli",
    body_family: "Testo",
    navigation: "Navigazione",
    hue_family: "Tinta",
  },
};

export function dimensionLabel(locale: VisualLocale, dimension: string): string {
  return DIMENSION_LABELS[locale][dimension] ?? dimension.replace(/_/g, " ");
}

export function valueLabel(value: string): string {
  const text = value.toLowerCase().replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function archetypeLabel(locale: VisualLocale, archetype: LayoutArchetype): string {
  return ARCHETYPE_LABELS[locale][archetype];
}

export function visualChoices(
  visual: VisualLanguagePayload | null | undefined,
): VisualChoicesPayload {
  return visual?.choices ?? NEUTRAL_CHOICES;
}

export function visualTokens(
  visual: VisualLanguagePayload | null | undefined,
): Record<string, string> {
  return visual?.tokens ?? NEUTRAL_TOKENS;
}

export function tokenStyle(
  visual: VisualLanguagePayload | null | undefined,
): Record<string, string> {
  const tokens = visualTokens(visual);
  return Object.fromEntries(
    Object.entries(tokens).filter(([name, value]) => name.startsWith("--vl-") && value.length > 0),
  );
}

export function shellClasses(choices: VisualChoicesPayload): string[] {
  return [
    `vl-shell-${choices.archetype}`,
    `vl-nav-${choices.navigation}`,
    `vl-header-${choices.header}`,
    `vl-bg-${choices.background}`,
    `vl-buttons-${choices.buttons}`,
    `vl-inputs-${choices.inputs}`,
    `vl-emphasis-${choices.emphasis}`,
  ];
}
