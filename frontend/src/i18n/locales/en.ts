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
    login: "Log in",
    logout: "Log out",
    menu: "Menu",
    openLabel: "Open primary navigation",
    overview: "Overview",
    projects: "Projects",
    register: "Register",
    skip: "Skip to main content",
  },
  auth: {
    email: "Email address",
    password: "Password",
    passwordHint: "Use at least 15 characters. Spaces and passphrases are supported.",
    submitting: "Please wait…",
    login: {
      eyebrow: "Local account",
      title: "Log in",
      description: "Continue to your OrchesTwin Studio projects.",
      submit: "Log in",
      noAccount: "No account yet?",
      registerLink: "Create one",
    },
    register: {
      eyebrow: "Local account",
      title: "Create your account",
      description: "Register a local owner account for your projects.",
      submit: "Register",
      hasAccount: "Already registered?",
      loginLink: "Log in",
    },
    errors: {
      invalid_authentication: "The email or password is not valid.",
      email_already_registered: "An account already uses this email address.",
      invalid_registration: "The registration data is not valid.",
      invalid_refresh_token: "Your session is no longer valid. Please log in again.",
      expired_refresh_token: "Your session expired. Please log in again.",
      refresh_token_reuse_detected:
        "The session was revoked because an old token was reused. Please log in again.",
      unexpected_api_error: "The server returned an unexpected response.",
      unexpected_error: "An unexpected error occurred.",
    },
  },
  overview: {
    capabilities: {
      api: "Versioned health API",
      backend: "Typed FastAPI backend",
      frontend: "Verified Vue frontend workspace",
    },
    capabilitiesTitle: "Foundation capabilities",
    description:
      "The current foundation provides independently verifiable backend and frontend workspaces. Project workflows will be introduced incrementally.",
    eyebrow: "Human-governed Agentic UCD",
    status: "Frontend workspace operational",
    title: "OrchesTwin Studio",
  },
  projects: {
    description: "Create and manage your structured software projects.",
    emptyDescription: "Create the first project to begin its Project Brief.",
    emptyTitle: "No projects yet",
    eyebrow: "Project workspace",
    title: "Projects",
  },
} as const;

export default messages;