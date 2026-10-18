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

后台可以查看播客及已下载集数；点击播客名称可查看下载记录、内容简介、来源链接并在线播放或下载音频；也可以添加播客、移除播客配置。添加或移除后定时任务会立即同步；移除不会删除下载文件和历史记录。后台写入 `config.yaml` 时会保留配置值，但 YAML 中的手写注释不会保留。

管理界面使用 React、shadcn/ui 和 Tailwind CSS，前端依赖统一由 pnpm 管理。仓库已包含可直接运行的构建产物；修改前端时使用：

```bash
pnpm install
pnpm dev       # 开发服务器，API 默认代理到 127.0.0.1:8001
pnpm test
pnpm build     # 生产文件输出到 src/admin_static
```

管理后台使用 HTTP Basic Authentication。部署到公网时必须先替换默认密码，并放在 HTTPS 反向代理后，不要通过明文 HTTP 传输密码。使用默认密码时，后台会显示警告；虽然也能编辑 Cookie 文件，但已知默认密码的任何人都可能读取其中的敏感凭据。

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
