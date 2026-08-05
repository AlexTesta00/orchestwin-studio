const messages = {
  app: {
    homeAriaLabel: "OrchesTwin Studio home",
    title: "OrchesTwin Studio",
  },
  locale: {
    en: "English",
    it: "Italian",
    label: "Language",
  },
  navigation: {
    close: "Close",
    closeLabel: "Close primary navigation",
    label: "Primary navigation",
    menu: "Menu",
    openLabel: "Open primary navigation",
    overview: "Overview",
    projects: "Projects",
    skip: "Skip to main content",
  },
  overview: {
    capabilities: {
      api: "Versioned health API",
      backend: "Typed FastAPI backend",
      frontend: "Verified Vue frontend workspace",
    },
    capabilitiesTitle: "Foundation capabilities",
    description:
      "The current foundation provides independently verifiable backend and frontend workspaces. Project workflows will be introduced in later sprints.",
    eyebrow: "Human-governed Agentic UCD",
    status: "Frontend workspace operational",
    title: "OrchesTwin Studio",
  },
  projects: {
    description: "Project intake and versioned briefs will be introduced in Sprint 02.",
    emptyDescription:
      "The foundation sprint verifies navigation and workspace structure without creating domain data prematurely.",
    emptyTitle: "No projects yet",
    eyebrow: "Project workspace",
    title: "Projects",
  },
} as const;

export default messages;
