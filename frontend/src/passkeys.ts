import { request } from "@/api"

function decode(value: string): ArrayBuffer {
  const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/"))
  return Uint8Array.from(raw, (char) => char.charCodeAt(0)).buffer
}

function encode(value: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

type Options = Omit<PublicKeyCredentialCreationOptions, "challenge" | "user" | "excludeCredentials"> & { challenge: string; user: Omit<PublicKeyCredentialUserEntity, "id"> & { id: string }; excludeCredentials?: Array<Omit<PublicKeyCredentialDescriptor, "id"> & { id: string }> }
type LoginOptions = Omit<PublicKeyCredentialRequestOptions, "challenge" | "allowCredentials"> & { challenge: string; allowCredentials?: Array<Omit<PublicKeyCredentialDescriptor, "id"> & { id: string }> }

export async function registerPasskey() {
  const options = await request<Options>("/api/admin/passkeys/register/options", { method: "POST" })
  const credential = await navigator.credentials.create({ publicKey: {
    ...options, challenge: decode(options.challenge), user: { ...options.user, id: decode(options.user.id) },
    excludeCredentials: options.excludeCredentials?.map((key) => ({ ...key, id: decode(key.id) })),
  } }) as PublicKeyCredential | null
  if (!credential) throw new Error("Passkey 注册已取消")
  const response = credential.response as AuthenticatorAttestationResponse
  return request<{ passkey_origin: string; passkey_count: number }>("/api/admin/passkeys/register/verify", {
    method: "POST", body: JSON.stringify({ challenge: options.challenge, credential: {
      id: credential.id, rawId: encode(credential.rawId), type: credential.type,
      response: { clientDataJSON: encode(response.clientDataJSON), attestationObject: encode(response.attestationObject), transports: response.getTransports?.() || [] },
    } }),
  })
}

export async function loginPasskey() {
  const options = await request<LoginOptions>("/api/admin/passkeys/login/options", { method: "POST" })
  const credential = await navigator.credentials.get({ publicKey: {
    ...options, challenge: decode(options.challenge),
    allowCredentials: options.allowCredentials?.map((key) => ({ ...key, id: decode(key.id) })),
  } }) as PublicKeyCredential | null
  if (!credential) throw new Error("Passkey 登录已取消")
  const response = credential.response as AuthenticatorAssertionResponse
  return request<{ status: string }>("/api/admin/passkeys/login/verify", {
    method: "POST", body: JSON.stringify({ challenge: options.challenge, credential: {
      id: credential.id, rawId: encode(credential.rawId), type: credential.type,
      response: { clientDataJSON: encode(response.clientDataJSON), authenticatorData: encode(response.authenticatorData), signature: encode(response.signature), userHandle: response.userHandle ? encode(response.userHandle) : null },
    } }),
  })
}
