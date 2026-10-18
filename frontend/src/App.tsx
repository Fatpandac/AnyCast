import { useEffect, useState } from "react"

import { Dashboard } from "@/Dashboard"
import { PodcastDetail } from "@/PodcastDetail"
import { SettingsPage } from "@/Settings"
import { Login } from "@/Login"

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
  const [settingsOpen, setSettingsOpen] = useState(() => window.location.pathname === "/admin/settings")

  useEffect(() => {
    const updateRoute = () => {
      setPodcastName(podcastFromPath(window.location.pathname))
      setSettingsOpen(window.location.pathname === "/admin/settings")
    }
    window.addEventListener("popstate", updateRoute)
    return () => window.removeEventListener("popstate", updateRoute)
  }, [])

  function openPodcast(name: string) {
    window.history.pushState({}, "", `/admin/podcasts/${encodeURIComponent(name)}`)
    setPodcastName(name)
  }

  function openSettings() {
    window.history.pushState({}, "", "/admin/settings")
    setSettingsOpen(true)
  }

  function goBack() {
    window.history.pushState({}, "", "/admin")
    setPodcastName(null)
    setSettingsOpen(false)
  }

  return window.location.pathname === "/admin/login" ? (
    <Login />
  ) : settingsOpen ? (
    <SettingsPage goBack={goBack} />
  ) : podcastName ? (
    <PodcastDetail name={podcastName} goBack={goBack} />
  ) : (
    <Dashboard openPodcast={openPodcast} openSettings={openSettings} />
  )
}
