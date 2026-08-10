import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type {
  AuthenticationApi,
  AuthenticationInput,
  AuthenticationResponse,
  ProjectApi,
  ProjectBriefInput,
  ProjectBriefVersionResponse,
  ProjectCreateInput,
  ProjectResponse,
  UserResponse,
} from "@/api/contracts";
import { useAuthStore } from "@/stores/auth";

import { useProjectsStore } from "./projects";

const USER: UserResponse = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "owner@example.com",
  is_active: true,
  created_at: "2026-08-10T12:00:00Z",
};

const PROJECT: ProjectResponse = {
  id: "00000000-0000-4000-8000-000000000010",
  display_name: "Project",
  mode: "GREENFIELD_GENERATION",
  current_brief_version: 0,
  is_archived: false,
  created_at: "2026-08-10T12:00:00Z",
  updated_at: "2026-08-10T12:00:00Z",
};

class FakeApplicationApi implements AuthenticationApi, ProjectApi {
  public async register(input: AuthenticationInput): Promise<AuthenticationResponse> {
    void input;

    throw new Error("not used");
  }

  public async login(input: AuthenticationInput): Promise<AuthenticationResponse> {
    void input;

    throw new Error("not used");
  }

  public async refresh(): Promise<AuthenticationResponse> {
    throw new Error("not used");
  }

  public async logout(): Promise<void> {
    return undefined;
  }

  public async me(accessToken: string): Promise<UserResponse> {
    void accessToken;

    return USER;
  }

  public async createProject(
    accessToken: string,
    input: ProjectCreateInput,
  ): Promise<ProjectResponse> {
    void accessToken;

    return {
      ...PROJECT,
      display_name: input.display_name,
      mode: input.mode,
    };
  }

  public async listProjects(accessToken: string): Promise<readonly ProjectResponse[]> {
    void accessToken;

    return [PROJECT];
  }

  public async getProject(accessToken: string, projectId: string): Promise<ProjectResponse> {
    void accessToken;
    void projectId;

    return PROJECT;
  }

  public async renameProject(
    accessToken: string,
    projectId: string,
    displayName: string,
  ): Promise<ProjectResponse> {
    void accessToken;
    void projectId;

    return {
      ...PROJECT,
      display_name: displayName,
    };
  }

  public async archiveProject(accessToken: string, projectId: string): Promise<void> {
    void accessToken;
    void projectId;

    return undefined;
  }

  public async createBriefVersion(
    accessToken: string,
    projectId: string,
    input: ProjectBriefInput,
  ): Promise<ProjectBriefVersionResponse> {
    void accessToken;

    return {
      id: "00000000-0000-4000-8000-000000000020",
      project_id: projectId,
      version_number: 1,
      schema_version: 1,
      content_hash: "a".repeat(64),
      created_by_user_id: USER.id,
      created_at: "2026-08-10T12:05:00Z",
      brief: {
        ...input,
        provided_fields: ["name"],
        missing_fields: ["problem"],
      },
    };
  }

  public async currentBriefVersion(
    accessToken: string,
    projectId: string,
  ): Promise<ProjectBriefVersionResponse> {
    return this.createBriefVersion(accessToken, projectId, {
      name: "Project",
      description: null,
      problem: null,
      goals: null,
      target_users: null,
      domain: null,
      technical_constraints: null,
      temporal_constraints: null,
      budget: null,
      functional_requirements: null,
      non_functional_requirements: null,
      risks: null,
      stakeholders: null,
      available_artifacts: null,
      definition_of_done: null,
      unknown_fields: [],
    });
  }

  public async listBriefVersions(
    accessToken: string,
    projectId: string,
  ): Promise<readonly ProjectBriefVersionResponse[]> {
    void accessToken;
    void projectId;

    return [];
  }

  public async getBriefVersion(
    accessToken: string,
    projectId: string,
    versionNumber: number,
  ): Promise<ProjectBriefVersionResponse> {
    void versionNumber;

    return this.currentBriefVersion(accessToken, projectId);
  }
}

describe("useProjectsStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads projects through the authenticated token boundary", async () => {
    const auth = useAuthStore();
    const projects = useProjectsStore();
    const api = new FakeApplicationApi();

    auth.$patch({
      status: "authenticated",
      user: USER,
      accessToken: "access-token",
      expiresAt: "2026-08-10T12:15:00Z",
    });

    const succeeded = await projects.loadProjects(api, auth);

    expect(succeeded).toBe(true);
    expect(projects.projects).toEqual([PROJECT]);
  });

  it("creates a project and prepends it to the list", async () => {
    const auth = useAuthStore();
    const projects = useProjectsStore();
    const api = new FakeApplicationApi();

    auth.$patch({
      status: "authenticated",
      user: USER,
      accessToken: "access-token",
      expiresAt: "2026-08-10T12:15:00Z",
    });

    const created = await projects.createProject(api, auth, {
      display_name: "New project",
      mode: "BROWNFIELD_ASSESSMENT",
    });

    expect(created?.display_name).toBe("New project");
    expect(projects.projects[0]?.mode).toBe("BROWNFIELD_ASSESSMENT");
  });
});
