import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "./App"
import { describeSchedule, parseScheduleCron } from "./schedule"

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
    expect(screen.getByText("每小时整点")).toBeInTheDocument()
    expect(screen.queryByText("0 * * * *")).not.toBeInTheDocument()
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

  it("reuses the add form when editing a podcast", async () => {
    const updated = { ...podcast, url: "https://www.youtube.com/playlist?list=UPDATED" }
    const fetch = vi.fn()
      .mockImplementationOnce(() => jsonResponse({ podcasts: [podcast], uses_default_password: false }))
      .mockImplementationOnce(() => jsonResponse({ podcast: updated }))
      .mockImplementationOnce(() => jsonResponse({ podcasts: [updated], uses_default_password: false }))
    vi.stubGlobal("fetch", fetch)

    render(<App />)
    fireEvent.click(await screen.findByRole("button", { name: "编辑 weekly" }))
    const dialog = screen.getByRole("dialog", { name: "编辑 weekly" })
    expect(within(dialog).getByLabelText("名称")).toHaveValue("weekly")
    expect(within(dialog).getByLabelText("名称")).toHaveAttribute("readonly")
    expect(within(dialog).getByRole("button", { name: "更新频率：每小时整点" })).toBeInTheDocument()
    expect(within(dialog).queryByLabelText("更新计划（Cron）")).not.toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText("播放列表地址"), { target: { value: updated.url } })
    fireEvent.submit(within(dialog).getByRole("button", { name: "保存" }).closest("form")!)

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "编辑 weekly" })).not.toBeInTheDocument())
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/admin/podcasts/weekly", expect.objectContaining({
      method: "PUT",
      body: expect.stringContaining(updated.url),
    }))
  })

  it("opens the add form in a dialog and closes it after adding", async () => {
    const fetch = vi.fn()
      .mockImplementationOnce(() => jsonResponse({ podcasts: [], uses_default_password: false }))
      .mockImplementationOnce(() => jsonResponse({ podcast }))
      .mockImplementationOnce(() => jsonResponse({ podcasts: [podcast], uses_default_password: false }))
    vi.stubGlobal("fetch", fetch)

    render(<App />)
    expect(await screen.findByText(/还没有播客/)).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "添加播客" }))
    const dialog = screen.getByRole("dialog", { name: "添加播客" })
    fireEvent.change(within(dialog).getByLabelText("名称"), { target: { value: "weekly" } })
    fireEvent.change(within(dialog).getByLabelText("播放列表地址"), { target: { value: podcast.url } })
    fireEvent.submit(within(dialog).getByRole("button", { name: "添加播客" }).closest("form")!)

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getByText("weekly")).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith("/api/admin/podcasts", expect.objectContaining({ method: "POST" }))
  })

  it("keeps the add dialog open when saving fails", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockImplementationOnce(() => jsonResponse({ podcasts: [], uses_default_password: false }))
      .mockImplementationOnce(() => Promise.resolve({ ok: false, status: 409, json: () => Promise.resolve({ detail: "播客已存在" }) })))
    render(<App />)
    expect(await screen.findByText(/还没有播客/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "添加播客" }))
    const dialog = screen.getByRole("dialog", { name: "添加播客" })
    fireEvent.submit(within(dialog).getByRole("button", { name: "添加播客" }).closest("form")!)

    expect(await screen.findByText("播客已存在")).toBeInTheDocument()
    expect(dialog).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  it("describes common saved cron schedules without exposing raw expressions", () => {
    expect(describeSchedule("*/2 * * * *")).toBe("每 2 分钟")
    expect(describeSchedule("*/1 * * * *")).toBe("每分钟")
    expect(describeSchedule("0 */2 * * *")).toBe("每 2 小时整点")
    expect(describeSchedule("30 * * * *")).toBe("每小时第 30 分钟")
    expect(describeSchedule("0 9 * * *")).toBe("每天 09:00")
    expect(describeSchedule("30 8 * * 0")).toBe("每周一 08:30")
    expect(describeSchedule("0 10 15 * *")).toBe("每月 15 日 10:00")
    expect(describeSchedule("0 9 * * 1-5")).toBe("自定义计划（请查看配置）")
    expect(describeSchedule("bad input")).toBe("自定义计划（请查看配置）")
  })

  it("loads supported cron schedules into the shared form", () => {
    expect(parseScheduleCron("30 8 * * 5")).toEqual({ frequency: "weekly", time: "08:30", weekday: "5", monthDay: "1" })
    expect(parseScheduleCron("0 9 * * 1-5")).toBeNull()
  })

  it("converts selected weekly time to cron when adding", async () => {
    const fetch = vi.fn()
      .mockImplementationOnce(() => jsonResponse({ podcasts: [], uses_default_password: false }))
      .mockImplementationOnce(() => jsonResponse({ podcast }))
      .mockImplementationOnce(() => jsonResponse({ podcasts: [podcast], uses_default_password: false }))
    vi.stubGlobal("fetch", fetch)
    render(<App />)
    expect(await screen.findByText(/还没有播客/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "添加播客" }))
    const dialog = screen.getByRole("dialog", { name: "添加播客" })
    expect(within(dialog).queryByLabelText(/Cron/)).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: /更新频率：每小时整点/ }))
    const picker = screen.getByRole("dialog", { name: "选择更新计划" })
    fireEvent.click(within(picker).getByRole("button", { name: "每周" }))
    expect(within(picker).queryByRole("textbox", { name: "执行时间" })).not.toBeInTheDocument()
    expect(within(picker).queryByDisplayValue("08:30")).not.toBeInTheDocument()
    fireEvent.click(within(picker).getByRole("combobox", { name: "星期" }))
    fireEvent.click(screen.getByRole("option", { name: "周六" }))
    fireEvent.click(within(picker).getByRole("combobox", { name: "小时" }))
    fireEvent.click(screen.getByRole("option", { name: "08" }))
    fireEvent.click(within(picker).getByRole("combobox", { name: "分钟" }))
    fireEvent.click(screen.getByRole("option", { name: "30" }))
    fireEvent.click(within(picker).getByRole("button", { name: "完成" }))
    expect(within(dialog).getByRole("button", { name: /更新频率：每周六 08:30/ })).toBeInTheDocument()
    expect(within(dialog).queryByLabelText("星期")).not.toBeInTheDocument()
    expect(within(dialog).queryByLabelText("执行时间")).not.toBeInTheDocument()
    fireEvent.submit(within(dialog).getByRole("button", { name: "添加播客" }).closest("form")!)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3))
    expect(JSON.parse(fetch.mock.calls[1][1].body).update_period_cron).toBe("30 8 * * 5")
  })

  it("resets the add schedule after closing and reopening", async () => {
    vi.stubGlobal("fetch", vi.fn(() => jsonResponse({ podcasts: [], uses_default_password: false })))
    render(<App />)
    expect(await screen.findByText(/还没有播客/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "添加播客" }))
    const dialog = screen.getByRole("dialog", { name: "添加播客" })
    fireEvent.click(within(dialog).getByRole("button", { name: /更新频率：每小时整点/ }))
    const picker = screen.getByRole("dialog", { name: "选择更新计划" })
    fireEvent.click(within(picker).getByRole("button", { name: "每月" }))
    fireEvent.click(within(picker).getByRole("combobox", { name: "每月几号" }))
    fireEvent.click(screen.getByRole("option", { name: "15 日" }))
    fireEvent.click(within(picker).getByRole("combobox", { name: "小时" }))
    fireEvent.click(screen.getByRole("option", { name: "11" }))
    fireEvent.click(within(picker).getByRole("combobox", { name: "分钟" }))
    fireEvent.click(screen.getByRole("option", { name: "45" }))
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    fireEvent.click(screen.getByRole("button", { name: "添加播客" }))
    const reopened = screen.getByRole("dialog", { name: "添加播客" })
    expect(within(reopened).getByRole("button", { name: /更新频率：每小时整点/ })).toBeInTheDocument()
    fireEvent.click(within(reopened).getByRole("button", { name: /更新频率：每小时整点/ }))
    const reopenedPicker = screen.getByRole("dialog", { name: "选择更新计划" })
    fireEvent.click(within(reopenedPicker).getByRole("button", { name: "每月" }))
    expect(within(reopenedPicker).getByRole("combobox", { name: "每月几号" })).toHaveTextContent("1 日")
    expect(within(reopenedPicker).getByRole("combobox", { name: "小时" })).toHaveTextContent("09")
    expect(within(reopenedPicker).getByRole("combobox", { name: "分钟" })).toHaveTextContent("00")
  })

  it("selects a recurring day from the schedule picker without native time inputs", async () => {
    const fetch = vi.fn()
      .mockImplementationOnce(() => jsonResponse({ podcasts: [], uses_default_password: false }))
      .mockImplementationOnce(() => jsonResponse({ podcast }))
      .mockImplementationOnce(() => jsonResponse({ podcasts: [podcast], uses_default_password: false }))
    vi.stubGlobal("fetch", fetch)
    render(<App />)
    expect(await screen.findByText(/还没有播客/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "添加播客" }))
    const dialog = screen.getByRole("dialog", { name: "添加播客" })
    fireEvent.click(within(dialog).getByRole("button", { name: /更新频率：每小时整点/ }))
    const picker = screen.getByRole("dialog", { name: "选择更新计划" })
    fireEvent.click(within(picker).getByRole("button", { name: "每月" }))
    expect(within(picker).queryByDisplayValue("09:00")).not.toBeInTheDocument()
    expect(within(picker).queryByRole("spinbutton")).not.toBeInTheDocument()
    fireEvent.click(within(picker).getByRole("combobox", { name: "每月几号" }))
    fireEvent.click(screen.getByRole("option", { name: "31 日" }))
    fireEvent.click(within(picker).getByRole("button", { name: "完成" }))
    expect(within(dialog).getByRole("button", { name: /每月 31 日 09:00/ })).toBeInTheDocument()
    fireEvent.submit(within(dialog).getByRole("button", { name: "添加播客" }).closest("form")!)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3))
    expect(JSON.parse(fetch.mock.calls[1][1].body).update_period_cron).toBe("0 9 31 * *")
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
