import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { YtdlpNotice } from "./YtdlpNotice"
import { getYtdlpStatus } from "./api"

vi.mock("./api", () => ({ getYtdlpStatus: vi.fn() }))
let poll: () => void

beforeEach(() => {
  vi.mocked(getYtdlpStatus).mockResolvedValue({ update_error: null })
  const nativeInterval = window.setInterval.bind(window)
  vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
    if (delay !== 30000) return nativeInterval(callback, delay) as unknown as ReturnType<typeof setInterval>
    poll = callback as () => void
    return 1 as unknown as ReturnType<typeof setInterval>
  })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks() })

it("stays hidden without an upgrade failure", async () => {
  await act(async () => { render(<YtdlpNotice />) })
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("keeps the warning compact and reveals escaped diagnostics only on request", async () => {
  const error = "ERROR: You installed yt-dlp with pip; <script>Use pip to update</script>"
  vi.mocked(getYtdlpStatus).mockResolvedValue({ update_error: error })
  render(<YtdlpNotice />)
  const notice = await screen.findByRole("alert")
  expect(notice).toHaveTextContent("yt-dlp 自动升级失败")
  expect(notice).toHaveTextContent("手动升级")
  expect(notice).not.toHaveTextContent(error)
  expect(notice).not.toHaveClass("bg-amber-50")
  fireEvent.click(within(notice).getByRole("button", { name: "查看详情" }))
  const dialog = await screen.findByRole("dialog")
  expect(dialog).toHaveTextContent(error)
  expect(dialog.querySelector("script")).toBeNull()
  vi.mocked(getYtdlpStatus).mockResolvedValue({ update_error: null })
  await act(async () => { poll() })
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
})

it("closing the diagnostic dialog keeps the unresolved warning visible", async () => {
  vi.mocked(getYtdlpStatus).mockResolvedValue({ update_error: "Use pip to update" })
  render(<YtdlpNotice />)
  fireEvent.click(await screen.findByRole("button", { name: "查看详情" }))
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "知道了" }))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent("yt-dlp 自动升级失败")
})

it("does not erase a known upgrade failure if status polling fails", async () => {
  vi.mocked(getYtdlpStatus).mockResolvedValue({ update_error: "Use pip to update" })
  render(<YtdlpNotice />)
  await screen.findByRole("alert")
  vi.mocked(getYtdlpStatus).mockRejectedValue(new Error("network unavailable"))
  await act(async () => { poll() })
  expect(screen.getByRole("alert")).toHaveTextContent("yt-dlp 自动升级失败")
  fireEvent.click(screen.getByRole("button", { name: "查看详情" }))
  expect(await screen.findByRole("dialog")).toHaveTextContent("Use pip to update")
})

it("reports unreadable status without claiming an upgrade failed", async () => {
  vi.mocked(getYtdlpStatus).mockRejectedValue(new Error("network unavailable"))
  render(<YtdlpNotice />)
  expect(await screen.findByRole("alert")).toHaveTextContent("无法读取 yt-dlp 升级状态")
  expect(screen.queryByText("yt-dlp 自动升级失败")).not.toBeInTheDocument()
})
