import { FormEvent, useCallback, useEffect, useState } from "react"
import { AlertTriangle, ExternalLink, LoaderCircle, Plus, Radio, Trash2 } from "lucide-react"

import { createPodcast, deletePodcast, listPodcasts, type Podcast, type PodcastInput } from "@/api"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const selectClass = "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"

export function Dashboard({ openPodcast }: { openPodcast: (name: string) => void }) {
  const [podcasts, setPodcasts] = useState<Podcast[]>([])
  const [usesDefaultPassword, setUsesDefaultPassword] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")

  const load = useCallback(async () => {
    try {
      const data = await listPodcasts()
      setPodcasts(data.podcasts)
      setUsesDefaultPassword(data.uses_default_password)
      setError("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    const keepLatest = String(values.get("keep_latest") || "")
    const podcast: PodcastInput = {
      name: String(values.get("name") || "").trim(),
      url: String(values.get("url") || "").trim(),
      update_period_cron: String(values.get("update_period_cron") || "").trim(),
      keep_latest: keepLatest ? Number(keepLatest) : null,
      page_size: Number(values.get("page_size") || 20),
      sort_by: values.get("sort_by") as PodcastInput["sort_by"],
      sort_order: values.get("sort_order") as PodcastInput["sort_order"],
    }

    setSaving(true)
    setMessage("")
    try {
      await createPodcast(podcast)
      form.reset()
      setMessage("播客已添加，定时任务已生效。")
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "添加失败")
    } finally {
      setSaving(false)
    }
  }

  async function remove(name: string) {
    if (!window.confirm(`移除 ${name}？下载文件和历史记录会保留。`)) return
    try {
      await deletePodcast(name)
      setMessage("播客配置已移除，下载文件和历史记录已保留。")
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "移除失败")
    }
  }

  const episodeCount = podcasts.reduce((sum, item) => sum + (item.episode_count || 0), 0)

  return (
    <>
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-5 sm:px-6">
          <div className="rounded-lg bg-primary p-2 text-primary-foreground"><Radio className="size-5" /></div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">AnyCast 管理后台</h1>
            <p className="text-sm text-muted-foreground">管理订阅源和下载计划</p>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6">
        {usesDefaultPassword && (
          <Alert className="border-amber-300 bg-amber-50 text-amber-950">
            <AlertTriangle className="mb-2 size-4" />
            <AlertTitle>正在使用默认密码 adminadmin</AlertTitle>
            <AlertDescription>请立即设置 ANYCAST_ADMIN_PASSWORD 替换密码。</AlertDescription>
          </Alert>
        )}
        {error && <Alert className="border-destructive/40 bg-destructive/5 text-destructive"><AlertTitle>操作失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        {message && <Alert className="border-emerald-300 bg-emerald-50 text-emerald-950"><AlertDescription>{message}</AlertDescription></Alert>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Card><CardHeader className="pb-3"><CardDescription>播客数量</CardDescription><CardTitle className="text-3xl">{podcasts.length}</CardTitle></CardHeader></Card>
          <Card><CardHeader className="pb-3"><CardDescription>已下载内容</CardDescription><CardTitle className="text-3xl">{episodeCount}</CardTitle></CardHeader></Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>播客</CardTitle>
            <CardDescription>点击播客查看下载记录和内容详情。</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex justify-center py-12 text-muted-foreground"><LoaderCircle className="size-5 animate-spin" /></div>
            ) : podcasts.length === 0 ? (
              <div className="rounded-lg border border-dashed py-12 text-center text-sm text-muted-foreground">还没有播客，请在下方添加。</div>
            ) : (
              <Table>
                <TableHeader><TableRow><TableHead>名称 / 地址</TableHead><TableHead>已下载</TableHead><TableHead>更新计划</TableHead><TableHead>保留</TableHead><TableHead className="text-right">操作</TableHead></TableRow></TableHeader>
                <TableBody>
                  {podcasts.map((podcast) => (
                    <TableRow
                      key={podcast.name}
                      className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      tabIndex={0}
                      aria-label={`查看 ${podcast.name}`}
                      onClick={() => openPodcast(podcast.name)}
                      onKeyDown={(event) => {
                        if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
                          event.preventDefault()
                          openPodcast(podcast.name)
                        }
                      }}
                    >
                      <TableCell className="min-w-64">
                        <span className="block font-medium text-primary">{podcast.name}</span>
                        <span className="block max-w-md truncate text-xs text-muted-foreground" title={podcast.url}>{podcast.url}</span>
                      </TableCell>
                      <TableCell><Badge>{podcast.episode_count || 0} 集</Badge></TableCell>
                      <TableCell><code className="rounded bg-muted px-2 py-1 text-xs">{podcast.update_period_cron}</code></TableCell>
                      <TableCell>{podcast.keep_latest ?? "全部"}</TableCell>
                      <TableCell onClick={(event) => event.stopPropagation()}>
                        <div className="flex justify-end gap-1">
                          <Button asChild size="sm" variant="ghost"><a href={`/rss/${encodeURIComponent(podcast.name)}`} target="_blank" rel="noreferrer"><ExternalLink />RSS</a></Button>
                          <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => void remove(podcast.name)}><Trash2 />移除</Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>添加播客</CardTitle><CardDescription>支持 Bilibili 和 YouTube 播放列表。</CardDescription></CardHeader>
          <CardContent>
            <form className="grid gap-5" onSubmit={add}>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="名称" htmlFor="name"><Input id="name" name="name" required maxLength={64} pattern="[\w-]+" placeholder="weekly-news" /></Field>
                <Field label="更新计划（Cron）" htmlFor="cron"><Input id="cron" name="update_period_cron" required defaultValue="0 * * * *" /></Field>
                <Field className="sm:col-span-2" label="播放列表地址" htmlFor="url"><Input id="url" name="url" type="url" required placeholder="https://..." /></Field>
                <Field label="保留最新集数" htmlFor="keep"><Input id="keep" name="keep_latest" type="number" min={1} placeholder="留空则不清理" /></Field>
                <Field label="每次扫描数量" htmlFor="page-size"><Input id="page-size" name="page_size" type="number" min={1} defaultValue={20} /></Field>
                <Field label="排序字段" htmlFor="sort-by"><select className={selectClass} id="sort-by" name="sort_by" defaultValue="date"><option value="date">发布时间</option><option value="title">标题</option></select></Field>
                <Field label="播放列表顺序" htmlFor="sort-order"><select className={selectClass} id="sort-order" name="sort_order" defaultValue="desc"><option value="desc">新到旧</option><option value="asc">旧到新</option></select></Field>
              </div>
              <div><Button type="submit" disabled={saving}>{saving ? <LoaderCircle className="animate-spin" /> : <Plus />}添加播客</Button></div>
            </form>
          </CardContent>
        </Card>
      </main>
    </>
  )
}

function Field({ label, htmlFor, className, children }: { label: string; htmlFor: string; className?: string; children: React.ReactNode }) {
  return <div className={className}><Label htmlFor={htmlFor}>{label}</Label><div className="mt-2">{children}</div></div>
}
