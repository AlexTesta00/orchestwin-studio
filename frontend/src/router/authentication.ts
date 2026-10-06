import type { Pinia } from "pinia";
import type { Router } from "vue-router";

import type { AuthenticationApi } from "@/api/contracts";
import { useAuthStore } from "@/stores/auth";
import { useGuidanceStore } from "@/stores/guidance";

export function installAuthenticationGuard(
  router: Router,
  pinia: Pinia,
  api: AuthenticationApi,
): void {
  const auth = useAuthStore(pinia);
  const guidance = useGuidanceStore(pinia);

  router.beforeEach(async (target) => {
    if (auth.status === "idle" || (auth.isLocal && !auth.isAuthenticated)) {
      await auth.bootstrap(api);
    }

    if (target.meta.requiresAuthentication === true && !auth.isAuthenticated) {
      return {
        name: "login",
        query: {
          redirect: target.fullPath,
        },
      };
    }

    if (target.meta.guestOnly === true && auth.isAuthenticated) {
      return {
        name: "projects",
      };
    }

    if (
      auth.isAuthenticated &&
      !guidance.chosen &&
      target.meta.requiresAuthentication === true &&
      target.name !== "guidance-choice"
    ) {
      return {
        name: "guidance-choice",
        query: {
          redirect: target.fullPath,
        },
      };
    }

    if (auth.isAuthenticated && guidance.chosen && target.name === "guidance-choice") {
      return {
        name: "projects",
      };
    }

    return true;
  });
}
