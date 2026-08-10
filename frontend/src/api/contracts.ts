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