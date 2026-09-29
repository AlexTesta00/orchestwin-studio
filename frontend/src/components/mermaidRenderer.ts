export interface DiagramRenderer {
  render(id: string, source: string): Promise<string>;
}

export interface DiagramLink {
  code: string;
  label: string;
}

interface MermaidModule {
  initialize(configuration: Record<string, unknown>): void;
  render(id: string, source: string, container?: Element): Promise<{ svg: string }>;
}

export type MermaidLoader = () => Promise<{ default: MermaidModule }>;

export const DIAGRAM_SANDBOX_ATTRIBUTE = "data-diagram-sandbox";

const DIAGRAM_FONT_FACE = "Geist";
const DIAGRAM_FONT_SIZE = "15px";
const DIAGRAM_FONT_WEIGHTS = ["", "bold "] as const;
const DIAGRAM_FONT = `"${DIAGRAM_FONT_FACE}", ui-sans-serif, system-ui, sans-serif`;

export const DIAGRAM_TOKENS = {
  "night-deep": "#0c0e0f",
  "night-panel": "#15181a",
  "on-night": "#f3f4f4",
  "on-night-2": "#c9cfd1",
  "petrol-on-night": "#5fb3bb",
  "petrol-on-night-2": "#8fc0c5",
  "warn-on-night": "#e0c08e",
} as const;

const NODE_FILL = "#1b2124";
const GROUP_FILL = "#121517";
const GROUP_LINE = "#3a4144";
const NOTE_FILL = "#221d14";

export const DIAGRAM_BACKGROUND = DIAGRAM_TOKENS["night-deep"];

export const MERMAID_CONFIGURATION = {
  startOnLoad: false,
  securityLevel: "strict",
  theme: "base",
  fontFamily: DIAGRAM_FONT,
  flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis", padding: 16 },
  state: { useMaxWidth: false },
  requirement: { useMaxWidth: false },
  usecase: {
    useMaxWidth: false,
    actorFontFamily: DIAGRAM_FONT,
    usecaseFontFamily: DIAGRAM_FONT,
  },
  themeVariables: {
    darkMode: true,
    dropShadow: "none",
    fontFamily: DIAGRAM_FONT,
    fontSize: DIAGRAM_FONT_SIZE,
    background: DIAGRAM_TOKENS["night-deep"],
    primaryColor: NODE_FILL,
    primaryBorderColor: DIAGRAM_TOKENS["petrol-on-night"],
    primaryTextColor: DIAGRAM_TOKENS["on-night"],
    secondaryColor: DIAGRAM_TOKENS["night-panel"],
    secondaryBorderColor: GROUP_LINE,
    secondaryTextColor: DIAGRAM_TOKENS["on-night"],
    tertiaryColor: GROUP_FILL,
    tertiaryBorderColor: GROUP_LINE,
    tertiaryTextColor: DIAGRAM_TOKENS["on-night-2"],
    lineColor: DIAGRAM_TOKENS["petrol-on-night-2"],
    arrowheadColor: DIAGRAM_TOKENS["petrol-on-night-2"],
    textColor: DIAGRAM_TOKENS["on-night"],
    mainBkg: NODE_FILL,
    nodeBorder: DIAGRAM_TOKENS["petrol-on-night"],
    nodeTextColor: DIAGRAM_TOKENS["on-night"],
    clusterBkg: GROUP_FILL,
    clusterBorder: GROUP_LINE,
    titleColor: DIAGRAM_TOKENS["on-night-2"],
    edgeLabelBackground: DIAGRAM_TOKENS["night-deep"],
    labelBackgroundColor: DIAGRAM_TOKENS["night-deep"],
    actorBkg: NODE_FILL,
    actorBorder: DIAGRAM_TOKENS["petrol-on-night"],
    actorTextColor: DIAGRAM_TOKENS["on-night"],
    actorLineColor: DIAGRAM_TOKENS["petrol-on-night"],
    noteBkgColor: NOTE_FILL,
    noteBorderColor: DIAGRAM_TOKENS["warn-on-night"],
    noteTextColor: DIAGRAM_TOKENS["on-night"],
    requirementBackground: NODE_FILL,
    requirementBorderColor: DIAGRAM_TOKENS["petrol-on-night"],
    requirementTextColor: DIAGRAM_TOKENS["on-night"],
    relationColor: DIAGRAM_TOKENS["petrol-on-night-2"],
    relationLabelBackground: DIAGRAM_TOKENS["night-deep"],
    relationLabelColor: DIAGRAM_TOKENS["on-night-2"],
    compositeBackground: GROUP_FILL,
    compositeTitleBackground: NODE_FILL,
    compositeBorder: GROUP_LINE,
    stateLabelColor: DIAGRAM_TOKENS["on-night"],
  },
} as const;

const defaultLoader: MermaidLoader = () =>
  import("mermaid") as unknown as Promise<{ default: MermaidModule }>;

function diagramSandbox(): HTMLElement {
  const existing = document.querySelector<HTMLElement>(`[${DIAGRAM_SANDBOX_ATTRIBUTE}]`);

  if (existing !== null) {
    return existing;
  }

  const element = document.createElement("div");
  element.setAttribute(DIAGRAM_SANDBOX_ATTRIBUTE, "");
  element.setAttribute("aria-hidden", "true");
  document.body.append(element);
  return element;
}

async function diagramFontReady(): Promise<void> {
  const fonts = (document as Partial<Document>).fonts;

  if (fonts === undefined || typeof fonts.load !== "function") {
    return;
  }

  await Promise.all(
    DIAGRAM_FONT_WEIGHTS.map((weight) =>
      fonts.load(`${weight}${DIAGRAM_FONT_SIZE} "${DIAGRAM_FONT_FACE}"`).catch(() => []),
    ),
  );
}

export function createMermaidRenderer(loader: MermaidLoader = defaultLoader): DiagramRenderer {
  let ready: Promise<MermaidModule> | null = null;
  let queue: Promise<unknown> = Promise.resolve();

  function mermaid(): Promise<MermaidModule> {
    ready ??= loader()
      .then((module) => {
        module.default.initialize({ ...MERMAID_CONFIGURATION });
        return module.default;
      })
      .catch((error: unknown) => {
        ready = null;
        throw error;
      });
    return ready;
  }

  return {
    render(id, source) {
      const result = queue.then(async () => {
        const engine = await mermaid();
        await diagramFontReady();
        const { svg } = await engine.render(id, source, diagramSandbox());
        return svg;
      });
      queue = result.catch(() => undefined);
      return result;
    },
  };
}

export const mermaidRenderer = createMermaidRenderer();
