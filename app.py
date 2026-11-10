"""Break — 30秒休息一下（Flask 后端）。

安全说明：
- GitHub OAuth 的 client_id / client_secret、Flask session 密钥都从环境变量读取，
  不硬编码在代码里。
- OAuth 授权带上随机 `state` 参数防 CSRF。
- 删帖需要登录且只能删自己的帖子（服务端校验，不能只靠前端）。
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime

from flask import Flask, jsonify, redirect, request, send_from_directory, session
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

# ===== 配置（从环境变量读取，缺省时给出明确报错，不硬编码密钥）=====

app.secret_key = os.environ.get("BREAKTIME_SECRET_KEY")
if not app.secret_key:
    # 开发环境兜底：随机生成。生产环境务必设置 BREAKTIME_SECRET_KEY。
    # 随机密钥意味着每次重启 session 失效（需要重新登录），但绝不硬编码。
    app.secret_key = secrets.token_hex(32)

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.environ.get(
    "GITHUB_REDIRECT_URI", "http://localhost:5001/auth/github/callback"
)

DB_PATH = os.environ.get("BREAKTIME_DB_PATH", "breaktime.db")


def _github_configured() -> bool:
    return bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '摸鱼',
            likes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES posts(id)
        )
        """
    )
    # 兼容旧数据库：如果没有 likes 列就加上
    try:
        conn.execute("SELECT likes FROM posts LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE posts ADD COLUMN likes INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


init_db()


# ===== GitHub OAuth 路由 =====


@app.route("/auth/github")
def auth_github():
    if not _github_configured():
        return jsonify({"error": "GitHub 登录未配置（缺 GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET）"}), 500

    # 随机 state 防 CSRF：存进 session，回调时比对
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    params = urllib.parse.urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "state": state,
    })
    github_auth_url = f"https://github.com/login/oauth/authorize?{params}"
    return redirect(github_auth_url)


@app.route("/auth/github/callback")
def auth_github_callback():
    code = request.args.get("code")
    if not code:
        return redirect("/?login_failed=1")

    # 校验 state，防 CSRF
    returned_state = request.args.get("state")
    expected_state = session.pop("oauth_state", None)
    if not returned_state or returned_state != expected_state:
        return redirect("/?login_failed=csrf")

    # 用 code 换 access_token
    token_url = "https://github.com/login/oauth/access_token"
    data = json.dumps({
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": GITHUB_REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(
        token_url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    token_data = json.loads(resp.read())
    access_token = token_data.get("access_token")
    if not access_token:
        return redirect("/?login_failed=1")

    # 用 access_token 获取用户信息
    user_url = "https://api.github.com/user"
    req2 = urllib.request.Request(
        user_url,
        headers={"Authorization": "token " + access_token, "Accept": "application/json"},
    )
    resp2 = urllib.request.urlopen(req2)
    user_data = json.loads(resp2.read())

    session["user"] = {
        "login": user_data.get("login"),
        "avatar_url": user_data.get("avatar_url"),
        "name": user_data.get("name") or user_data.get("login"),
    }
    return redirect("/")


@app.route("/api/me")
def get_me():
    user = session.get("user")
    if user:
        return jsonify({"logged_in": True, "user": user})
    return jsonify({"logged_in": False})


@app.route("/auth/logout")
def auth_logout():
    session.pop("user", None)
    return redirect("/")


# ===== 工具 =====


def _current_user() -> dict | None:
    return session.get("user")


def _post_to_dict(p, current_user=None):
    """把一行 posts 转成 dict，并标注是否「我发的」（供前端「我的」面板使用）。"""
    d = dict(p)
    d["mine"] = bool(current_user and d["author"] == current_user.get("name"))
    return d


# ===== API 路由 =====


@app.route("/api/posts", methods=["GET"])
def get_posts():
    category = request.args.get("category")
    sort = request.args.get("sort", "new")
    search = request.args.get("search", "").strip()
    conn = get_db()
    query = "SELECT * FROM posts WHERE 1=1"
    params = []
    if category and category != "全部":
        query += " AND category = ?"
        params.append(category)
    if search:
        query += " AND title LIKE ?"
        params.append("%" + search + "%")
    if sort == "hot":
        query += " ORDER BY likes DESC, id DESC"
    else:
        query += " ORDER BY id DESC"
    posts = conn.execute(query, params).fetchall()
    current_user = _current_user()
    result = []
    for p in posts:
        d = _post_to_dict(p, current_user)
        comment_count = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE post_id = ?", (d["id"],)
        ).fetchone()[0]
        d["comment_count"] = comment_count
        result.append(d)
    conn.close()
    return jsonify(result)


@app.route("/api/posts/<int:post_id>", methods=["GET"])
def get_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({"error": "帖子不存在"}), 404
    post = _post_to_dict(post, _current_user())
    comments = conn.execute(
        "SELECT * FROM comments WHERE post_id = ? ORDER BY id ASC", (post_id,)
    ).fetchall()
    post["comments"] = [dict(c) for c in comments]
    conn.close()
    return jsonify(post)


@app.route("/api/posts", methods=["POST"])
def create_post():
    data = request.json or {}
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    author = data.get("author", "匿名").strip()
    category = data.get("category", "摸鱼").strip()
    if not title or not content:
        return jsonify({"error": "标题和内容不能为空"}), 400
    now = datetime.now().isoformat()
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO posts (title, content, author, category, created_at) VALUES (?, ?, ?, ?, ?)",
        (title, content, author, category, now),
    )
    conn.commit()
    post_id = cursor.lastrowid
    conn.close()
    return jsonify({"id": post_id, "message": "发帖成功"}), 201


@app.route("/api/posts/<int:post_id>/comments", methods=["POST"])
def create_comment(post_id):
    data = request.json or {}
    content = data.get("content", "").strip()
    author = data.get("author", "匿名").strip()
    if not content:
        return jsonify({"error": "评论内容不能为空"}), 400
    now = datetime.now().isoformat()
    conn = get_db()
    post = conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({"error": "帖子不存在"}), 404
    conn.execute(
        "INSERT INTO comments (post_id, author, content, created_at) VALUES (?, ?, ?, ?)",
        (post_id, author, content, now),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "评论成功"}), 201


@app.route("/api/posts/<int:post_id>", methods=["DELETE"])
def delete_post(post_id):
    # 权限校验：必须登录，且只能删自己的帖子（服务端校验，不能只靠前端）
    user = _current_user()
    if not user:
        return jsonify({"error": "请先登录"}), 401

    conn = get_db()
    post = conn.execute("SELECT id, author FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({"error": "帖子不存在"}), 404

    if post["author"] != user.get("name"):
        conn.close()
        return jsonify({"error": "只能删除自己的帖子"}), 403

    conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "删除成功"})


@app.route("/api/posts/<int:post_id>/like", methods=["POST"])
def like_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT id, likes FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({"error": "帖子不存在"}), 404
    new_likes = post["likes"] + 1
    conn.execute("UPDATE posts SET likes = ? WHERE id = ?", (new_likes, post_id))
    conn.commit()
    conn.close()
    return jsonify({"likes": new_likes})


@app.route("/api/categories", methods=["GET"])
def get_categories():
    return jsonify(["全部", "摸鱼", "经验交流", "技术讨论", "灌水"])


# ===== 前端页面 =====


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
