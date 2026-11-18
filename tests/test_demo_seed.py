import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECK = """
import json
from sqlalchemy import func, select
import deploy_start
from app.database import SessionLocal
from app.ai.tasks import follow_up_plan
from app.models import Comment, Island, Notification, Post, User

deploy_start.seed_if_empty()
with SessionLocal() as db:
    demo_post = db.scalar(select(Post).where(Post.title == "회의 때 의견을 말하기가 어려워요"))
    demo_root = db.scalar(select(Comment).where(Comment.post_id == demo_post.id, Comment.is_ai, Comment.parent_id.is_(None)))
    per_island = {}
    for island in db.scalars(select(Island)):
        authors = db.scalar(
            select(func.count(func.distinct(Post.user_id)))
            .join(User, User.id == Post.user_id)
            .where(Post.island_id == island.id, Post.visibility == "public", Post.status == "published",
                   User.deleted_at.is_(None))
        )
        per_island[island.job or "common"] = authors
    print(json.dumps({
        "islands": per_island,
        "characters": len(set(db.scalars(select(User.character).where(User.deleted_at.is_(None))))),
        "ai_follow_ups": db.scalar(select(func.count()).select_from(Comment).where(Comment.is_ai, Comment.parent_id.is_not(None))),
        "thanked": db.scalar(select(func.count()).select_from(Comment).where(Comment.thanked_at.is_not(None))),
        "invites": db.scalar(select(func.count()).select_from(Notification).where(Notification.type == "invite")),
        "presenter_ai_ready": follow_up_plan(db, demo_post, demo_root)[0],
    }))
"""


def test_demo_seed_fills_every_island_with_worried_neighbors():
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite:///{Path(tmp) / 'seed.db'}",
            "AI_PROVIDER": "local",
            "DEMO_JOB": "개발",
            "PYTHONIOENCODING": "utf-8",
        }
        env.pop("UPSTAGE_API_KEY", None)
        env.pop("GEMINI_API_KEY", None)
        result = subprocess.run(
            [sys.executable, "-c", CHECK], cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=300,
        )
    assert result.returncode == 0, result.stderr
    import json
    stats = json.loads(result.stdout.strip().splitlines()[-1])

    assert stats["islands"]["개발"] >= 15
    assert stats["islands"]["디자인"] >= 8
    assert stats["islands"]["영업"] >= 7
    assert stats["islands"]["common"] >= 12
    assert stats["characters"] == 13
    assert stats["ai_follow_ups"] >= 1
    assert stats["thanked"] >= 2
    assert stats["invites"] >= 2
    assert stats["presenter_ai_ready"] is True
