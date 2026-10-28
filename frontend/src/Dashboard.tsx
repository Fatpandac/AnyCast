import { FormEvent, useCallback, useEffect, useState } from "react"
import { AlertTriangle, ChevronDown, ExternalLink, LoaderCircle, Pencil, Plus, Radio, RotateCw, Settings2, Trash2 } from "lucide-react"

import { createPodcast, deletePodcast, listPodcasts, runPodcastUpdate, updatePodcast, type Podcast, type PodcastInput } from "@/api"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { describeSchedule, parseScheduleCron, scheduleCron, type Frequency } from "@/schedule"

const selectClass = "h-9 w-full appearance-none rounded-md border border-input bg-transparent py-1 pl-3 pr-9 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"

export function Dashboard({ openPodcast, openSettings }: { openPodcast: (name: string) => void; openSettings: () => void }) {
  const [podcasts, setPodcasts] = useState<Podcast[]>([])
  const [usesDefaultPassword, setUsesDefaultPassword] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [updating, setUpdating] = useState<string | null>(null)
  const [editingPodcast, setEditingPodcast] = useState<Podcast | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [frequency, setFrequency] = useState<Frequency>("hourly")
  const [scheduleTime, setScheduleTime] = useState("09:00")
  const [weekday, setWeekday] = useState("0")
  const [monthDay, setMonthDay] = useState("1")
  const [customCron, setCustomCron] = useState<string | null>(null)
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

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!validSchedule) return
    const form = event.currentTarget
    const values = new FormData(form)
    const keepLatest = String(values.get("keep_latest") || "")
    const podcast: PodcastInput = {
      name: editingPodcast?.name || String(values.get("name") || "").trim(),
      url: String(values.get("url") || "").trim(),
      update_period_cron: customCron?.trim() || scheduleCron(frequency, scheduleTime, weekday, monthDay),
      keep_latest: keepLatest ? Number(keepLatest) : null,
      page_size: Number(values.get("page_size") || 20),
      sort_by: values.get("sort_by") as PodcastInput["sort_by"],
      sort_order: values.get("sort_order") as PodcastInput["sort_order"],
    }

    setSaving(true)
    setMessage("")
    try {
      if (editingPodcast) await updatePodcast(editingPodcast.name, podcast)
      else await createPodcast(podcast)
      form.reset()
      closeForm()
      setMessage(editingPodcast ? "播客配置已更新，定时任务已生效。" : "播客已添加，定时任务已生效。")
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : editingPodcast ? "更新失败" : "添加失败")
    } finally {
      setSaving(false)
    }
  }

  function closeForm() {
    setAddOpen(false)
    setEditingPodcast(null)
    setScheduleOpen(false)
    setFrequency("hourly")
    setScheduleTime("09:00")
    setWeekday("0")
    setMonthDay("1")
    setCustomCron(null)
    setError("")
  }

  function openEditor(podcast: Podcast) {
    const schedule = parseScheduleCron(podcast.update_period_cron)
    if (schedule) {
      setFrequency(schedule.frequency)
      setScheduleTime(schedule.time)
      setWeekday(schedule.weekday)
      setMonthDay(schedule.monthDay)
      setCustomCron(null)
    } else {
      setCustomCron(podcast.update_period_cron)
    }
    setError("")
    setEditingPodcast(podcast)
  }

  async function updateNow(name: string) {
    setUpdating(name)
    setError("")
    setMessage("")
    try {
      await runPodcastUpdate(name)
      setMessage(`${name} 已提交更新任务，可在「设置 → 运行日志」查看进度。`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交更新失败")
    } finally {
      setUpdating(null)
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
  const validSchedule = customCron !== null ? Boolean(customCron.trim()) : (frequency === "hourly" || frequency === "minutes15" || /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(scheduleTime))
    && (frequency !== "monthly" || (Number.isInteger(Number(monthDay)) && Number(monthDay) >= 1 && Number(monthDay) <= 31))
  const scheduleDescription = customCron ?? (validSchedule ? describeSchedule(scheduleCron(frequency, scheduleTime, weekday, monthDay)) : "请完善更新计划")

  return (
    <>
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-5 sm:px-6">
          <div className="rounded-lg bg-primary p-2 text-primary-foreground"><Radio className="size-5" /></div>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold tracking-tight">AnyCast 管理后台</h1>
            <p className="text-sm text-muted-foreground">管理订阅源和下载计划</p>
          </div>
          <Button variant="outline" onClick={openSettings}><Settings2 />设置</Button>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6">
        {usesDefaultPassword && (
          <Alert className="border-amber-300 bg-amber-50 text-amber-950">
            <AlertTriangle className="mb-2 size-4" />
            <AlertTitle>正在使用默认密码 adminadmin</AlertTitle>
            <AlertDescription>请到「设置 → 管理员密码」立即修改，或设置 ANYCAST_ADMIN_PASSWORD。</AlertDescription>
          </Alert>
        )}
        {error && !addOpen && !editingPodcast && <Alert className="border-destructive/40 bg-destructive/5 text-destructive"><AlertTitle>操作失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        {message && <Alert className="border-emerald-300 bg-emerald-50 text-emerald-950"><AlertDescription>{message}</AlertDescription></Alert>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Card><CardHeader className="pb-3"><CardDescription>播客数量</CardDescription><CardTitle className="text-3xl">{podcasts.length}</CardTitle></CardHeader></Card>
          <Card><CardHeader className="pb-3"><CardDescription>已下载内容</CardDescription><CardTitle className="text-3xl">{episodeCount}</CardTitle></CardHeader></Card>
        </div>

        <Dialog open={addOpen || Boolean(editingPodcast)} onOpenChange={(open) => {
          if (saving) return
          if (open) {
            setError("")
            setAddOpen(true)
          } else closeForm()
        }}>
          <Card>
            <CardHeader className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
              <div className="space-y-1.5"><CardTitle>播客</CardTitle><CardDescription>点击播客查看下载记录和内容详情。</CardDescription></div>
              <DialogTrigger asChild><Button className="shrink-0"><Plus />添加播客</Button></DialogTrigger>
            </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex justify-center py-12 text-muted-foreground"><LoaderCircle className="size-5 animate-spin" /></div>
            ) : podcasts.length === 0 ? (
              <div className="rounded-lg border border-dashed py-12 text-center text-sm text-muted-foreground">还没有播客，点击“添加播客”开始。</div>
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
                      <TableCell className="whitespace-nowrap">{describeSchedule(podcast.update_period_cron)}</TableCell>
                      <TableCell>{podcast.keep_latest ?? "全部"}</TableCell>
                      <TableCell onClick={(event) => event.stopPropagation()}>
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" aria-label={`立即更新 ${podcast.name}`} disabled={updating === podcast.name} onClick={() => void updateNow(podcast.name)}>{updating === podcast.name ? <LoaderCircle className="animate-spin" /> : <RotateCw />}立即更新</Button>
                          <Button size="sm" variant="ghost" aria-label={`编辑 ${podcast.name}`} onClick={() => openEditor(podcast)}><Pencil />编辑</Button>
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

          <DialogContent key={editingPodcast?.name || "add"}>
            <DialogHeader>
              <DialogTitle>{editingPodcast ? `编辑 ${editingPodcast.name}` : "添加播客"}</DialogTitle>
              <DialogDescription>{editingPodcast ? "修改播客配置并保存。" : "支持 Bilibili 和 YouTube 播放列表。"}</DialogDescription>
            </DialogHeader>
            {error && <Alert className="border-destructive/40 bg-destructive/5 text-destructive"><AlertTitle>操作失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
            <form className="grid gap-5" onSubmit={save}>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="名称" htmlFor="name"><Input id="name" name="name" required maxLength={64} pattern="[\w-]+" placeholder="weekly-news" defaultValue={editingPodcast?.name} readOnly={Boolean(editingPodcast)} /></Field>
                {customCron !== null ? (
                  <Field label="更新计划（Cron）" htmlFor="cron"><Input id="cron" required value={customCron} onChange={(event) => setCustomCron(event.target.value)} /></Field>
                ) : (
                <Field label="更新频率" htmlFor="schedule-trigger">
                  <Popover open={scheduleOpen} onOpenChange={setScheduleOpen}>
                    <PopoverTrigger asChild>
                      <Button id="schedule-trigger" type="button" variant="outline" aria-label={`更新频率：${scheduleDescription}`} className="w-full justify-between px-3 font-normal shadow-sm">
                        {scheduleDescription}<ChevronDown aria-hidden="true" className="text-muted-foreground" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent aria-label="选择更新计划">
                      <p className="mb-3 text-sm font-medium">选择更新计划</p>
                      <div className="grid grid-cols-2 gap-2">
                        {([ ["minutes15", "每 15 分钟"], ["hourly", "每小时整点"], ["daily", "每天"], ["weekly", "每周"], ["monthly", "每月"] ] as const).map(([value, label]) => (
                          <Button key={value} type="button" size="sm" variant={frequency === value ? "secondary" : "outline"} aria-pressed={frequency === value} onClick={() => { setFrequency(value); if (value === "minutes15" || value === "hourly") setScheduleOpen(false) }}>{label}</Button>
                        ))}
                      </div>
                      {(frequency === "daily" || frequency === "weekly" || frequency === "monthly") && (
                        <div className="mt-4 grid gap-3 border-t pt-4">
                          {frequency === "weekly" && <Field label="星期" htmlFor="weekday"><Select value={weekday} onValueChange={setWeekday}><SelectTrigger id="weekday" aria-label="星期"><SelectValue /></SelectTrigger><SelectContent>{["一", "二", "三", "四", "五", "六", "日"].map((day, index) => <SelectItem key={day} value={String(index)}>周{day}</SelectItem>)}</SelectContent></Select></Field>}
                          {frequency === "monthly" && <Field label="每月几号" htmlFor="month-day"><Select value={monthDay} onValueChange={setMonthDay}><SelectTrigger id="month-day" aria-label="每月几号"><SelectValue /></SelectTrigger><SelectContent>{Array.from({ length: 31 }, (_, day) => <SelectItem key={day} value={String(day + 1)}>{day + 1} 日</SelectItem>)}</SelectContent></Select></Field>}
                          <div className="grid grid-cols-2 gap-3">
                            <Field label="小时" htmlFor="schedule-hour"><Select value={scheduleTime.slice(0, 2)} onValueChange={(hour) => setScheduleTime(`${hour}:${scheduleTime.slice(3)}`)}><SelectTrigger id="schedule-hour" aria-label="小时"><SelectValue /></SelectTrigger><SelectContent>{Array.from({ length: 24 }, (_, hour) => <SelectItem key={hour} value={String(hour).padStart(2, "0")}>{String(hour).padStart(2, "0")}</SelectItem>)}</SelectContent></Select></Field>
                            <Field label="分钟" htmlFor="schedule-minute"><Select value={scheduleTime.slice(3)} onValueChange={(minute) => setScheduleTime(`${scheduleTime.slice(0, 2)}:${minute}`)}><SelectTrigger id="schedule-minute" aria-label="分钟"><SelectValue /></SelectTrigger><SelectContent>{Array.from({ length: 60 }, (_, minute) => <SelectItem key={minute} value={String(minute).padStart(2, "0")}>{String(minute).padStart(2, "0")}</SelectItem>)}</SelectContent></Select></Field>
                          </div>
                          <p className="text-xs text-muted-foreground">按服务器时区执行{frequency === "monthly" && "；当月没有所选日期时不执行"}</p>
                          <Button type="button" size="sm" disabled={!validSchedule} onClick={() => setScheduleOpen(false)}>完成</Button>
                        </div>
                      )}
                    </PopoverContent>
                  </Popover>
                </Field>
                )}
                <Field className="sm:col-span-2" label="播放列表地址" htmlFor="url"><Input id="url" name="url" type="url" required placeholder="https://..." defaultValue={editingPodcast?.url} /></Field>
                <Field label="保留最新集数" htmlFor="keep">
                  <Input id="keep" name="keep_latest" type="number" min={1} placeholder="留空则不清理" defaultValue={editingPodcast?.keep_latest ?? ""} aria-describedby="keep-help" />
                  <p id="keep-help" className="mt-1.5 text-xs text-muted-foreground">只保留最近 N 集；留空不清理，首次下载最新 10 集，之后下载检查范围内的全部新内容。</p>
                </Field>
                <Field label="每次扫描数量" htmlFor="page-size">
                  <Input id="page-size" name="page_size" type="number" min={1} defaultValue={editingPodcast?.page_size ?? 20} aria-describedby="page-size-help" />
                  <p id="page-size-help" className="mt-1.5 text-xs text-muted-foreground">YouTube 每轮检查播放列表最新 N 条；留空使用默认值 20。</p>
                </Field>
                <Field label="排序字段" htmlFor="sort-by"><NativeSelect id="sort-by" name="sort_by" defaultValue={editingPodcast?.sort_by ?? "date"}><option value="date">发布时间</option><option value="title">标题</option></NativeSelect></Field>
                <Field label="播放列表顺序" htmlFor="sort-order"><NativeSelect id="sort-order" name="sort_order" defaultValue={editingPodcast?.sort_order ?? "desc"}><option value="desc">新到旧</option><option value="asc">旧到新</option></NativeSelect></Field>
              </div>
              <p className="text-sm text-muted-foreground">定时任务按服务器时区执行。</p>
              <div className="flex justify-end"><Button type="submit" disabled={saving || !validSchedule}>{saving ? <LoaderCircle className="animate-spin" /> : editingPodcast ? <Pencil /> : <Plus />}{editingPodcast ? "保存" : "添加播客"}</Button></div>
            </form>
          </DialogContent>
        </Dialog>
      </main>
    </>
  )
}

function NativeSelect(props: React.ComponentProps<"select">) {
  return <div className="relative"><select className={selectClass} {...props} /><ChevronDown aria-hidden="true" className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /></div>
}

function Field({ label, htmlFor, className, children }: { label: string; htmlFor: string; className?: string; children: React.ReactNode }) {
  return <div className={className}><Label htmlFor={htmlFor}>{label}</Label><div className="mt-2">{children}</div></div>
}
