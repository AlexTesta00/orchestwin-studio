import { apiClient } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export function useAuthorizedRequest(
  authorize: () => AuthorizedRequest | undefined,
): AuthorizedRequest {
  const auth = useAuthStore();
  return (operation) => {
    const request = authorize();
    return request ? request(operation) : auth.withAccessToken(apiClient, operation);
  };
}
