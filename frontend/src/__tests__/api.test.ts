/// <reference types="jest" />
/** Audit 2026-10-10 Wave 4 — API client behaviour (timeouts, 401 handling, error hygiene, guest ids). */
const mockMem = new Map<string, unknown>();
jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: async (k: string, fb: unknown) => (mockMem.has(k) ? mockMem.get(k) : fb),
    setItem: async (k: string, v: unknown) => (mockMem.set(k, v), true),
    secureGet: async (k: string, fb: unknown) => (mockMem.has(k) ? mockMem.get(k) : fb),
    secureSet: async (k: string, v: unknown) => (mockMem.set(k, v), true),
    secureRemove: async (k: string) => (mockMem.delete(k), true),
  },
}));
let mockUuidCounter = 0;
jest.mock("expo-crypto", () => ({ randomUUID: () => `0000000${++mockUuidCounter}-aaaa-4bbb-8ccc-dddddddddddd` }));

// Expo inlines EXPO_PUBLIC_* at transform time; the test run sets it in package.json "jest.setupFiles"-free form below.
function load() {
  jest.resetModules();
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- fresh module state per test
  return require("@/src/api") as typeof import("@/src/api");
}

function respond(status: number, body: string) {
  return { ok: status >= 200 && status < 300, status, text: async () => body, json: async () => JSON.parse(body) } as unknown as Response;
}

beforeEach(() => {
  mockMem.clear();
  (globalThis as any).fetch = jest.fn();
});

test("a build without a usable backend URL reports a configuration error", () => {
  const api = load();
  for (const bad of [undefined, "", "undefined", "api.example.com", "https://"]) expect(api.backendConfigError(bad)).toMatch(/EXPO_PUBLIC_BACKEND_URL/);
  expect(api.backendConfigError("https://api.example.com")).toBeNull();
  expect(api.backendConfigError("http://10.0.2.2:8001")).toBeNull();
});

test("401 with a token signs the user out; 401 without a token does not", async () => {
  const api = load();
  const onUnauthorized = jest.fn();
  api.setUnauthorizedHandler(onUnauthorized);
  (globalThis.fetch as jest.Mock).mockResolvedValue(respond(401, '{"detail":"Invalid or expired token"}'));
  await expect(api.api("/auth/me")).rejects.toMatchObject({ status: 401 });
  expect(onUnauthorized).not.toHaveBeenCalled();
  await api.setToken("tok");
  await expect(api.api("/auth/me")).rejects.toMatchObject({ status: 401, message: "Invalid or expired token" });
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
});

test("validation error lists are not dumped raw into the UI", async () => {
  const api = load();
  (globalThis.fetch as jest.Mock).mockResolvedValue(respond(422, '{"detail":[{"loc":["body","email"],"msg":"bad"}]}'));
  await expect(api.api("/x")).rejects.toMatchObject({ status: 422, message: "Please check your details and try again." });
});

test("empty 2xx bodies resolve to null instead of throwing", async () => {
  const api = load();
  (globalThis.fetch as jest.Mock).mockResolvedValue(respond(200, ""));
  await expect(api.api("/x")).resolves.toBeNull();
});

test("a hung request times out with a friendly error", async () => {
  jest.useFakeTimers();
  const api = load();
  (globalThis.fetch as jest.Mock).mockImplementation((_url: string, init: RequestInit) =>
    new Promise((_resolve, reject) => init.signal!.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })))),
  );
  const p = api.api("/slow", { timeoutMs: 1000 });
  const assertion = expect(p).rejects.toMatchObject({ status: 0, message: expect.stringMatching(/timed out/) });
  await jest.advanceTimersByTimeAsync(1001);
  await assertion;
  jest.useRealTimers();
});

test("guest ids come from the CSPRNG and rotate on demand", async () => {
  const api = load();
  const first = await api.getGuestId();
  expect(first).toMatch(/^g_[0-9a-f]{32}$/);
  expect(await api.getGuestId()).toBe(first);
  await api.rotateGuestId();
  const second = await api.getGuestId();
  expect(second).toMatch(/^g_[0-9a-f]{32}$/);
  expect(second).not.toBe(first);
});

test("every request carries the guest id and, when signed in, the bearer token", async () => {
  const api = load();
  await api.setToken("tok");
  (globalThis.fetch as jest.Mock).mockResolvedValue(respond(200, "{}"));
  await api.api("/sparks/mine");
  const [url, init] = (globalThis.fetch as jest.Mock).mock.calls[0];
  expect(url).toBe(`${process.env.EXPO_PUBLIC_BACKEND_URL}/api/sparks/mine`);
  expect(init.headers.Authorization).toBe("Bearer tok");
  expect(init.headers["X-Guest-ID"]).toMatch(/^g_/);
});

test("a wrong password while signed in does not sign the user out", async () => {
  const api = load();
  const onUnauthorized = jest.fn();
  api.setUnauthorizedHandler(onUnauthorized);
  await api.setToken("tok");
  (globalThis.fetch as jest.Mock).mockResolvedValue(respond(401, '{"detail":"Incorrect email or password"}'));
  for (const path of ["/auth/login", "/auth/apple", "/auth/google", "/auth/password/reset"]) {
    await expect(api.api(path, { method: "POST" })).rejects.toMatchObject({ status: 401 });
  }
  expect(onUnauthorized).not.toHaveBeenCalled();
});
