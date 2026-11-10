# Break — 30 秒休息一下 🐱

摸鱼小工具：随机休息建议 + 鱼库（收藏链接）+ 树洞（匿名发帖社区）。

Flask + SQLite 全栈，另附**零后端单文件离线版**（`break-time-single.html`，双击浏览器直接打开，数据存 localStorage）。

---

## 功能

- **随机休息建议**：点一下换一条（喝水、起身、看窗外……）
- **鱼库**：收藏链接（B站、微信读书、任意网址），分类管理
- **树洞**：匿名发帖 + 跟帖 + 点赞 + 搜索 + 排序（最新/热门），GitHub OAuth 登录
- **摸鱼计时浮窗**：可拖拽的计时器，看着自己摸了多久

---

## 快速开始

### 方式一：单文件离线版（零依赖，最快）

直接双击打开 `break-time-single.html`，或用任意浏览器打开。树洞数据存在浏览器 localStorage，内置几条示例帖。

### 方式二：全栈版（有后端，多人共享树洞）

```bash
git clone <你的仓库地址> && cd break-time
pip install -r requirements.txt

# 配置环境变量（GitHub 登录 + session 密钥）
cp .env.example .env   # 然后编辑 .env 填入真实值
# 或者直接 export：
export BREAKTIME_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export GITHUB_CLIENT_ID=你的_id
export GITHUB_CLIENT_SECRET=你的_secret

python app.py           # 默认跑在 http://localhost:5001
```

> 不配置 GitHub OAuth 也能跑：帖子/评论/点赞全功能可用，只是右上角没有「登录 GitHub」按钮（`/auth/github` 会返回 500 提示未配置）。

---

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `BREAKTIME_SECRET_KEY` | 建议 | Flask session 签名密钥；不设则每次启动随机生成（重启后需重新登录） |
| `GITHUB_CLIENT_ID` | 登录需要 | GitHub OAuth App 的 client id |
| `GITHUB_CLIENT_SECRET` | 登录需要 | GitHub OAuth App 的 client secret |
| `GITHUB_REDIRECT_URI` | 否 | 回调地址，默认 `http://localhost:5001/auth/github/callback` |
| `BREAKTIME_DB_PATH` | 否 | SQLite 数据库路径，默认 `breaktime.db` |

---

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/posts` | 帖子列表（支持 `category` / `sort` / `search`） |
| GET | `/api/posts/<id>` | 帖子详情（含评论） |
| POST | `/api/posts` | 发帖 |
| POST | `/api/posts/<id>/comments` | 跟帖 |
| POST | `/api/posts/<id>/like` | 点赞 |
| DELETE | `/api/posts/<id>` | 删帖（**需登录且只能删自己的**） |
| GET | `/api/me` | 当前登录用户 |

---

## 安全设计（重点）

这个项目里最危险的 bug 是「删帖没有权限校验」——任何人调 `DELETE /api/posts/1` 就能删掉别人的帖子。已修复：

1. **删帖权限**：服务端校验「已登录 + 作者是本人」，否则返回 401 / 403。
2. **OAuth state 防 CSRF**：授权请求带随机 `state`，回调时比对。
3. **密钥不硬编码**：`client_secret` / `secret_key` 全部走环境变量，仓库里只有 `.env.example`。
4. **前后端字段对齐**：后端在列表和详情里都返回 `mine` 字段，前端「我的」面板据此显示，不再有「我发的永远为空」的问题。

---

## 架构

```
static/index.html（前端）
   │  fetch 调用 /api/*
   ▼
Flask app.py（后端）
   ├─ SQLite（posts / comments 两张表）
   └─ GitHub OAuth（登录）
```

- `app.py`：全部后端逻辑（路由 + SQLite + OAuth）
- `static/index.html`：完整版前端
- `break-time-single.html`：单文件离线版（无后端）

---

## 我做的取舍

- **SQLite 而非 Postgres**：这个体量（个人小社区）不需要数据库服务器，一个文件就够，也方便别人 clone 即跑。
- **匿名优先**：发帖/评论默认匿名，登录只用于「删自己的帖」，降低使用门槛。
- **保留单文件版**：让「想快速玩玩」的人和「想部署」的人都能用。

---

## 已知限制

- 点赞没有去重，同一个用户可以无限点赞（未做 per-user 去重）。
- 匿名帖无法删除（没有登录身份可校验）。
- 没有分页，帖子多了列表会很长。
- GitHub OAuth 登录后，发帖默认用 GitHub 用户名；未登录发帖走本地昵称。
- 单文件离线版的数据存在 localStorage，换浏览器/清缓存即丢失。

---

## License

[MIT](./LICENSE)
