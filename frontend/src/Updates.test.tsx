import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { ApplicationUpdates } from "./Updates"
import { checkApplicationUpdate, getUpdateStatus, installApplicationUpdate, type UpdateStatus } from "./api"

vi.mock("./api", () => ({ getUpdateStatus: vi.fn(), checkApplicationUpdate: vi.fn(), installApplicationUpdate: vi.fn() }))

const current = "a".repeat(40)
const target = "b".repeat(40)
const idle: UpdateStatus = {
  current_sha: current, latest_sha: current, latest_message: "", latest_date: "2026-11-15T00:00:00Z",
  checked_at: "2026-11-15T00:00:00Z", relation: "current", update_available: false,
  can_update: false, reason: "", error: "", phase: "idle",
}
const available: UpdateStatus = { ...idle, latest_sha: target, latest_message: "Fix downloads", relation: "behind", update_available: true, can_update: true }
let poll: () => void

beforeEach(() => {
  vi.mocked(getUpdateStatus).mockResolvedValue(idle)
  const nativeInterval = window.setInterval.bind(window)
  vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
    if (delay !== 2000) return nativeInterval(callback, delay) as unknown as ReturnType<typeof setInterval>
    poll = callback as () => void
    return 1 as unknown as ReturnType<typeof setInterval>
  })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks() })

it("checks main and displays a pinned commit with the update button", async () => {
  vi.mocked(checkApplicationUpdate).mockResolvedValue(available)
  render(<ApplicationUpdates />)
  expect(await screen.findByText("已是最新提交")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "检查更新" }))
  expect(await screen.findByText("Fix downloads")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "更新并重启" })).toBeEnabled()
  expect(screen.getByRole("link", { name: target.slice(0, 7) })).toHaveAttribute("href", `https://github.com/Fatpandac/AnyCast/commit/${target}`)
})

it("preserves all commit messages and line breaks in a keyboard-scrollable update history", async () => {
  const notes = "bbbbbbb · 2026-11-15T12:00:00Z\nLatest change\n\nFull latest body\n<button>plain commit text</button>\n\nccccccc · 2026-11-14T12:00:00Z\nEarlier change\n\n完整的早期提交说明"
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, latest_message: notes })
  render(<ApplicationUpdates />)
  const history = await screen.findByRole("region", { name: "待更新提交说明" })
  expect(history.textContent).toBe(notes)
  expect(history).toHaveClass("whitespace-pre-wrap", "overflow-y-auto", "max-h-80")
  expect(history).toHaveAttribute("tabindex", "0")
  expect(history.querySelector("button")).toBeNull()
  expect(screen.queryByText("最新提交说明")).not.toBeInTheDocument()
})

it("requires confirmation and reconnects until the target SHA is running", async () => {
  vi.mocked(getUpdateStatus).mockResolvedValue(available)
  vi.mocked(installApplicationUpdate).mockResolvedValue({ ...available, phase: "preparing", target, can_update: false })
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
  render(<ApplicationUpdates />)
  fireEvent.click(await screen.findByRole("button", { name: "更新并重启" }))
  expect(installApplicationUpdate).not.toHaveBeenCalled()
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByRole("button", { name: "更新并重启" }))
  await waitFor(() => expect(installApplicationUpdate).toHaveBeenCalledWith(target))
  expect(await screen.findByText("准备更新")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "检查更新" })).toBeDisabled()
  vi.mocked(getUpdateStatus).mockRejectedValueOnce(new Error("Failed to fetch"))
  await act(async () => { poll() })
  expect(await screen.findByText(/正在等待服务恢复/)).toBeInTheDocument()
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...idle, current_sha: target, latest_sha: target, phase: "success", target })
  await act(async () => { poll() })
  expect(await screen.findByText("更新成功，运行版本已确认")).toBeInTheDocument()
})

it("keeps tracking an install when its response is lost but unlocks explicit server rejections", async () => {
  vi.mocked(getUpdateStatus).mockResolvedValue(available)
  vi.mocked(installApplicationUpdate).mockRejectedValueOnce(new TypeError("network lost"))
  vi.spyOn(window, "confirm").mockReturnValue(true)
  render(<ApplicationUpdates />)
  fireEvent.click(await screen.findByRole("button", { name: "更新并重启" }))
  expect(await screen.findByText(/正在等待服务恢复/)).toBeInTheDocument()
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...idle, phase: "failed", message: "工作区有未提交修改" })
  await act(async () => { poll() })
  expect(screen.getByRole("alert")).toHaveTextContent("工作区有未提交修改")
  expect(screen.getByRole("button", { name: "检查更新" })).toBeEnabled()
})

it("does not announce success for a stale or wrong running SHA", async () => {
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, target, phase: "restarting" })
  render(<ApplicationUpdates />)
  expect(await screen.findByText("重启中")).toBeInTheDocument()
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, target, phase: "success" })
  await act(async () => { poll() })
  expect(await screen.findByText(/运行版本尚未匹配目标提交/)).toBeInTheDocument()
  expect(screen.queryByText("更新成功，运行版本已确认")).not.toBeInTheDocument()
})

it("shows check errors instead of claiming latest and permits a retry", async () => {
  vi.mocked(checkApplicationUpdate).mockRejectedValueOnce(new Error("GitHub 连接超时")).mockResolvedValueOnce(available)
  render(<ApplicationUpdates />)
  await screen.findByText("已是最新提交")
  fireEvent.click(screen.getByRole("button", { name: "检查更新" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("GitHub 连接超时")
  expect(screen.queryByText("已是最新提交")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "检查更新" }))
  expect(await screen.findByText("Fix downloads")).toBeInTheDocument()
})

it("explains disabled installs and shows recovery failure without losing settings", async () => {
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, can_update: false, reason: "工作区有未提交修改", phase: "failed", message: "依赖安装失败；已恢复旧版" })
  render(<ApplicationUpdates />)
  expect(await screen.findByText("工作区有未提交修改")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "更新并重启" })).toBeDisabled()
  expect(screen.getByRole("alert")).toHaveTextContent("已恢复旧版")
})

it("keeps polling healthy long-running dependency installs without calling them disconnected", async () => {
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, target, phase: "installing" })
  render(<ApplicationUpdates />)
  await screen.findByText("安装依赖中")
  for (let i = 0; i < 95; i++) await act(async () => { poll() })
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  expect(screen.getByText("安装依赖中")).toBeInTheDocument()
})

it("does not reuse an old success message when main has a newer commit", async () => {
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, target: current, phase: "success" })
  render(<ApplicationUpdates />)
  expect(await screen.findByText("Fix downloads")).toBeInTheDocument()
  expect(screen.queryByText("更新成功，运行版本已确认")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "更新并重启" })).toBeEnabled()
})

it("limits disconnected polling and allows manual recovery checks", async () => {
  vi.mocked(getUpdateStatus).mockResolvedValueOnce({ ...available, target, phase: "restarting" })
  render(<ApplicationUpdates />)
  await screen.findByText("重启中")
  vi.mocked(getUpdateStatus).mockRejectedValue(new Error("offline"))
  for (let i = 0; i < 91; i++) await act(async () => { poll() })
  expect(await screen.findByRole("alert")).toHaveTextContent(/重连超时/)
  const calls = vi.mocked(getUpdateStatus).mock.calls.length
  await act(async () => { poll() })
  expect(vi.mocked(getUpdateStatus).mock.calls.length).toBe(calls)
  expect(screen.getByRole("button", { name: "检查更新" })).toBeEnabled()
})
