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
uv run src/main.py
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

YouTube 音频提取依赖 `ffmpeg`。macOS 可通过 Homebrew 安装：

```bash
brew install ffmpeg
```

Linux 或其他系统请使用对应包管理器安装 `ffmpeg`，并确保 `ffmpeg` 在 `PATH` 中。

```bash
uv sync --group dev
uv run src/main.py
```

如果只需要运行测试：

```bash
uv run pytest --cov=src --cov-report=html --cov-fail-under=90
```
