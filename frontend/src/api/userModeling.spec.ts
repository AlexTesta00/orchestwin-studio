import { afterEach, describe, expect, it, vi } from "vitest";
import { UserModelingApiError, userModelingApi } from "./userModeling";

const data = {
  name: "Receptionist",
  description: "Works at reception",
  role: "Receptionist",
  goals: ["Fast check-in"],
  context: null,
};
describe("archetype API", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("sends create, edit and archive with the exact version and encoded identity", async () => {
    const fetch = vi.fn().mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            ...data,
            persona_id: "persona/1",
            version_id: "version",
            version_number: 3,
            source: "OWNER_PROVIDED",
            confirmation_status: "CONFIRMED",
            archived: false,
          }),
        ),
    );
    vi.stubGlobal("fetch", fetch);
    await userModelingApi.createArchetype("project/1", data, "token");
    await userModelingApi.editArchetype(
      "project/1",
      "persona/1",
      { ...data, based_on_version_number: 2 },
      "token",
    );
    await userModelingApi.archiveArchetype(
      "project/1",
      "persona/1",
      { based_on_version_number: 3 },
      "token",
    );
    const root = "/api/v1/projects/project%2F1/user-modeling/archetypes";
    expect(
      fetch.mock.calls.map(([path, init]) => [path, init.method, JSON.parse(init.body)]),
    ).toEqual([
      [root, "POST", data],
      [root + "/persona%2F1", "PATCH", { ...data, based_on_version_number: 2 }],
      [root + "/persona%2F1", "DELETE", { based_on_version_number: 3 }],
    ]);
    expect(fetch.mock.calls[0]?.[1].headers.Authorization).toBe("Bearer token");
    expect(fetch.mock.calls[0]?.[1].headers.Prefer).toBeUndefined();
  });
  it("lists active archetypes and preserves the conflict code", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("[]"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: { code: "ARCHETYPE_VERSION_CONFLICT" } }), {
          status: 409,
        }),
      );
    vi.stubGlobal("fetch", fetch);
    expect(await userModelingApi.getArchetypes("project", "token")).toEqual([]);
    await expect(
      userModelingApi.editArchetype(
        "project",
        "persona",
        { ...data, based_on_version_number: 1 },
        "token",
      ),
    ).rejects.toMatchObject({ status: 409, code: "ARCHETYPE_VERSION_CONFLICT" });
    expect(fetch.mock.calls[0]?.[1].method).toBe("GET");
    expect(fetch.mock.calls[0]?.[1].body).toBeUndefined();
  });
  it("requires authentication before any manual write", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(userModelingApi.createArchetype("project", data, "")).rejects.toBeInstanceOf(
      UserModelingApiError,
    );
    expect(fetch).not.toHaveBeenCalled();
  });
});
