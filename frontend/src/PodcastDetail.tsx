import { useEffect, useState } from "react"
import { ArrowLeft, CalendarDays, Download, ExternalLink, FileAudio, LoaderCircle } from "lucide-react"

import { getPodcast, type Episode, type Podcast } from "@/api"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

export function PodcastDetail({ name, goBack }: { name: string; goBack: () => void }) {
  const [podcast, setPodcast] = useState<Podcast | null>(null)
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [error, setError] = useState("")

  useEffect(() => {
    void getPodcast(name)
      .then((data) => {
        setPodcast(data.podcast)
        setEpisodes(data.episodes)
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"))
  }, [name])

  return (
    <>
      <header className="border-b bg-card">
        <div className="mx-auto max-w-6xl px-4 py-5 sm:px-6">
          <Button variant="ghost" size="sm" className="-ml-3 mb-3 text-muted-foreground" onClick={goBack}><ArrowLeft />返回管理后台</Button>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{podcast?.name || name}</h1>
            {podcast && <Badge>共 {episodes.length} 集</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">下载记录与内容详情</p>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-4 px-4 py-6 sm:px-6">
        {error ? (
          <Alert className="border-destructive/40 bg-destructive/5 text-destructive"><AlertTitle>加载失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>
        ) : !podcast ? (
          <div className="flex justify-center py-20 text-muted-foreground"><LoaderCircle className="size-6 animate-spin" /></div>
        ) : episodes.length === 0 ? (
          <Card><CardContent className="py-16 text-center text-sm text-muted-foreground">暂无下载记录。</CardContent></Card>
        ) : (
          episodes.map((episode) => <EpisodeCard key={episode.episode_id} podcastName={name} episode={episode} />)
        )}
      </main>
    </>
  )
}

function EpisodeCard({ podcastName, episode }: { podcastName: string; episode: Episode }) {
  const mediaUrl = `/media/${encodeURIComponent(podcastName)}/${encodeURIComponent(episode.file_name)}`
  const sourceUrl = safeHttpUrl(episode.source_url)
  const coverUrl = episode.cover_image_url ? safeHttpUrl(episode.cover_image_url) : null

  return (
    <Card className="overflow-hidden">
      <CardContent className="grid gap-5 p-4 sm:grid-cols-[180px_minmax(0,1fr)] sm:p-5">
        {coverUrl ? (
          <img className="aspect-video w-full rounded-lg bg-muted object-cover sm:w-[180px]" src={coverUrl} alt="" loading="lazy" />
        ) : (
          <div className="flex aspect-video w-full items-center justify-center rounded-lg bg-muted text-muted-foreground sm:w-[180px]"><FileAudio className="size-8" /></div>
        )}
        <div className="min-w-0">
          <h2 className="text-lg font-semibold leading-snug">{episode.title || episode.file_name}</h2>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-3.5" />发布于 {formatDate(episode.published_at)}</span>
            <span>下载于 {formatDate(episode.created_at)}</span>
          </div>
          <p className="mt-2 truncate text-xs text-muted-foreground" title={episode.file_name}>{episode.file_name}</p>
          <audio className="mt-4 h-10 w-full max-w-xl" controls preload="none" src={mediaUrl}>浏览器不支持音频播放。</audio>
          <div className="mt-3 flex flex-wrap gap-2">
            {sourceUrl && <Button asChild size="sm" variant="outline"><a href={sourceUrl} target="_blank" rel="noreferrer"><ExternalLink />查看原内容</a></Button>}
            <Button asChild size="sm" variant="outline"><a href={mediaUrl} download><Download />下载文件</a></Button>
          </div>
          {episode.description && <p className="mt-4 border-t pt-4 text-sm leading-6 text-muted-foreground whitespace-pre-wrap">{episode.description}</p>}
        </div>
      </CardContent>
    </Card>
  )
}

function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === "http:" || url.protocol === "https:" ? value : null
  } catch {
    return null
  }
}

function formatDate(value: string | null): string {
  if (!value) return "未知"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN")
}
