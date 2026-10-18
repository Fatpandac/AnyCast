import { useState } from "react"
import { loginPasskey } from "@/passkeys"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

export function Login() {
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function login() {
    setError("")
    setBusy(true)
    try {
      await loginPasskey()
      window.location.assign("/admin")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Passkey 登录失败")
      setBusy(false)
    }
  }

  return <main className="mx-auto grid min-h-screen max-w-sm content-center gap-5 px-4">
    <h1 className="text-2xl font-semibold">AnyCast 管理后台</h1>
    {error && <Alert role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
    <Button disabled={busy || !("credentials" in navigator)} onClick={() => void login()}>使用 Passkey 登录</Button>
    <a href="/admin/basic" className="text-center text-sm underline">使用密码登录</a>
  </main>
}
