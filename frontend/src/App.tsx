import { useEffect, useState } from "react"

import { Dashboard } from "@/Dashboard"
import { PodcastDetail } from "@/PodcastDetail"

function podcastFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/admin\/podcasts\/([^/]+)\/?$/)
  if (!match) return null
  try {
    return decodeURIComponent(match[1])
  } catch {
    return null
  }
}

export function App() {
  const [podcastName, setPodcastName] = useState(() => podcastFromPath(window.location.pathname))

  useEffect(() => {
    const updateRoute = () => setPodcastName(podcastFromPath(window.location.pathname))
    window.addEventListener("popstate", updateRoute)
    return () => window.removeEventListener("popstate", updateRoute)
  }, [])

  function openPodcast(name: string) {
    window.history.pushState({}, "", `/admin/podcasts/${encodeURIComponent(name)}`)
    setPodcastName(name)
  }

  function goBack() {
    window.history.pushState({}, "", "/admin")
    setPodcastName(null)
  }

  return podcastName ? (
    <PodcastDetail name={podcastName} goBack={goBack} />
  ) : (
    <Dashboard openPodcast={openPodcast} />
  )
}
