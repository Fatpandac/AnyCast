export type Frequency = "minutes15" | "hourly" | "daily" | "weekly" | "monthly"

const weekdays = ["一", "二", "三", "四", "五", "六", "日"]

export function scheduleCron(frequency: Frequency, time: string, weekday: string, monthDay: string): string {
  const [hour, minute] = time.split(":").map(Number)
  switch (frequency) {
    case "minutes15": return "*/15 * * * *"
    case "hourly": return "0 * * * *"
    case "daily": return `${minute} ${hour} * * *`
    case "weekly": return `${minute} ${hour} * * ${weekday}`
    case "monthly": return `${minute} ${hour} ${monthDay} * *`
  }
}

export function describeSchedule(cron: string): string {
  const custom = "自定义计划（请查看配置）"
  const fields = cron.trim().split(/\s+/)
  if (fields.length !== 5) return custom
  const [minute, hour, day, month, weekday] = fields
  if (month !== "*") return custom
  if (hour === "*" && day === "*" && weekday === "*") {
    if (minute === "*") return "每分钟"
    const step = /^\*\/(\d+)$/.exec(minute)
    if (step && Number(step[1]) >= 1 && Number(step[1]) <= 59) return step[1] === "1" ? "每分钟" : `每 ${step[1]} 分钟`
    if (minute === "0") return "每小时整点"
    if (/^(?:[1-9]|[1-5]\d)$/.test(minute)) return `每小时第 ${Number(minute)} 分钟`
  }
  if (minute === "0" && day === "*" && weekday === "*") {
    const step = /^\*\/(\d+)$/.exec(hour)
    if (step && Number(step[1]) >= 1 && Number(step[1]) <= 23) return step[1] === "1" ? "每小时整点" : `每 ${step[1]} 小时整点`
  }
  if (!/^(?:[01]?\d|2[0-3])$/.test(hour) || !/^(?:[0-9]|[1-5][0-9])$/.test(minute)) return custom
  const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`
  if (day === "*" && weekday === "*") return `每天 ${time}`
  if (day === "*" && /^[0-6]$/.test(weekday)) return `每周${weekdays[Number(weekday)]} ${time}`
  if (weekday === "*" && /^([1-9]|[12]\d|3[01])$/.test(day)) return `每月 ${Number(day)} 日 ${time}`
  return custom
}
