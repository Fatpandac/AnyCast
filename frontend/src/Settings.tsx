import { FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react"
import { ArrowLeft, LoaderCircle, Save } from "lucide-react"

import { changeAdminPassword, getCookieFile, getRuntimeLog, getSettings, saveCookieFile, savePasskeyOrigin, saveSettings, type Settings } from "@/api"
import { registerPasskey } from "@/passkeys"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

type CookieSource = "none" | "file" | "browser"

export function SettingsPage({ goBack }: { goBack: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [source, setSource] = useState<CookieSource>("none")
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [cookieFilePath, setCookieFilePath] = useState("")
  const [cookieContent, setCookieContent] = useState<string | null>(null)
  const [cookieRevision, setCookieRevision] = useState("")
  const [cookieError, setCookieError] = useState("")
  const [cookieSaved, setCookieSaved] = useState(false)
  const [cookieSaving, setCookieSaving] = useState(false)
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [passwordError, setPasswordError] = useState("")
  const [passwordSaved, setPasswordSaved] = useState(false)
  const [passwordSaving, setPasswordSaving] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [passkeyOrigin, setPasskeyOrigin] = useState("")
  const [configuredOrigin, setConfiguredOrigin] = useState("")
  const [passkeyCount, setPasskeyCount] = useState(0)
  const [passkeyError, setPasskeyError] = useState("")
  const [passkeyBusy, setPasskeyBusy] = useState(false)
  const [runtimeLog, setRuntimeLog] = useState<string[] | null>(null)
  const [logBefore, setLogBefore] = useState<string | null>(null)
  const [runtimeLogError, setRuntimeLogError] = useState("")
  const [logLoading, setLogLoading] = useState(false)
  const logRef = useRef<HTMLTextAreaElement>(null)
  const logBusy = useRef(false)
  const logAfter = useRef<string | null>(null)
  const scrollRestore = useRef<{ height: number; top: number } | { top: number } | "bottom" | null>(null)

  async function loadRuntimeLog(before?: string, live = false) {
    if (logBusy.current) return
    logBusy.current = true
    if (!live) setLogLoading(true)
    try {
      const page = await getRuntimeLog(before, live ? logAfter.current ?? undefined : undefined)
      if (before) {
        const view = logRef.current
        scrollRestore.current = view ? { height: view.scrollHeight, top: view.scrollTop } : null
        setRuntimeLog((current) => [...page.lines, ...(current ?? [])])
        setLogBefore(page.before)
      } else if (live && logAfter.current) {
        if (page.lines.length) {
          const view = logRef.current
          scrollRestore.current = view && view.scrollHeight - view.scrollTop - view.clientHeight <= 40
            ? "bottom" : { top: view?.scrollTop ?? 0 }
          setRuntimeLog((current) => [...(current ?? []), ...page.lines])
        }
      } else {
        scrollRestore.current = "bottom"
        setRuntimeLog(page.lines)
        setLogBefore(page.before)
      }
      if (!before) logAfter.current = page.after
      setRuntimeLogError("")
    } catch (reason) {
      if (before) setLogBefore(null)
      if (live && reason instanceof Error && reason.message.includes("日志已轮转")) logAfter.current = null
      setRuntimeLogError(reason instanceof Error ? reason.message : "读取运行日志失败")
    } finally {
      logBusy.current = false
      if (!live) setLogLoading(false)
    }
  }

  useEffect(() => {
    void loadRuntimeLog()
    const timer = window.setInterval(() => { void loadRuntimeLog(undefined, true) }, 3000)
    return () => window.clearInterval(timer)
  }, [])
  useLayoutEffect(() => {
    const view = logRef.current
    if (!view || !scrollRestore.current) return
    view.scrollTop = scrollRestore.current === "bottom"
      ? view.scrollHeight
      : "height" in scrollRestore.current
        ? view.scrollHeight - scrollRestore.current.height + scrollRestore.current.top
        : scrollRestore.current.top
    scrollRestore.current = null
  }, [runtimeLog])

  function scrollRuntimeLog() {
    if (logRef.current && logRef.current.scrollTop <= 32 && logBefore) void loadRuntimeLog(logBefore)
  }

  function togglePasswordDialog(open: boolean) {
    if (passwordSaving) return
    setPasswordOpen(open)
    setCurrentPassword("")
    setNewPassword("")
    setConfirmPassword("")
    setPasswordError("")
  }

  useEffect(() => {
    let active = true
    setCookieContent(null)
    setCookieError("")
    setCookieSaved(false)
    if (cookieFilePath) {
      void getCookieFile().then((data) => {
        if (active) {
          if (data.path === cookieFilePath) {
            setCookieContent(data.content)
            setCookieRevision(data.revision)
          }
          else setCookieError("配置已变更，请刷新页面")
        }
      }).catch((reason) => {
        if (active) setCookieError(reason instanceof Error ? reason.message : "读取 Cookie 文件失败")
      })
    }
    return () => { active = false }
  }, [cookieFilePath])

  async function submitCookieFile() {
    if (cookieContent === null) return
    setCookieSaving(true)
    setCookieSaved(false)
    setCookieError("")
    try {
      const data = await saveCookieFile(cookieFilePath, cookieContent, cookieRevision)
      setCookieRevision(data.revision)
      setCookieSaved(true)
    } catch (reason) {
      setCookieError(reason instanceof Error ? reason.message : "保存 Cookie 文件失败")
    } finally {
      setCookieSaving(false)
    }
  }


  useEffect(() => {
    void getSettings().then((data) => {
      setSettings(data)
      setPasskeyOrigin(data.admin?.passkey_origin || "")
      setConfiguredOrigin(data.admin?.passkey_origin || "")
      setPasskeyCount(data.admin?.passkey_count || 0)
      setCookieFilePath(data.youtube.cookies_file)
      setSource(data.youtube.cookies_file ? "file" : data.youtube.cookies_from_browser ? "browser" : "none")
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"))
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!settings) return
    setSaving(true)
    setError("")
    setSaved(false)
    try {
      const data = await saveSettings({
        server: { host: settings.server.host.trim(), port: settings.server.port },
        youtube: {
          cookies_file: source === "file" ? settings.youtube.cookies_file.trim() : "",
          cookies_from_browser: source === "browser" ? settings.youtube.cookies_from_browser.trim() : "",
        },
      })
      setSettings(data)
      setCookieFilePath(data.youtube.cookies_file)
      setSaved(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  async function saveOrigin() {
    const origin = passkeyOrigin.trim()
    if (passkeyCount && origin !== configuredOrigin && !window.confirm("更换域名会删除已注册的 Passkey 并使 Passkey 登录失效，确定继续吗？")) return
    setPasskeyError("")
    setPasskeyBusy(true)
    try {
      const result = await savePasskeyOrigin(origin)
      setPasskeyOrigin(result.passkey_origin)
      setConfiguredOrigin(result.passkey_origin)
      setPasskeyCount(result.passkey_count)
    } catch (reason) {
      setPasskeyError(reason instanceof Error ? reason.message : "保存域名失败")
    } finally {
      setPasskeyBusy(false)
    }
  }

  async function enrollPasskey() {
    setPasskeyError("")
    setPasskeyBusy(true)
    try {
      const result = await registerPasskey()
      setPasskeyCount(result.passkey_count)
    } catch (reason) {
      setPasskeyError(reason instanceof Error ? reason.message : "注册 Passkey 失败")
    } finally {
      setPasskeyBusy(false)
    }
  }

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPasswordError("")
    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的新密码不一致")
      return
    }
    setPasswordSaving(true)
    setPasswordSaved(false)
    try {
      await changeAdminPassword(currentPassword, newPassword)
      setCurrentPassword("")
      setNewPassword("")
      setConfirmPassword("")
      setCookieContent(null)
      setPasswordOpen(false)
      setPasswordSaved(true)
    } catch (reason) {
      setPasswordError(reason instanceof Error ? reason.message : "修改密码失败")
    } finally {
      setPasswordSaving(false)
    }
  }

  return (
    <>
      <header className="border-b bg-card">
        <div className="mx-auto max-w-3xl px-4 py-5 sm:px-6">
          <Button variant="ghost" size="sm" className="-ml-3 mb-3 text-muted-foreground" onClick={goBack}><ArrowLeft />返回管理后台</Button>
          <h1 className="text-2xl font-semibold tracking-tight">AnyCast 设置</h1>
          <p className="mt-1 text-sm text-muted-foreground">管理服务监听和 YouTube 下载选项</p>
        </div>
      </header>
      <main className="mx-auto grid grid-cols-1 max-w-3xl gap-5 px-4 py-6 sm:px-6">
        {error && <Alert className="border-destructive/40 bg-destructive/5 text-destructive" role="alert"><AlertTitle>操作失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        {saved && <Alert role="status"><AlertDescription>设置已保存。修改监听地址或端口后，请重启服务；YouTube Cookie 设置将在下次下载时生效。</AlertDescription></Alert>}
        {!settings && !error && <div className="flex justify-center py-16 text-muted-foreground"><LoaderCircle className="size-6 animate-spin" /></div>}
        {settings && (
          <form className="grid gap-8" onSubmit={(event) => void submit(event)}>
            <section aria-labelledby="server-settings-title" className="grid gap-4 border-b pb-8">
              <div className="space-y-1">
                <h2 id="server-settings-title" className="text-lg font-semibold">服务监听</h2>
                <p className="text-sm text-muted-foreground">修改监听地址或端口后需重启服务；0.0.0.0 仅用于监听，浏览器应使用服务器 IP 或域名访问。</p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2"><Label htmlFor="server-host">监听地址</Label><Input id="server-host" required value={settings.server.host} onChange={(event) => setSettings({ ...settings, server: { ...settings.server, host: event.target.value } })} /></div>
                <div className="grid gap-2"><Label htmlFor="server-port">监听端口</Label><Input id="server-port" type="number" required min={1} max={65535} value={settings.server.port} onChange={(event) => setSettings({ ...settings, server: { ...settings.server, port: Number(event.target.value) } })} /></div>
              </div>
            </section>
            <section aria-labelledby="youtube-settings-title" className="grid gap-4 border-b pb-8">
              <div className="space-y-1">
                <h2 id="youtube-settings-title" className="text-lg font-semibold">YouTube Cookie</h2>
                <p className="text-sm text-muted-foreground">选择一种来源以绕过 bot 检测。文件模式下可查看、编辑服务器上的 Cookie 内容；这是敏感凭据，建议修改默认管理密码并使用 HTTPS 访问。</p>
              </div>
              <div className="grid gap-4">
                <div className="grid gap-2"><Label htmlFor="cookie-source">Cookie 来源</Label>
                  <Select value={source} onValueChange={(value) => setSource(value as CookieSource)}><SelectTrigger id="cookie-source" aria-label="Cookie 来源"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">不使用</SelectItem><SelectItem value="file">Cookie 文件</SelectItem><SelectItem value="browser">服务器浏览器</SelectItem></SelectContent></Select>
                </div>
                {source === "file" && <>
                  <div className="grid gap-2"><Label htmlFor="cookies-file">Cookie 文件路径</Label><Input id="cookies-file" required placeholder="/path/to/cookies.txt" value={settings.youtube.cookies_file} onChange={(event) => setSettings({ ...settings, youtube: { ...settings.youtube, cookies_file: event.target.value } })} /></div>
                  {settings.youtube.cookies_file !== cookieFilePath ? <p className="text-sm text-muted-foreground">请先保存新的文件路径，再编辑文件内容。</p> : <>
                    {cookieError && <Alert className="border-destructive/40 bg-destructive/5 text-destructive" role="alert"><AlertDescription>{cookieError}{cookieError.includes("文件不存在") && "。请先将上方路径改成服务器上已有的 Cookie 文件并保存设置。"}</AlertDescription></Alert>}
                    {cookieContent !== null && <div className="grid gap-2">
                      <Label htmlFor="cookie-content">Cookie 文件内容</Label>
                      <textarea id="cookie-content" rows={10} spellCheck={false} autoComplete="off" className="w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" value={cookieContent} onChange={(event) => { setCookieContent(event.target.value); setCookieSaved(false) }} />
                      <div className="flex items-center justify-between gap-3"><p className="text-sm text-muted-foreground">仅支持 Netscape 格式，最大 1 MiB；文件内容不会写入 config.yaml。</p><Button type="button" variant="outline" disabled={cookieSaving} onClick={() => void submitCookieFile()}>{cookieSaving && <LoaderCircle className="animate-spin" />}保存 Cookie 文件</Button></div>
                      {cookieSaved && <p className="text-sm text-emerald-700">Cookie 文件已保存，后续下载将使用新内容。</p>}
                    </div>}
                  </>}
                </>}

                {source === "browser" && <div className="grid gap-2"><Label htmlFor="cookies-browser">服务器浏览器名称</Label><Input id="cookies-browser" required placeholder="chrome / firefox / safari" value={settings.youtube.cookies_from_browser} onChange={(event) => setSettings({ ...settings, youtube: { ...settings.youtube, cookies_from_browser: event.target.value } })} /></div>}
              </div>
            </section>
            <div className="flex justify-end"><Button type="submit" disabled={saving}>{saving ? <LoaderCircle className="animate-spin" /> : <Save />}保存设置</Button></div>
          </form>
        )}
        <section aria-labelledby="security-settings-title" className="grid gap-4 py-2">
          <div className="space-y-1">
            <h2 id="security-settings-title" className="text-lg font-semibold">安全设置</h2>
            <p className="text-sm text-muted-foreground">管理员密码可在此修改，保存后立即生效。</p>
          </div>
          {passwordSaved && <Alert role="status"><AlertDescription>密码已修改。请用新密码重新登录（可刷新页面）。</AlertDescription></Alert>}
          <div className="flex items-center justify-between gap-4 border-t py-4">
            <div><p className="font-medium">管理员密码</p><p className="text-sm text-muted-foreground">修改登录管理后台使用的密码</p></div>
            <Dialog open={passwordOpen} onOpenChange={togglePasswordDialog}>
              <DialogTrigger asChild><Button type="button" variant="outline">修改密码</Button></DialogTrigger>
              <DialogContent className="max-w-md">
                <DialogHeader>
                  <DialogTitle>修改管理员密码</DialogTitle>
                  <DialogDescription>保存后立即生效，无需重启。新密码将以加盐哈希保存在本机 config.yaml 中，优先于 ANYCAST_ADMIN_PASSWORD 环境变量；请妥善保管。</DialogDescription>
                </DialogHeader>
                <form className="grid gap-4" onSubmit={(event) => void submitPassword(event)}>
                  <div className="grid gap-2"><Label htmlFor="current-password">当前密码</Label><Input id="current-password" type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></div>
                  <div className="grid gap-2"><Label htmlFor="new-password">新密码</Label><Input id="new-password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></div>
                  <div className="grid gap-2"><Label htmlFor="confirm-password">确认新密码</Label><Input id="confirm-password" type="password" autoComplete="new-password" required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></div>
                  {passwordError && <Alert className="border-destructive/40 bg-destructive/5 text-destructive" role="alert"><AlertDescription>{passwordError}</AlertDescription></Alert>}
                  <div className="flex justify-end"><Button type="submit" disabled={passwordSaving}>{passwordSaving && <LoaderCircle className="animate-spin" />}修改密码</Button></div>
                </form>
              </DialogContent>
            </Dialog>
          </div>
          <div className="grid gap-3 border-t py-4">
            <div><p className="font-medium">Passkey 登录</p><p className="text-sm text-muted-foreground">先保存此后台的 HTTPS 域名，再通过该域名打开本页面注册。密码登录仍可用于恢复。</p></div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="grid min-w-0 flex-1 gap-2"><Label htmlFor="passkey-origin">Passkey 登录域名</Label><Input id="passkey-origin" type="url" placeholder="https://example.com" value={passkeyOrigin} onChange={(event) => setPasskeyOrigin(event.target.value)} /></div>
              <Button type="button" variant="outline" disabled={passkeyBusy} onClick={() => void saveOrigin()}>保存登录域名</Button>
            </div>
            {configuredOrigin && passkeyOrigin === configuredOrigin && window.location.origin === configuredOrigin &&
              <div className="flex flex-wrap items-center gap-3"><Button type="button" variant="outline" disabled={passkeyBusy || !("credentials" in navigator)} onClick={() => void enrollPasskey()}>{passkeyBusy && <LoaderCircle className="animate-spin" />}注册 Passkey</Button><span className="text-sm text-muted-foreground">已注册 {passkeyCount} 个</span>{passkeyCount > 0 && <a href="/admin/login" className="text-sm underline">使用 Passkey 登录</a>}</div>}
            {configuredOrigin && window.location.origin !== configuredOrigin && <p className="text-sm text-muted-foreground">请用 {configuredOrigin}/admin/settings 访问后注册；反向代理需保留 Host 请求头。</p>}
            {passkeyError && <Alert role="alert" className="border-destructive/40 bg-destructive/5 text-destructive"><AlertDescription>{passkeyError}</AlertDescription></Alert>}
          </div>
        </section>
        <section aria-labelledby="runtime-log-title" className="relative left-1/2 grid w-[min(95vw,70rem)] -translate-x-1/2 gap-3 border-t py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-1">
              <h2 id="runtime-log-title" className="text-lg font-semibold">运行日志</h2>
              <p className="text-sm text-muted-foreground">日志每 3 秒自动更新；初次加载最新 100 行，向上滚动查看更多。</p>
            </div>
          </div>
          {runtimeLogError && <Alert role="alert"><AlertDescription>{runtimeLogError}</AlertDescription></Alert>}
          <textarea ref={logRef} aria-label="运行日志" readOnly spellCheck={false} wrap="soft" value={runtimeLog?.join("\n") ?? ""} onScroll={scrollRuntimeLog} placeholder={logLoading ? "正在加载运行日志…" : "暂无运行日志。"} className="h-[70vh] min-h-[32rem] w-full resize-y overflow-auto rounded-md border bg-muted p-4 font-mono text-xs leading-relaxed" />
        </section>
      </main>
    </>
  )
}
