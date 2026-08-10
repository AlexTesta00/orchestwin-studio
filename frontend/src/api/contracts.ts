export interface UserResponse {
  readonly id: string;
  readonly email: string;
  readonly is_active: boolean;
  readonly created_at: string;
}

export interface AuthenticationResponse {
  readonly access_token: string;
  readonly token_type: "bearer";
  readonly expires_at: string;
  readonly user: UserResponse;
}

export interface AuthenticationInput {
  readonly email: string;
  readonly password: string;
}

export interface AuthenticationApi {
  register(input: AuthenticationInput): Promise<AuthenticationResponse>;
  login(input: AuthenticationInput): Promise<AuthenticationResponse>;
  refresh(): Promise<AuthenticationResponse>;
  logout(): Promise<void>;
  me(accessToken: string): Promise<UserResponse>;
}

export type ProjectMode = "GREENFIELD_GENERATION" | "BROWNFIELD_ASSESSMENT";

export type BriefField =
  | "name"
  | "description"
  | "problem"
  | "goals"
  | "target_users"
  | "domain"
  | "technical_constraints"
  | "temporal_constraints"
  | "budget"
  | "functional_requirements"
  | "non_functional_requirements"
  | "risks"
  | "stakeholders"
  | "available_artifacts"
  | "definition_of_done";

export interface ProjectResponse {
  readonly id: string;
  readonly display_name: string;
  readonly mode: ProjectMode;
  readonly current_brief_version: number;
  readonly is_archived: boolean;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ProjectCreateInput {
  readonly display_name: string;
  readonly mode: ProjectMode;
}

export interface ProjectBriefInput {
  readonly name: string | null;
  readonly description: string | null;
  readonly problem: string | null;
  readonly goals: readonly string[] | null;
  readonly target_users: readonly string[] | null;
  readonly domain: string | null;
  readonly technical_constraints: readonly string[] | null;
  readonly temporal_constraints: string | null;
  readonly budget: string | null;
  readonly functional_requirements: readonly string[] | null;
  readonly non_functional_requirements: readonly string[] | null;
  readonly risks: readonly string[] | null;
  readonly stakeholders: readonly string[] | null;
  readonly available_artifacts: readonly string[] | null;
  readonly definition_of_done: readonly string[] | null;
  readonly unknown_fields: readonly BriefField[];
}

export interface ProjectBriefResponse extends ProjectBriefInput {
  readonly provided_fields: readonly BriefField[];
  readonly missing_fields: readonly BriefField[];
}

export interface ProjectBriefVersionResponse {
  readonly id: string;
  readonly project_id: string;
  readonly version_number: number;
  readonly schema_version: number;
  readonly content_hash: string;
  readonly created_by_user_id: string;
  readonly created_at: string;
  readonly brief: ProjectBriefResponse;
}

export interface ProjectApi {
  createProject(accessToken: string, input: ProjectCreateInput): Promise<ProjectResponse>;

  listProjects(accessToken: string): Promise<readonly ProjectResponse[]>;

  getProject(accessToken: string, projectId: string): Promise<ProjectResponse>;

  renameProject(
    accessToken: string,
    projectId: string,
    displayName: string,
  ): Promise<ProjectResponse>;

  archiveProject(accessToken: string, projectId: string): Promise<void>;

  createBriefVersion(
    accessToken: string,
    projectId: string,
    input: ProjectBriefInput,
  ): Promise<ProjectBriefVersionResponse>;

  currentBriefVersion(accessToken: string, projectId: string): Promise<ProjectBriefVersionResponse>;

  listBriefVersions(
    accessToken: string,
    projectId: string,
  ): Promise<readonly ProjectBriefVersionResponse[]>;

  getBriefVersion(
    accessToken: string,
    projectId: string,
    versionNumber: number,
  ): Promise<ProjectBriefVersionResponse>;
}
