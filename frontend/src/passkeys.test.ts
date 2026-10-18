import { afterEach, expect, it, vi } from "vitest"
import { registerPasskey, loginPasskey } from "./passkeys"

afterEach(() => vi.unstubAllGlobals())

it("converts binary WebAuthn options and responses for registration and login", async () => {
  const create = vi.fn((_options: CredentialCreationOptions) => Promise.resolve({
    id: "key", rawId: new Uint8Array([1]).buffer, type: "public-key",
    response: { clientDataJSON: new Uint8Array([2]).buffer, attestationObject: new Uint8Array([3]).buffer, getTransports: () => ["internal"] },
  }))
  const get = vi.fn((_options: CredentialRequestOptions) => Promise.resolve({
    id: "key", rawId: new Uint8Array([1]).buffer, type: "public-key",
    response: { clientDataJSON: new Uint8Array([2]).buffer, authenticatorData: new Uint8Array([3]).buffer, signature: new Uint8Array([4]).buffer, userHandle: null },
  }))
  vi.stubGlobal("navigator", { credentials: { create, get } })
  const fetch = vi.fn((url: string, options?: RequestInit) => Promise.resolve({ ok: true, json: () => Promise.resolve(
    url.endsWith("/options") ? url.includes("register")
      ? { rp: { id: "example.com", name: "AnyCast" }, user: { id: "AQ", name: "admin", displayName: "admin" }, challenge: "Ag", pubKeyCredParams: [] }
      : { rpId: "example.com", challenge: "Ag" }
      : url.includes("register") ? { passkey_count: 1, passkey_origin: "https://example.com" } : { status: "ok" },
  ) } as Response))
  vi.stubGlobal("fetch", fetch)
  await registerPasskey()
  await loginPasskey()
  expect(new Uint8Array(create.mock.calls[0][0].publicKey!.challenge as ArrayBuffer)).toEqual(new Uint8Array([2]))
  expect(new Uint8Array(get.mock.calls[0][0].publicKey!.challenge as ArrayBuffer)).toEqual(new Uint8Array([2]))
  expect(fetch).toHaveBeenCalledWith("/api/admin/passkeys/register/verify", expect.objectContaining({ body: expect.stringContaining('"attestationObject":"Aw"') }))
  expect(fetch).toHaveBeenCalledWith("/api/admin/passkeys/login/verify", expect.objectContaining({ body: expect.stringContaining('"signature":"BA"') }))
})
