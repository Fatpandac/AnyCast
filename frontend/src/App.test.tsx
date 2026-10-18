import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "./App"

const podcast = {
  name: "weekly",
  url: "https://www.youtube.com/playlist?list=PL123",
  update_period_cron: "0 * * * *",
  keep_latest: 10,
  sort_by: "date",
  sort_order: "desc",
  page_size: 20,
  yt_dlp_options: {},
  episode_count: 7,
}

function jsonResponse(body: unknown) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  } as Response)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.history.replaceState({}, "", "/admin")
})

describe("AnyCast admin", () => {
  it("renders the podcast dashboard and default-password warning", async () => {
    window.history.replaceState({}, "", "/admin")
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        jsonResponse({ podcasts: [podcast], uses_default_password: true }),
      ),
    )

    render(<App />)

    expect(await screen.findByText("weekly")).toBeInTheDocument()
    expect(screen.getByText("7 集")).toBeInTheDocument()
    expect(screen.getByText(/正在使用默认密码/)).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "播客" })).toBeInTheDocument()
  })

  it("opens podcast details when clicking anywhere on its row", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string | URL | Request) =>
      jsonResponse(String(url).includes("/weekly")
        ? { podcast, episodes: [] }
        : { podcasts: [podcast], uses_default_password: false }),
    ))

    render(<App />)
    fireEvent.click(await screen.findByText("7 集"))

    expect(await screen.findByText("暂无下载记录。")).toBeInTheDocument()
    expect(window.location.pathname).toBe("/admin/podcasts/weekly")
  })

  it("renders downloaded episode details from a nested URL", async () => {
    window.history.replaceState({}, "", "/admin/podcasts/weekly")
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        jsonResponse({
          podcast,
          episodes: [
            {
              episode_id: "ep-1",
              title: "Episode One",
              description: "完整内容简介",
              source_url: "https://www.youtube.com/watch?v=ep-1",
              file_name: "episode one.m4a",
              published_at: "2026-10-17T12:00:00+00:00",
              created_at: "2026-10-18 13:20:00",
              cover_image_url: "https://img.example/cover.jpg",
            },
          ],
        }),
      ),
    )

    render(<App />)

    expect(await screen.findByText("Episode One")).toBeInTheDocument()
    expect(screen.getByText("完整内容简介")).toBeInTheDocument()
    expect(screen.getByText("episode one.m4a")).toBeInTheDocument()
    expect(screen.getByText("共 1 集")).toBeInTheDocument()
    expect(document.querySelector('img[src="https://img.example/cover.jpg"]')).toHaveAttribute("referrerpolicy", "no-referrer")
    expect(screen.getByRole("link", { name: "查看原内容" })).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=ep-1",
    )
  })
})
