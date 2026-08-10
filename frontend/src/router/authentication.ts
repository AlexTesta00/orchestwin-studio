import type { Pinia } from "pinia";
import type { Router } from "vue-router";

import type { AuthenticationApi } from "@/api/contracts";
import { useAuthStore } from "@/stores/auth";

export function installAuthenticationGuard(
  router: Router,
  pinia: Pinia,
  api: AuthenticationApi,
): void {
  const auth = useAuthStore(pinia);

  router.beforeEach(async (target) => {
    if (auth.status === "idle") {
      await auth.bootstrap(api);
    }

    if (
      target.meta.requiresAuthentication === true &&
      !auth.isAuthenticated
    ) {
      return {
        name: "login",
        query: {
          redirect: target.fullPath,
        },
      };
    }

    if (
      target.meta.guestOnly === true &&
      auth.isAuthenticated
    ) {
      return {
        name: "projects",
      };
    }

    return true;
  });
}