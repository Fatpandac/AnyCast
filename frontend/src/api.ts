export type Podcast = {
  name: string
  url: string
  update_period_cron: string
  keep_latest: number | null
  sort_by: "date" | "title"
  sort_order: "asc" | "desc"
  page_size: number
  yt_dlp_options: Record<string, unknown>
  episode_count?: number
}

export type Episode = {
  episode_id: string
  title: string | null
  description: string | null
  source_url: string
  file_name: string
  published_at: string | null
  created_at: string | null
  cover_image_url: string | null
}

export type PodcastInput = Omit<Podcast, "episode_count" | "yt_dlp_options">

export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: options?.body
      ? { "Content-Type": "application/json", ...options.headers }
      : options?.headers,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item?.msg).filter(Boolean).join("；")
          : `请求失败（${response.status}）`
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export type Settings = {
  server: { host: string; port: number }
  youtube: { cookies_file: string; cookies_from_browser: string }
  admin?: { passkey_origin: string; passkey_count: number }
}

export function getSettings() {
  return request<Settings>("/api/admin/settings")
}

export function saveSettings(settings: Settings) {
  return request<Settings>("/api/admin/settings", { method: "PUT", body: JSON.stringify(settings) })
}

export function changeAdminPassword(current_password: string, new_password: string) {
  return request<{ status: string }>("/api/admin/settings/password", {
    method: "PUT", body: JSON.stringify({ current_password, new_password }),
  })
}

export function savePasskeyOrigin(origin: string) {
  return request<{ passkey_origin: string; passkey_count: number }>("/api/admin/settings/passkey-origin", {
    method: "PUT", body: JSON.stringify({ origin }),
  })
}

export function getCookieFile() {
  return request<{ path: string; content: string; revision: string }>("/api/admin/settings/cookies")
}

export function saveCookieFile(path: string, content: string, revision: string) {
  return request<{ revision: string }>("/api/admin/settings/cookies", {
    method: "PUT", body: JSON.stringify({ path, content, revision }),
  })
}

export function listPodcasts() {
  return request<{ podcasts: Podcast[]; uses_default_password: boolean }>(
    "/api/admin/podcasts",
  )
}

export function getPodcast(name: string) {
  return request<{ podcast: Podcast; episodes: Episode[] }>(
    `/api/admin/podcasts/${encodeURIComponent(name)}`,
  )
}

export function createPodcast(podcast: PodcastInput) {
  return request<{ podcast: Podcast }>("/api/admin/podcasts", {
    method: "POST",
    body: JSON.stringify(podcast),
  })
}

export function updatePodcast(name: string, podcast: PodcastInput) {
  return request<{ podcast: Podcast }>(
    `/api/admin/podcasts/${encodeURIComponent(name)}`,
    { method: "PUT", body: JSON.stringify(podcast) },
  )
}

export function deletePodcast(name: string) {
  return request<{ status: string }>(
    `/api/admin/podcasts/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  )
}
