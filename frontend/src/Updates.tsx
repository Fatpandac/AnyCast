import { useEffect, useRef, useState } from "react"
import { Download, LoaderCircle, RefreshCw } from "lucide-react"

import { checkApplicationUpdate, getUpdateStatus, installApplicationUpdate, type UpdateStatus } from "@/api"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

const phases: Record<string, string> = {
  preparing: "准备更新", installing: "安装依赖中", restarting: "重启中", recovering: "正在恢复旧版",
}

function commitLink(sha: string | null | undefined) {
  return sha ? <a href={`https://github.com/Fatpandac/AnyCast/commit/${sha}`} target="_blank" rel="noreferrer" className="font-mono text-primary underline underline-offset-4">{sha.slice(0, 7)}</a> : "未知"
}

export function ApplicationUpdates() {
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState("")
  const [loadError, setLoadError] = useState("")
  const [reconnecting, setReconnecting] = useState(false)
  const [stopped, setStopped] = useState(false)
  const expected = useRef<string | null>(null)
  const attempts = useRef(0)
  const inFlight = useRef(false)
  const pollingStopped = useRef(false)

  function accept(next: UpdateStatus) {
    if (phases[next.phase] && !expected.current) expected.current = next.target ?? next.latest_sha
    if (next.phase === "failed" || next.current_sha === expected.current) {
      expected.current = null
      attempts.current = 0
    } else if (phases[next.phase]) {
      attempts.current = 0
    } else if (expected.current) {
      attempts.current += 1
    }
    setStatus(next)
    setLoadError("")
    setReconnecting(false)
  }

  useEffect(() => {
    let mounted = true
    async function poll() {
      if (inFlight.current || pollingStopped.current) return
      if (expected.current && attempts.current >= 90) {
        pollingStopped.current = true
        if (mounted) { setStopped(true); setError("重连超时，请检查服务器终端或私有更新日志，再手动检查状态。"); setReconnecting(false) }
        return
      }
      inFlight.current = true
      try {
        const next = await getUpdateStatus()
        if (mounted) accept(next)
      } catch (reason) {
        if (mounted) {
          if (expected.current) { attempts.current += 1; setReconnecting(true) }
          else setLoadError(reason instanceof Error ? reason.message : "无法读取应用更新状态")
        }
      } finally {
        inFlight.current = false
      }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 2000)
    return () => { mounted = false; window.clearInterval(timer) }
  }, [])

  async function check() {
    if (inFlight.current) return
    inFlight.current = true
    setChecking(true)
    setError("")
    setStopped(false)
    pollingStopped.current = false
    attempts.current = 0
    try {
      accept(await checkApplicationUpdate())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "检查更新失败")
    } finally {
      inFlight.current = false
      setChecking(false)
    }
  }

  async function install() {
    const target = status?.latest_sha
    if (!target || inFlight.current || !window.confirm(`更新到 main 提交 ${target.slice(0, 7)} 并重启？服务会短暂中断；正在下载或有本地修改时不会安装。`)) return
    inFlight.current = true
    expected.current = target
    attempts.current = 0
    setError("")
    setStatus((current) => current && { ...current, phase: "preparing", target, can_update: false })
    try {
      accept(await installApplicationUpdate(target))
    } catch (reason) {
      if (reason && typeof reason === "object" && "status" in reason) {
        expected.current = null
        setStatus((current) => current && { ...current, phase: "failed" })
        setError(reason instanceof Error ? reason.message : "提交更新失败")
      } else {
        // A lost response may still mean the parent accepted the update.
        setReconnecting(true)
      }
    } finally {
      inFlight.current = false
    }
  }

  const active = Boolean(status && phases[status.phase])
  const busy = active && !stopped
  const failure = error || loadError || status?.error || (status?.phase === "failed" ? status.message : "")
  const wrongVersion = status?.phase === "success" && status.target && status.current_sha !== status.target
  const success = status?.phase === "success" && status.target && status.current_sha === status.target && !status.update_available

  return <section aria-labelledby="application-updates-title" className="grid min-w-0 gap-4 border-t py-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <h2 id="application-updates-title" className="text-lg font-semibold">应用更新</h2>
        <p className="text-sm text-muted-foreground">跟随 GitHub main 分支，每小时检查一次；仅在确认后安装。</p>
      </div>
      <Button type="button" size="sm" variant="outline" disabled={checking || busy} onClick={() => void check()}>{checking ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}检查更新</Button>
    </div>
    <dl className="grid gap-4 rounded-lg border bg-card p-4 sm:grid-cols-2">
      <div className="space-y-1"><dt className="text-sm text-muted-foreground">当前运行提交</dt><dd>{commitLink(status?.current_sha)}</dd></div>
      <div className="space-y-1"><dt className="text-sm text-muted-foreground">最新 main 提交</dt><dd>{status?.latest_sha ? commitLink(status.latest_sha) : "尚未检查"}</dd></div>
      {status?.latest_message && <div className="min-w-0 space-y-1 sm:col-span-2"><dt className="text-sm text-muted-foreground">最新提交说明</dt><dd className="break-words text-sm">{status.latest_message}</dd>{status.latest_date && <dd className="text-xs text-muted-foreground">{new Date(status.latest_date).toLocaleString()}</dd>}</div>}
    </dl>
    {failure && <Alert role="alert" className="border-destructive/40 bg-destructive/5 text-destructive"><AlertDescription>{failure}</AlertDescription></Alert>}
    <div aria-live="polite" className="space-y-2 text-sm">
      {busy && <p className="flex items-center gap-2"><LoaderCircle className="size-4 shrink-0 animate-spin" />{phases[status!.phase]}</p>}
      {reconnecting && <p className="text-muted-foreground">服务暂时断开，正在等待服务恢复并核对运行版本…</p>}
      {wrongVersion && <p className="text-destructive">运行版本尚未匹配目标提交，请检查日志，尚不能确认更新成功。</p>}
      {!failure && !wrongVersion && success && <p className="text-emerald-700">更新成功，运行版本已确认</p>}
      {!failure && !active && !success && status?.relation === "current" && <p>已是最新提交</p>}
      {status?.reason && !busy && <p className="break-words text-muted-foreground">{status.reason}</p>}
    </div>
    {status?.update_available && <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted-foreground">更新会短暂停机，配置和音频文件保留。</p>
      <Button type="button" disabled={!status.can_update || checking || active || Boolean(error || loadError || status.error)} onClick={() => void install()}><Download />更新并重启</Button>
    </div>}
    <p className="text-xs text-muted-foreground">最近检查：{status?.checked_at ? new Date(status.checked_at).toLocaleString() : "尚未检查"} · 安装要求 macOS/Linux、干净的 main 工作区及受管启动。</p>
  </section>
}
