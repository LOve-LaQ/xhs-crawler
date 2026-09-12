from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import websockets.sync.client as ws_client

from .models import FeedNote, normalize_feed

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_RELATIVE_PATH = "scripts/cli.py"


class XhsAdapterError(RuntimeError):
    pass


def build_cli_command(*args: str) -> list[str]:
    return [sys.executable, CLI_RELATIVE_PATH, *args]


class XhsCliAdapter:
    def __init__(
        self,
        *,
        timeout: int = 120,
        comment_timeout: int = 180,
        bridge_url: str = "ws://localhost:9333",
    ) -> None:
        self.timeout = timeout
        self.comment_timeout = comment_timeout
        self.bridge_url = bridge_url

    def run_json(self, *args: str, timeout: int | None = None) -> dict[str, Any]:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                build_cli_command(*args),
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            raise XhsAdapterError(f"自动化操作超时（{self.timeout} 秒）") from exc
        except OSError as exc:
            raise XhsAdapterError(f"无法启动 Python 自动化脚本: {exc}") from exc

        try:
            payload = json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            detail = result.stderr.strip() or result.stdout.strip() or "没有返回 JSON"
            raise XhsAdapterError(f"自动化脚本返回格式错误: {detail[:300]}") from exc

        if result.returncode != 0 or payload.get("success") is False or payload.get("error"):
            message = payload.get("error") or payload.get("message") or result.stderr.strip()
            raise XhsAdapterError(message or "自动化操作失败")
        return payload

    def search_feeds(
        self,
        keyword: str,
        *,
        sort_by: str = "最多点赞",
        note_type: str = "",
        publish_time: str = "",
    ) -> list[FeedNote]:
        args = ["search-feeds", "--keyword", keyword]
        if sort_by:
            args.extend(["--sort-by", sort_by])
        if note_type:
            args.extend(["--note-type", note_type])
        if publish_time:
            args.extend(["--publish-time", publish_time])
        payload = self.run_json(*args)
        return [normalize_feed(item) for item in payload.get("feeds", [])]

    def get_feed_detail(
        self,
        note: FeedNote,
        *,
        load_all_comments: bool = False,
        max_comment_items: int = 0,
    ) -> FeedNote:
        args = [
            "get-feed-detail",
            "--feed-id",
            note.note_id,
            "--xsec-token",
            note.xsec_token,
        ]
        if load_all_comments:
            args.append("--load-all-comments")
        if max_comment_items > 0:
            args.extend(["--max-comment-items", str(max_comment_items)])
        detail = self.run_json(*args, timeout=self.comment_timeout)
        normalized = normalize_feed(detail)
        normalized.xsec_token = note.xsec_token
        normalized.raw = {**note.raw, **detail}
        return normalized

    def locate_comment(
        self,
        note: FeedNote,
        *,
        comment_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        args = [
            "locate-comment",
            "--feed-id",
            note.note_id,
            "--xsec-token",
            note.xsec_token,
        ]
        if comment_id:
            args.extend(["--comment-id", comment_id])
        if user_id:
            args.extend(["--user-id", user_id])
        return self.run_json(*args)

    def bridge_status(self) -> dict[str, bool]:
        try:
            with ws_client.connect(self.bridge_url, open_timeout=0.8, close_timeout=0.2) as ws:
                ws.send(json.dumps({"role": "cli", "method": "ping_server"}))
                payload = json.loads(ws.recv(timeout=1.2))
            result = payload.get("result", {})
            return {
                "server": "result" in payload,
                "extension": bool(result.get("extension_connected")),
            }
        except Exception:
            return {"server": False, "extension": False}
