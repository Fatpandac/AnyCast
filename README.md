# AnyCast
A generator for creating podcasts from Bilibili and YouTube playlists.

## 已实现功能

- 从 `config.yaml` 里的 `podcasts` 列表拉取 Bilibili 或 YouTube 视频
- 仅下载音频（`only_audio`）并落库
- 自动生成 RSS（以播客 `name` 作为路径）

## 管理后台

默认凭据为 `admin / adminadmin`。服务配置中的 `0.0.0.0` 是监听地址，不能作为浏览器访问地址；本机请访问 `http://127.0.0.1:8001/admin`（端口以 `config.yaml` 为准）。首次使用后请立即在后台「设置 → 管理员密码」修改密码（至少 12 位），或通过环境变量设置初始密码：

```bash
export ANYCAST_ADMIN_PASSWORD='请替换为强密码'
# 可选，默认用户名为 admin
export ANYCAST_ADMIN_USERNAME='admin'
uv run anycast
```

后台修改密码后立即生效，无需重启；新密码只以加盐 PBKDF2 哈希保存在本机 `config.yaml` 的 `admin.password_hash`，优先于环境变量。如忘记密码，可停机后手动删除该字段，重启后使用环境变量密码（或默认密码）登录并立即重新设置。请勿将 `config.yaml` 分享给他人。

后台可以查看播客及已下载集数；点击播客名称可查看下载记录、内容简介、来源链接并在线播放或下载音频；也可以添加播客、移除播客配置。更新 YouTube Cookie 后，可在对应播客行点击「立即更新」异步重新拉取，进度和错误可在「设置 → 运行日志」查看；同一播客的更新任务不会并发执行。添加或移除后定时任务会立即同步；移除不会删除下载文件和历史记录。后台写入 `config.yaml` 时会保留配置值，但 YAML 中的手写注释不会保留。

设置页「运行日志」读取应用自行保存的 `logs/anycast-runtime.log`，默认显示最新 100 行，页面打开期间每 3 秒拉取新增内容（不用刷新页面），向上滚动时每次再加载 100 行旧日志。日志包含调度、下载和错误信息，按 10 MiB × 6 个文件轮转，超出容量的旧日志不可再查看；不再读取 `anycast.log`，已有的旧日志也不会自动导入。日志可能包含来源地址等敏感信息，请仅向可信管理员开放后台。

管理界面使用 React、shadcn/ui 和 Tailwind CSS，前端依赖统一由 pnpm 管理。仓库已包含可直接运行的构建产物；修改前端时使用：

```bash
pnpm install
pnpm dev       # 开发服务器，API 默认代理到 127.0.0.1:8001
pnpm test
pnpm build     # 生产文件输出到 src/admin_static
```

管理后台支持 HTTP Basic 密码登录，也可在「设置 → Passkey 登录」填写并保存自己的 HTTPS 域名（例如 `https://example.com`），再用该域名打开后台注册 Passkey。注册前必须修改默认管理员密码。注册第一个 Passkey 后，通过 `/admin/login` 可使用设备验证登录；密码登录始终保留为恢复方式。更换或清空域名会移除已有 Passkey 并使 Passkey 会话失效，需要重新注册。反向代理必须保留原始 `Host` 头，且 Passkey 的注册及登录请求必须来自配置的 HTTPS 域名；多进程部署需要共享挑战存储（当前仅支持单 worker）。请妥善保管 `config.yaml`（其中保存 Passkey 公钥和会话签名密钥）。部署到公网时必须先替换默认密码，并放在 HTTPS 反向代理后，不要通过明文 HTTP 传输密码。使用默认密码时，后台会显示警告；虽然也能编辑 Cookie 文件，但已知默认密码的任何人都可能读取其中的敏感凭据。

## 应用更新

在 Git 源码目录中使用 `uv run anycast` 启动，会由轻量管理进程托管服务。首次安装此功能后，请先手动停止旧服务，再用该命令启动一次。

设置页的「应用更新」跟随固定仓库 `Fatpandac/AnyCast` 的 `main` 分支，使用提交 SHA 标识版本，提交说明展示当前运行提交（不含）到最新 main 提交（含）之间的全部提交，包含 hash、时间和完整消息，最新在前。服务启动后及每小时检查一次，也可点击「检查更新」（一分钟内复用检查结果）。只有发现可快进的新提交时，才提供「更新并重启」，不会自动无人值守安装。安装前会再次核对确认过的 SHA；main 若又有新提交，需要重新检查确认。

一键安装仅支持 macOS/Linux、单 worker、可写且无未提交修改的 main 工作区，并需要 Git 和 uv。正在下载或扫描、分支分叉、本地领先或运行版本与工作树不同，都不会强制覆盖。更新时暂时禁止新下载和配置写入，保留 `config.yaml`、`database.db`、Cookie 文件及已下载音频；使用仓库已提交的前端构建产物，不要求部署机器安装 pnpm。

更新流程会先备份配置和 SQLite 数据库，再停止子进程、快进代码、运行 `uv sync --locked`、重启并核对 HTTP 就绪状态和运行 SHA。失败会尝试恢复旧提交及依赖；恢复失败时请查看服务器终端。管理进程自身的更新日志、状态和私有备份保存在以下目录，不对网页静态服务开放：

```bash
git rev-parse --git-path anycast-updates
# update.log：管理进程日志；state.json：阶段、原提交、目标提交及失败原因
# backups/<operation_id>/：config.yaml 和 database.db 的安装前备份
```

服务短暂断开时，设置页会自动重连并核对目标版本；重连超时不代表安装已经停止，请查看终端或手动检查状态，勿同时操作 Git 或重复启动应用。进程被异常终止后，下次受管启动会拒绝重放旧请求；对已开始的安装尝试安全恢复，遇到本地修改会停止并要求人工处理。

如需人工恢复，先停止管理进程，检查 `git status` 和私有 `state.json` 中的 `previous`、`target`。**不要对有本地修改的工作区执行强制 reset/clean**。确认当前 HEAD、原提交及备份后自行恢复代码，执行 `uv sync --locked`，再运行 `uv run anycast`；涉及数据恢复时先另行备份当前数据库。

管理进程在升级期间保持运行，因此更新协议须向后兼容；涉及管理进程自身逻辑的变更，需要手动重启一次 `uv run anycast` 才生效。缺少 Git、uv 或在不支持的系统上启动时，会回退到普通服务模式，并在更新区说明安装不可用。

自动回退不能保证修复网络或依赖安装故障，也不支持不可逆的数据库/配置迁移；main 上的后续变更须保持向后兼容。更新相当于授权可信 main 代码在本机执行，请保护管理员账号及仓库权限。Docker、Windows、多 worker 或非 Git 安装应由外部部署工具更新；直接运行 `uv run src/main.py` 仍可使用后台，但不能在页面安装更新。

## API

- `GET /podcasts`：获取所有配置中的播客
- `GET /podcasts/{name}`：获取单个播客信息和 RSS 链接
- `GET /rss/{name}`：订阅该播客 RSS
- `GET /media/{name}/{file_name}`：获取生成后的音频文件

例如 RSS 订阅：
`https://<host>:<port>/rss/anycast1`

## Neovim + Pyright

如果看到 `apscheduler` 的 `reportMissingImports`，先确认使用项目虚拟环境：

```bash
uv sync --group dev
uv run pyright src
```

项目已新增 `pyrightconfig.json`，会把解释器定位到本仓库 `.venv` 并把 `src` 作为源码搜索路径。修改完依赖或配置后，重启 Neovim 的 Pyright LSP 即可刷新。

## 类型检查 Hook

本项目已在 `pre-commit` 中加入提交前类型检查：

```bash
uv sync --group dev
pre-commit install
```

之后每次 `git commit` 会执行 `uv run --with pyright pyright src`，即在提交前进行 Python 类型检查。

## 运行

需要 Python 3.11 或更新版本。YouTube 解析和下载调用外部 `yt-dlp`，不再安装项目内的 `yt-dlp` / `yt-dlp-ejs` Python 依赖。执行前会检查可执行文件及版本（最低 `2026.10.26`），日志记录实际路径和版本；缺失、版本无法识别或过旧会明确报错，不会回退到 Python 库。

macOS 可通过 Homebrew 安装 YouTube 所需工具（`ffmpeg` / `ffprobe` 用于提取音频）：

```bash
brew install yt-dlp ffmpeg node
# yt-dlp 可独立升级，无需更新项目或重启服务
brew upgrade yt-dlp
```

Linux 或其他系统请安装外部 `yt-dlp`、`ffmpeg`（含 `ffprobe`）和 Node.js，确保它们在服务的 `PATH` 中。外部 yt-dlp 的 EJS 组件及运行环境由它自己的安装方式管理，不由项目锁文件管理。若安装的是不包含 EJS 的官方可执行文件，请按 yt-dlp 官方文档配置 EJS。

可在 `config.yaml` 的现有 `youtube` 节点添加：

```yaml
youtube:
  executable: yt-dlp  # 默认从 PATH 查找；建议多环境部署时明确指定外部命令的绝对路径
  auto_update: false
  # cookies_file: /path/to/cookies.txt
```

`auto_update: true` 会在首次使用及之后最多每 24 小时调用一次官方 `yt-dlp --update`（仅当前进程内无 yt-dlp 任务时尝试；重启后重新计时），然后重新检查版本。升级失败会记录警告：当前版本仍兼容时继续，否则停止本次操作。默认关闭，不会自动提权或运行任意升级脚本。**Homebrew、pip 等包管理器安装通常不支持官方自更新**，请使用安装时的工具升级，例如 `brew upgrade yt-dlp`；要使用应用内自动升级，请使用支持 `--update` 且当前用户有写权限的官方独立可执行文件。配置只在 YAML 中提供，后台保存 Cookie 设置会保留这些字段。

自动升级失败还会在已登录的 admin 页面内容区顶部显示紧凑状态卡；点击「查看详情」可查看官方错误和手动升级建议，页面每 30 秒刷新状态。普通下载成功不会清除升级失败提醒；下一次自动升级成功后清除。提醒只保存在当前服务进程内，重启后清空，历史详情仍可查运行日志。读取状态失败会明确提示，且不会覆盖已知的升级失败原因。

迁移后首次执行 `uv sync --locked` 会清理旧虚拟环境中的 yt-dlp，因此请先安装好外部版本，避免 PATH 仍指向即将移除的 `.venv/bin/yt-dlp`。项目更新不会升级或降级外部 yt-dlp，项目回退也不会回退它。

播客级 `yt_dlp_options` 仍使用常用 Python API 风格键名，包括 `extractor_args`、`proxy`、`format`、`cookiefile`、`cookiesfrombrowser`、`http_headers`、`js_runtimes`、重试/超时/限速参数，以及 `FFmpegExtractAudio` 后处理。未知参数或不支持的参数类型会报错，不再承诺支持所有 Python API 选项。Cookie 文件仍为每个任务复制隔离；下载错误或缺失分片不会作为成功写入数据库。

```bash
uv sync --group dev
uv run anycast
```

如果只需要运行测试：

```bash
uv run pytest --cov=src --cov-report=html --cov-fail-under=90
```
