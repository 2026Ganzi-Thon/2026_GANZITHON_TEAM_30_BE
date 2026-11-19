"""고민 작성·수정·삭제 (B 담당). 조회·댓글·공감은 A의 app/routers/posts.py.

흐름: 검사(check_text) → 저장 → [백그라운드] 임베딩 → AI 첫 댓글
- 개인정보·회사명·욕설이 있으면 422로 반려하고 저장하지 않는다.
- 위기 신호는 막지 않고 게시한 뒤 응답에 crisis_support(109, 1577-0199)를 담는다.
- 나만 보기 글은 본인만 보므로 반려하지 않고, 위기 신호만 확인한다.
"""
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.ai import CRISIS_SUPPORT, CheckResult, check_text
from app.ai.tasks import sync_post
from app.config import COMFORT_TYPES, POST_CONTENT_MAX, POST_TITLE_MAX, TOPICS
from app.database import get_db
from app.deps import get_current_user
from app.models import Post, User
from app.queries import get_accessible_island
from app.ratelimit import limit_user
from app.schemas import CrisisSupport

router = APIRouter(prefix="/posts", tags=["posts (write)"])

Visibility = Literal["public", "private"]


# ---------- 요청·응답 형식 ----------

def _strip_required(v: str | None, label: str) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError(f"{label}을(를) 입력해 주세요")
    return v


def _topic(v: str | None) -> str | None:
    if v is not None and v not in TOPICS:
        raise ValueError(f"주제는 {TOPICS} 중 하나여야 합니다")
    return v


def _comfort(v: str | None) -> str | None:
    if v is not None and v not in COMFORT_TYPES:
        raise ValueError(f"위로 방식은 {list(COMFORT_TYPES)} 중 하나여야 합니다")
    return v


class PostCreate(BaseModel):
    island_id: int
    topic: str
    title: str = Field(min_length=1, max_length=POST_TITLE_MAX)
    content: str = Field(min_length=1, max_length=POST_CONTENT_MAX)
    comfort_type: str
    visibility: Visibility = "public"
    show_years: bool = False  # 연차 공개 여부 (가입 때 연차를 안 넣었으면 무시)
    map_x: float | None = Field(default=None, ge=0, le=100, description="글을 쓴 지도 위 가로 위치(%)")
    map_y: float | None = Field(default=None, ge=0, le=100, description="글을 쓴 지도 위 세로 위치(%)")

    _title = field_validator("title")(lambda v: _strip_required(v, "제목"))
    _content = field_validator("content")(lambda v: _strip_required(v, "내용"))
    _check_topic = field_validator("topic")(_topic)
    _check_comfort = field_validator("comfort_type")(_comfort)


class PostUpdate(BaseModel):
    """바꿀 필드만 보낸다. 섬은 바꿀 수 없다."""
    topic: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=POST_TITLE_MAX)
    content: str | None = Field(default=None, min_length=1, max_length=POST_CONTENT_MAX)
    comfort_type: str | None = None
    visibility: Visibility | None = None
    show_years: bool | None = None

    _title = field_validator("title")(lambda v: _strip_required(v, "제목"))
    _content = field_validator("content")(lambda v: _strip_required(v, "내용"))
    _check_topic = field_validator("topic")(_topic)
    _check_comfort = field_validator("comfort_type")(_comfort)


class PostWriteOut(BaseModel):
    id: int
    island_id: int
    visibility: str
    status: str
    crisis_support: CrisisSupport | None  # 위기 신호가 있을 때만 → FE에서 지원 정보 팝업


# ---------- 공통 ----------

def _check_post(title: str, content: str, visibility: str) -> CheckResult:
    """검사 후 반려 대상이면 422. 반려 응답 detail은 댓글 API와 같은 reason·suggestion에 code·issues를 더한 형태."""
    result = check_text(f"{title}\n{content}", kind="post")
    if visibility == "public" and not result.ok:
        raise HTTPException(
            422,
            {
                "code": "NEED_EDIT",
                "message": "공개 전에 한 번만 고쳐 주세요.",
                "reason": result.reason,
                "suggestion": result.suggestion,
                "issues": result.issues_dict(),
            },
        )
    return result


def _out(post: Post, crisis: bool) -> PostWriteOut:
    return PostWriteOut(
        id=post.id,
        island_id=post.island_id,
        visibility=post.visibility,
        status=post.status,
        crisis_support=CRISIS_SUPPORT if crisis else None,
    )


def _get_my_post(db: Session, post_id: int, me: User) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "고민글을 찾을 수 없습니다.")
    if post.user_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "내 고민글만 수정·삭제할 수 있습니다")
    return post


# ---------- API ----------

class PostCheckIn(BaseModel):
    title: str = Field(default="", max_length=POST_TITLE_MAX)
    content: str = Field(default="", max_length=POST_CONTENT_MAX)


class PostCheckOut(BaseModel):
    ok: bool  # false면 공개 게시 시 422 NEED_EDIT로 반려될 내용
    reason: str | None
    suggestion: str | None
    issues: list[dict]  # [{type, text, start, end, guide}] — start/end는 "제목+줄바꿈+본문" 기준 위치
    crisis: bool  # 위기 신호 (막지 않고 게시 후 상담 안내)


@router.post("/check", response_model=PostCheckOut, dependencies=[limit_user("post-check", 30, 600)])
def check_post(body: PostCheckIn, me: User = Depends(get_current_user)):
    """게시하지 않고 검사만 한다. FE의 '게시 전 AI 점검' 화면에서 결과를 미리 보여 줄 때 쓴다.
    실제 게시(POST/PATCH)에서도 같은 검사를 다시 하므로, 이 결과를 건너뛰어도 걸러진다."""
    result = check_text(body.title + "\n" + body.content, kind="post")
    return PostCheckOut(
        ok=result.ok,
        reason=result.reason,
        suggestion=result.suggestion,
        issues=result.issues_dict(),
        crisis=result.crisis,
    )


@router.post(
    "", response_model=PostWriteOut, status_code=status.HTTP_201_CREATED,
    dependencies=[limit_user("post-write", 10, 600)],
)
def create_post(
    body: PostCreate,
    background: BackgroundTasks,
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """고민 작성. 내 직무섬 또는 통합섬에만 쓸 수 있다.
    검사에 보통 1~3초(최대 5초) 걸리므로 FE는 로딩 화면을 띄운다."""
    island = get_accessible_island(db, body.island_id, me)
    result = _check_post(body.title, body.content, body.visibility)

    post = Post(
        user_id=me.id,
        island_id=island.id,
        topic=body.topic,
        title=body.title,
        content=body.content,
        comfort_type=body.comfort_type,
        visibility=body.visibility,
        show_years=body.show_years and me.years is not None,
        status="published",
        map_x=body.map_x,
        map_y=body.map_y,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    if post.visibility == "public":
        background.add_task(sync_post, post.id, crisis=result.crisis)
    return _out(post, result.crisis)


@router.patch("/{post_id}", response_model=PostWriteOut, dependencies=[limit_user("post-write", 10, 600)])
def update_post(
    post_id: int,
    body: PostUpdate,
    background: BackgroundTasks,
    me: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 글 수정. 제목·내용이 바뀌거나 나만 보기 → 공개로 바꾸면 다시 검사한다."""
    post = _get_my_post(db, post_id, me)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)

    title = changes.get("title", post.title)
    content = changes.get("content", post.content)
    visibility = changes.get("visibility", post.visibility)
    text_changed = title != post.title or content != post.content
    becomes_public = visibility == "public" and post.visibility != "public"

    crisis = False
    if text_changed or becomes_public:
        crisis = _check_post(title, content, visibility).crisis

    if "show_years" in changes:
        changes["show_years"] = changes["show_years"] and me.years is not None
    for key, value in changes.items():
        setattr(post, key, value)
    if post.status != "hidden":
        post.status = "published"
    db.commit()
    db.refresh(post)

    if post.visibility == "public":
        if text_changed or becomes_public:
            background.add_task(sync_post, post.id, crisis=crisis)
    else:
        background.add_task(sync_post, post.id)  # 나만 보기로 바꾸면 검색 벡터 삭제
    return _out(post, crisis)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """내 글 삭제. 댓글·공감·알림·검색 벡터는 DB에서 함께 지워진다 (CASCADE)."""
    post = _get_my_post(db, post_id, me)
    db.delete(post)
    db.commit()
