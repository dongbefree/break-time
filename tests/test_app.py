"""Tests for Break-time backend: 权限校验 + 核心 API。

重点覆盖之前最危险的 bug：删帖无权限校验。
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ["BREAKTIME_SECRET_KEY"] = "test-secret"


@pytest.fixture
def client(monkeypatch):
    # 用 mkdtemp 而非 pytest 的 tmp_path（后者在沙箱下偶发 EEXIST）
    tmpdir = tempfile.mkdtemp()
    db = os.path.join(tmpdir, "test.db")
    monkeypatch.setenv("BREAKTIME_DB_PATH", db)
    monkeypatch.setenv("BREAKTIME_SECRET_KEY", "test-secret")

    import importlib
    import app as app_module
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def _create_post(client, title="测试帖", content="内容", author="张三", category="摸鱼"):
    return client.post(
        "/api/posts",
        json={"title": title, "content": content, "author": author, "category": category},
    )


def test_create_and_list(client):
    resp = _create_post(client)
    assert resp.status_code == 201
    post_id = resp.get_json()["id"]

    resp = client.get("/api/posts")
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["id"] == post_id
    assert data[0]["title"] == "测试帖"
    assert data[0]["mine"] is False  # 未登录，不标注 mine


def test_create_empty_rejected(client):
    resp = _create_post(client, title="", content="")
    assert resp.status_code == 400


def test_comment(client):
    _create_post(client)
    post_id = client.get("/api/posts").get_json()[0]["id"]

    resp = client.post(f"/api/posts/{post_id}/comments", json={"content": "沙发", "author": "李四"})
    assert resp.status_code == 201

    detail = client.get(f"/api/posts/{post_id}").get_json()
    assert len(detail["comments"]) == 1
    assert detail["comments"][0]["content"] == "沙发"


def test_like(client):
    _create_post(client)
    post_id = client.get("/api/posts").get_json()[0]["id"]

    resp = client.post(f"/api/posts/{post_id}/like")
    assert resp.get_json()["likes"] == 1


def test_delete_requires_login(client):
    """核心：未登录不能删帖（原来的 bug 是任何人都能删）。"""
    _create_post(client)
    post_id = client.get("/api/posts").get_json()[0]["id"]

    resp = client.delete(f"/api/posts/{post_id}")
    assert resp.status_code == 401
    # 帖子还在
    assert client.get("/api/posts").get_json()[0]["id"] == post_id


def test_delete_own_post_requires_matching_author(client):
    """已登录但只能删「自己的」帖——作者名必须匹配。"""
    _create_post(client, author="张三")
    post_id = client.get("/api/posts").get_json()[0]["id"]

    # 模拟登录用户「李四」，尝试删「张三」的帖 → 403
    with client.session_transaction() as sess:
        sess["user"] = {"login": "lisi", "name": "李四"}

    resp = client.delete(f"/api/posts/{post_id}")
    assert resp.status_code == 403
    assert client.get("/api/posts").get_json()[0]["id"] == post_id


def test_delete_own_post_succeeds(client):
    """作者本人登录后可以删自己的帖。"""
    _create_post(client, author="张三")
    post_id = client.get("/api/posts").get_json()[0]["id"]

    with client.session_transaction() as sess:
        sess["user"] = {"login": "zhangsan", "name": "张三"}

    resp = client.delete(f"/api/posts/{post_id}")
    assert resp.status_code == 200
    # 帖子没了
    assert client.get("/api/posts").get_json() == []


def test_mine_field_marked_when_logged_in(client):
    """登录后，自己的帖子会被标注 mine=True。"""
    _create_post(client, author="张三")

    with client.session_transaction() as sess:
        sess["user"] = {"login": "zhangsan", "name": "张三"}

    data = client.get("/api/posts").get_json()
    assert data[0]["mine"] is True


def test_search_and_sort(client):
    _create_post(client, title="苹果手机", author="A")
    _create_post(client, title="香蕉好吃", author="B")

    # 搜索
    data = client.get("/api/posts?search=苹果").get_json()
    assert len(data) == 1
    assert data[0]["title"] == "苹果手机"

    # 点赞让「香蕉」变热门
    post2 = client.get("/api/posts?search=香蕉").get_json()[0]
    client.post(f"/api/posts/{post2['id']}/like")

    hot = client.get("/api/posts?sort=hot").get_json()
    assert hot[0]["title"] == "香蕉好吃"


def test_github_auth_unconfigured_returns_500(client):
    """未配置 GitHub OAuth 时，/auth/github 应返回明确的 500 提示。"""
    resp = client.get("/auth/github")
    assert resp.status_code == 500
