import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { App } from "./App"

const settings = {
  server: { host: "0.0.0.0", port: 8001 },
  youtube: { cookies_file: "/path/cookies.txt", cookies_from_browser: "" },
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState({}, "", "/admin")
})

it("shows the entire running log in a large scrollable window and refreshes it", async () => {
  window.history.replaceState({}, "", "/admin/settings")
  let log = "oldest line\n" + "x".repeat(70000) + "\nlatest line"
  const fetch = vi.fn((url: string) => Promise.resolve(url.endsWith("/logs")
    ? { ok: true, text: () => Promise.resolve(log) }
    : { ok: true, json: () => Promise.resolve(settings) } as Response))
  vi.stubGlobal("fetch", fetch)
  render(<App />)
  const editor = await screen.findByRole("textbox", { name: "运行日志" })
  expect(editor).toHaveValue(log)
  expect(editor).toHaveAttribute("readonly")
  expect(editor).toHaveClass("overflow-auto")
  expect(editor).toHaveClass("h-[70vh]")
  log = "newest run\nERROR: No route to host"
  fireEvent.click(screen.getByRole("button", { name: "刷新运行日志" }))
  await waitFor(() => expect(editor).toHaveValue(log))
  expect(fetch).toHaveBeenCalledWith("/api/admin/logs", expect.objectContaining({ credentials: "same-origin" }))
})

it("configures HTTPS domain and offers passkey registration only on that domain", async () => {
  window.history.replaceState({}, "", "/admin/settings")
  const fetch = vi.fn((url: string, options?: RequestInit) => Promise.resolve({ ok: true, json: () => Promise.resolve(
    url.endsWith("/passkey-origin") ? { passkey_origin: "https://example.com", passkey_count: 0 } : { ...settings, admin: { passkey_origin: "", passkey_count: 0 } },
  ) } as Response))
  vi.stubGlobal("fetch", fetch)
  render(<App />)
  fireEvent.change(await screen.findByLabelText("Passkey 登录域名"), { target: { value: "https://example.com" } })
  fireEvent.click(screen.getByRole("button", { name: "保存登录域名" }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/admin/settings/passkey-origin", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ origin: "https://example.com" }),
  })))
  expect(screen.queryByRole("button", { name: "注册 Passkey" })).not.toBeInTheDocument()
})

it("offers registration and login links on the configured origin after enrollment", async () => {
  window.history.replaceState({}, "", "/admin/settings")
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({
    ...settings, admin: { passkey_origin: window.location.origin, passkey_count: 1 },
  }) } as Response)))
  render(<App />)
  expect(await screen.findByRole("button", { name: "注册 Passkey" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "使用 Passkey 登录" })).toHaveAttribute("href", "/admin/login")
})

it("does not remove registered passkeys without confirmation", async () => {
  window.history.replaceState({}, "", "/admin/settings")
  const fetch = vi.fn((url: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(
    url.endsWith("/settings") ? { ...settings, admin: { passkey_origin: "https://example.com", passkey_count: 2 } } : settings,
  ) } as Response))
  vi.stubGlobal("fetch", fetch)
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
  render(<App />)
  fireEvent.change(await screen.findByLabelText("Passkey 登录域名"), { target: { value: "https://new.example.com" } })
  fireEvent.click(screen.getByRole("button", { name: "保存登录域名" }))
  expect(confirm).toHaveBeenCalled()
  expect(fetch).not.toHaveBeenCalledWith("/api/admin/settings/passkey-origin", expect.anything())
  confirm.mockRestore()
})

it("shows a password fallback on the passkey login page", () => {
  window.history.replaceState({}, "", "/admin/login")
  render(<App />)
  expect(screen.getByRole("button", { name: "使用 Passkey 登录" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "使用密码登录" })).toHaveAttribute("href", "/admin/basic")
})

it("opens settings, saves server and YouTube settings, and keeps the restart notice", async () => {
  const fetch = vi.fn((url: string | URL | Request, options?: RequestInit) =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(options?.method === "PUT" ? settings :
      String(url).includes("/settings") ? settings : { podcasts: [], uses_default_password: false }) } as Response),
  )
  vi.stubGlobal("fetch", fetch)
  render(<App />)
  fireEvent.click(await screen.findByRole("button", { name: "设置" }))
  expect(window.location.pathname).toBe("/admin/settings")
  expect(await screen.findByLabelText("监听端口")).toHaveValue(8001)
  expect(screen.getByRole("region", { name: "服务监听" })).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "YouTube Cookie" })).toBeInTheDocument()
  expect(screen.queryByText("播客配置")).not.toBeInTheDocument()
  expect(screen.getByLabelText("Cookie 文件路径")).toHaveValue("/path/cookies.txt")
  fireEvent.change(screen.getByLabelText("监听端口"), { target: { value: "9000" } })
  fireEvent.click(screen.getByRole("button", { name: "保存设置" }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/admin/settings", expect.objectContaining({
    method: "PUT",
    body: expect.stringContaining('"port":9000'),
  })))
  expect(await screen.findByRole("status")).toHaveTextContent(/重启服务/)
})

it("shows the configured cookie file content and saves edits separately", async () => {
  const content = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\tSID\tsecret\n"
  const fetch = vi.fn((url: string | URL | Request, options?: RequestInit) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(String(url).endsWith("/settings/cookies")
      ? { path: settings.youtube.cookies_file, content, revision: "a".repeat(64) }
      : String(url).endsWith("/settings") ? settings : { podcasts: [], uses_default_password: false }),
  } as Response))
  vi.stubGlobal("fetch", fetch)
  render(<App />)
  fireEvent.click(await screen.findByRole("button", { name: "设置" }))
  const editor = await screen.findByLabelText("Cookie 文件内容")
  expect(editor).toHaveValue(content)
  fireEvent.change(editor, { target: { value: content.replace("secret", "updated") } })
  fireEvent.click(screen.getByRole("button", { name: "保存 Cookie 文件" }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/admin/settings/cookies", expect.objectContaining({
    method: "PUT", body: expect.stringContaining("updated"),
  })))
  expect(fetch).toHaveBeenCalledWith("/api/admin/settings/cookies", expect.objectContaining({
    body: expect.stringContaining('"revision":"' + "a".repeat(64) + '"'),
  }))
})

it("keeps unsaved cookie edits on a conflict", async () => {
  const content = "# Netscape HTTP Cookie File\n"
  vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => Promise.resolve(
    url.endsWith("/settings/cookies") && options?.method === "PUT"
      ? { ok: false, status: 409, json: () => Promise.resolve({ detail: "Cookie 文件已被修改，请刷新页面后重试" }) }
      : { ok: true, json: () => Promise.resolve(url.endsWith("/settings/cookies")
        ? { path: settings.youtube.cookies_file, content, revision: "a".repeat(64) }
        : url.endsWith("/settings") ? settings : { podcasts: [], uses_default_password: false }) },
  )))
  render(<App />)
  fireEvent.click(await screen.findByRole("button", { name: "设置" }))
  const editor = await screen.findByLabelText("Cookie 文件内容")
  fireEvent.change(editor, { target: { value: content + "# comment\n" } })
  fireEvent.click(screen.getByRole("button", { name: "保存 Cookie 文件" }))
  expect(await screen.findByText(/Cookie 文件已被修改/)).toBeInTheDocument()
  expect(editor).toHaveValue(content + "# comment\n")
})

it("changes the admin password with confirmation and clears secrets after saving", async () => {
  window.history.replaceState({}, "", "/admin/settings")
  const fetch = vi.fn((url: string) => Promise.resolve({ ok: true, json: () => Promise.resolve(
    url.endsWith("/settings/password") ? { status: "updated" } : settings,
  ) } as Response))
  vi.stubGlobal("fetch", fetch)
  render(<App />)
  expect(await screen.findByRole("button", { name: "修改密码" })).toBeInTheDocument()
  expect(screen.queryByLabelText("当前密码")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }))
  const dialog = await screen.findByRole("dialog", { name: "修改管理员密码" })
  const current = await screen.findByLabelText("当前密码")
  const next = screen.getByLabelText("新密码")
  const confirm = screen.getByLabelText("确认新密码")
  expect(current).toHaveAttribute("type", "password")
  expect(next).toHaveAttribute("type", "password")
  fireEvent.change(current, { target: { value: "adminadmin" } })
  fireEvent.change(next, { target: { value: "new-secure-password" } })
  fireEvent.change(confirm, { target: { value: "mismatch" } })
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }))
  expect(await screen.findByText("两次输入的新密码不一致")).toBeInTheDocument()
  expect(fetch).not.toHaveBeenCalledWith("/api/admin/settings/password", expect.anything())
  fireEvent.change(confirm, { target: { value: "new-secure-password" } })
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/admin/settings/password", expect.objectContaining({
    method: "PUT", body: JSON.stringify({ current_password: "adminadmin", new_password: "new-secure-password" }),
  })))
  expect(await screen.findByText(/请用新密码重新登录/)).toBeInTheDocument()
  expect(current).toHaveValue("")
  expect(next).toHaveValue("")
  expect(confirm).toHaveValue("")
  expect(dialog).not.toBeInTheDocument()
})

it("clears password fields when the dialog is closed without saving", async () => {
  window.history.replaceState({}, "", "/admin/settings")
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(settings) } as Response)))
  render(<App />)
  fireEvent.click(await screen.findByRole("button", { name: "修改密码" }))
  fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "secret" } })
  fireEvent.click(screen.getByRole("button", { name: "关闭" }))
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "修改管理员密码" })).not.toBeInTheDocument())
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }))
  expect(await screen.findByLabelText("当前密码")).toHaveValue("")
})

it("loads settings on a direct link and leaves the form open when saving fails", async () => {
  window.history.replaceState({}, "", "/admin/settings")
  vi.stubGlobal("fetch", vi.fn((_url: string, options?: RequestInit) => Promise.resolve(
    options?.method === "PUT" ? { ok: false, status: 422, json: () => Promise.resolve({ detail: "无效配置" }) } :
      { ok: true, json: () => Promise.resolve(settings) },
  )))
  render(<App />)
  expect(await screen.findByLabelText("监听地址")).toHaveValue("0.0.0.0")
  fireEvent.click(screen.getByRole("button", { name: "保存设置" }))
  expect(await screen.findByText("无效配置")).toBeInTheDocument()
  expect(screen.getByLabelText("监听端口")).toHaveValue(8001)
})
