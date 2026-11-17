from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.config import CHARACTERS, COMMENT_MAX, JOBS, YEARS

class SignupRequest(BaseModel):
    email: EmailStr  # 회사 이메일: 형식 검사 + 이메일 인증코드로 본인 확인 (비밀번호 없음)
    code: str = Field(pattern=r"^\d{6}$", description="이메일로 받은 6자리 인증코드")
    job: str
    years: str | None = None  
    character: str  
    nickname: str | None = Field(default=None, max_length=30)
    agree_privacy: bool 

    @field_validator("job")
    @classmethod
    def job_must_exist(cls, v: str) -> str:
        if v not in JOBS:
            raise ValueError(f"직무는 {JOBS} 중 하나여야 합니다")
        return v

    @field_validator("years", mode="before")
    @classmethod
    def years_must_exist(cls, v: str | None) -> str | None:
        # FE의 "선택 안 함"은 빈 문자열("")로 온다 → 연차 없음(None)으로 저장
        if isinstance(v, str) and not v.strip():
            return None
        if v is not None and v not in YEARS:
            raise ValueError(f"연차는 {YEARS} 중 하나이거나 비워 두어야 합니다")
        return v

    @field_validator("character")
    @classmethod
    def character_must_exist(cls, v: str) -> str:
        if v not in CHARACTERS:
            raise ValueError(f"캐릭터는 {list(CHARACTERS)} 중 하나여야 합니다")
        return v

    @field_validator("agree_privacy")
    @classmethod
    def must_agree(cls, v: bool) -> bool:
        if not v:
            raise ValueError("개인정보 이용 안내에 동의해야 가입할 수 있습니다")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$", description="이메일로 받은 6자리 인증코드")


class EmailCodeRequest(BaseModel):
    email: EmailStr
    purpose: Literal["signup", "login"]


class EmailCodeOut(BaseModel):
    expires_in: int  # 코드 유효 시간(초)
    resend_after: int  # 다시 받기까지 기다릴 시간(초)
    demo_code: str | None = None  # EMAIL_MODE=demo일 때만. FE는 "체험용 인증코드: 123456"으로 표시


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class NicknameSuggestion(BaseModel):
    nickname: str
    character: str


class IslandOut(BaseModel):
    id: int
    type: str  
    name: str
    is_mine: bool  
    post_count: int  # 최근 7일 공개 고민 수 (0이면 "작성된 고민이 없어요!")
    has_new_comment: bool  


class AuthorOut(BaseModel):
    """글·이웃에 표시되는 익명 작성자 정보. email·years는 절대 넣지 않는다."""
    user_id: int
    nickname: str
    character: str
    job: str | None = None 


class LatestPostOut(BaseModel):
    id: int
    title: str
    created_at: datetime


class NeighborOut(BaseModel):
    author: AuthorOut
    latest_post: LatestPostOut | None  
    post_count: int  
    is_me: bool


class PostSummary(BaseModel):
    id: int
    title: str
    preview: str  
    topic: str
    comfort_type: str
    created_at: datetime
    comment_count: int
    author: AuthorOut


class PostListOut(BaseModel):
    posts: list[PostSummary]
    user_ids: list[int]  
    next_before_id: int | None  


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    job: str
    years: str | None
    nickname: str
    character: str

class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=COMMENT_MAX)
    @field_validator('content')
    @classmethod
    def not_blank( cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('댓글 내용을 입력해 주세요')
        return v

class CommentOut(BaseModel):
    id: int
    content: str  # 삭제된 댓글이면 "삭제된 댓글입니다"
    is_ai: bool
    is_deleted: bool = False
    author: AuthorOut | None  # AI 댓글·삭제된 댓글이면 None
    is_mine: bool
    created_at: datetime

class PostDetailOut(BaseModel):
    id: int
    island_id: int
    topic: str
    title: str
    content: str
    comfort_type: str
    visibility: str
    status: str
    created_at: datetime
    updated_at: datetime
    author: AuthorOut
    years: str | None          # 글쓴이가 '연차 표시'를 켰을 때만
    is_mine: bool             
    reaction_count: int
    reacted_by_me: bool
    comments: list[CommentOut]

class ReactionOut(BaseModel):
    reacted: bool
    reaction_count: int

class MyPostOut(PostSummary):
    visibility: str
    status: str
    has_unread: bool  # 이 글에 안 읽은 알림이 있으면 true


class MyCommentOut(BaseModel):
    id: int
    content: str
    created_at: datetime
    post_id: int | None  # 글이 비공개로 바뀌었거나 차단 관계면 None
    post_title: str  # 볼 수 없는 글이면 "삭제된 글"


# ---------- 4단계: 알림 ----------

class NotificationOut(BaseModel):
    id: int
    type: str  # comment / reaction
    post_id: int
    post_title: str
    actor: AuthorOut | None  # AI 댓글 알림이면 None
    is_ai: bool
    is_read: bool
    created_at: datetime


class NotificationListOut(BaseModel):
    notifications: list[NotificationOut]
    unread_count: int
    next_before_id: int | None


class ReadRequest(BaseModel):
    post_id: int | None = None  # 비우면 전체 읽음


# ---------- 5단계: 신고·차단 ----------

class ReportCreate(BaseModel):
    target_type: Literal["post", "comment"]
    target_id: int
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("신고 사유를 입력해 주세요")
        return v


class BlockCreate(BaseModel):
    user_id: int


class BlockedUserOut(BaseModel):
    user_id: int
    nickname: str
    character: str
    blocked_at: datetime
