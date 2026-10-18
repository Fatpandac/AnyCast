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

async function request<T>(url: string, options?: RequestInit): Promise<T> {
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

export function deletePodcast(name: string) {
  return request<{ status: string }>(
    `/api/admin/podcasts/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  )
}
