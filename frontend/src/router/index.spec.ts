import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import { createAppRouter } from "./index";

const PROJECT_ID = "3f2c8f4e-5b1a-4c2d-9e8f-0a1b2c3d4e5f";

describe("application router", () => {
  it("opens a project only from a UUID identifier", () => {
    const router = createAppRouter(createMemoryHistory());

    const project = router.resolve(`/projects/${PROJECT_ID}`);

    expect(project.name).toBe("project-detail");
    expect(project.params.projectId).toBe(PROJECT_ID);
    expect(router.resolve(`/projects/${PROJECT_ID.toUpperCase()}`).name).toBe("project-detail");
    expect(router.resolve("/projects/..%2Fauth%2Flogout").name).not.toBe("project-detail");
    expect(router.resolve("/projects/not-a-project").name).not.toBe("project-detail");
    expect(router.resolve(`/projects/${PROJECT_ID}/extra`).name).not.toBe("project-detail");
  });

  it.each(["/projects/..%2Fauth%2Flogout", "/an/unknown/address"])(
    "sends %s to the overview",
    async (address) => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
      const router = createAppRouter(createMemoryHistory());

      await router.push(address);
      await router.isReady();

      expect(router.currentRoute.value.name).toBe("overview");
      expect(router.currentRoute.value.path).toBe("/");
      expect(warn).not.toHaveBeenCalled();
    },
  );
});
