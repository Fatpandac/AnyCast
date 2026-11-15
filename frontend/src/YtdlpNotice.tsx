import { useEffect, useState } from "react"
import { AlertTriangle, ChevronRight } from "lucide-react"

import { getYtdlpStatus } from "@/api"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"

export function YtdlpNotice() {
  const [updateError, setUpdateError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState("")

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const status = await getYtdlpStatus()
        if (active) {
          setUpdateError(status.update_error)
          setLoadError("")
        }
      } catch (reason) {
        if (active) setLoadError(reason instanceof Error ? reason.message : "读取状态失败")
      }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 30000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  if (!updateError && !loadError) return null
  const title = updateError ? "yt-dlp 自动升级失败" : "无法读取 yt-dlp 升级状态"
  return <Dialog>
    <Alert className="flex items-center gap-3 border-border bg-card px-4 py-3 text-foreground shadow-sm">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200/60">
        <AlertTriangle className="size-4" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <AlertTitle className="mb-0 text-sm leading-5 tracking-normal">{title}</AlertTitle>
        <AlertDescription className="text-xs text-muted-foreground">
          {updateError ? "需使用原安装工具手动升级" : "连接恢复后将自动重试"}
        </AlertDescription>
      </div>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="h-10 shrink-0 gap-1 px-2 text-muted-foreground">
          查看详情<ChevronRight className="size-3.5" aria-hidden="true" />
        </Button>
      </DialogTrigger>
    </Alert>
    <DialogContent className="max-w-lg">
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>
          {updateError ? "请在服务器上使用安装 yt-dlp 时的工具更新，例如 pip、pipx 或 Homebrew。" : "暂时无法读取状态，不代表自动升级失败。页面会继续重试。"}
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">原始错误</h3>
        <pre tabIndex={0} aria-label="yt-dlp 原始错误" className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted p-3 font-mono text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{updateError || loadError}</pre>
      </div>
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs leading-relaxed text-muted-foreground">{updateError ? "当前版本仍兼容时，下载可继续运行。" : "状态恢复后，提示会自动消失。"}</p>
        <DialogClose asChild><Button variant="outline" className="h-10 shrink-0">知道了</Button></DialogClose>
      </div>
    </DialogContent>
  </Dialog>
}
