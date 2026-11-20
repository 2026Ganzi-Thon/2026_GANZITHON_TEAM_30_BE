from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.config import CHARACTER_COLORS, CHARACTERS, COMMENT_MAX, JOBS, YEARS

class SignupRequest(BaseModel):
    email: EmailStr  # 회사 이메일: 형식 검사 + 이메일 인증코드로 본인 확인 (비밀번호 없음)
    code: str = Field(pattern=r"^\d{6}$", description="이메일로 받은 6자리 인증코드")
    job: str
    years: str | None = None  
    character: str  
    nickname: str | None = Field(default=None, max_length=30, description="비우면 서버가 자동 생성. 예) 포근한 호랑이 4821")
    agree_privacy: bool
    remember: bool = False  # "로그인 유지": 토큰을 30일 동안 유효하게
    color: str = "original"  # 가입 화면 팔레트에서 고른 캐릭터 색감

    @field_validator("color")
    @classmethod
    def signup_color_must_exist(cls, v: str) -> str:
        if v not in CHARACTER_COLORS:
            raise ValueError(f"색감은 {list(CHARACTER_COLORS)} 중 하나여야 합니다")
        return v

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


class ProfileUpdate(BaseModel):
    """프로필 수정: 보낸 필드만 바꾼다. 캐릭터만 바꾸면 그 동물로 닉네임을 새로 만들어 준다."""
    character: str | None = None
    nickname: str | None = Field(default=None, max_length=30, description="GET /auth/nickname으로 추천받은 값")
    accept_invites: bool | None = None
    color: str | None = None

    @field_validator("character")
    @classmethod
    def character_must_exist(cls, v: str | None) -> str | None:
        if v is not None and v not in CHARACTERS:
            raise ValueError(f"캐릭터는 {list(CHARACTERS)} 중 하나여야 합니다")
        return v

    @field_validator("color")
    @classmethod
    def color_must_exist(cls, v: str | None) -> str | None:
        if v is not None and v not in CHARACTER_COLORS:
            raise ValueError(f"색감은 {list(CHARACTER_COLORS)} 중 하나여야 합니다")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$", description="이메일로 받은 6자리 인증코드")
    remember: bool = False  # "로그인 유지": 토큰을 30일 동안 유효하게


class EmailCodeRequest(BaseModel):
    email: EmailStr
    purpose: Literal["signup", "login"]


class EmailCodeVerify(BaseModel):
    email: EmailStr
    purpose: Literal["signup", "login"]
    code: str = Field(pattern=r"^\d{6}$")


class EmailCodeOut(BaseModel):
    expires_in: int  # 코드 유효 시간(초)
    resend_after: int  # 다시 받기까지 기다릴 시간(초)
    demo_code: str | None = None  # EMAIL_MODE=demo일 때만. FE는 "체험용 인증코드: 123456"으로 표시


class StartRequest(BaseModel):
    """가입·로그인을 나누지 않고 이메일 하나로 시작한다"""
    email: EmailStr


class StartOut(EmailCodeOut):
    is_new: bool  # true면 처음 온 사람 → 코드 확인 뒤 직무·캐릭터를 고르고 /auth/signup, false면 /auth/login


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


class TitleOut(BaseModel):
    """활동으로 얻은 대표 칭호 (app/titles.py)"""
    key: str
    icon: str
    name: str
    tier: int  # 1 새싹 · 2 따뜻한 · 3 빛나는 · 4 전설
    tier_name: str
    desc: str


class TitleItem(BaseModel):
    key: str
    icon: str
    name: str
    desc: str
    tier: int
    tier_name: str
    earned: bool
    progress: int
    need: int
    stat_label: str


class TitlesOut(BaseModel):
    current: TitleOut | None
    chosen_key: str | None  # 직접 고른 대표 칭호 (없으면 가장 높은 칭호가 자동으로)
    earned_count: int
    items: list[TitleItem]


class TitleChoice(BaseModel):
    key: str | None = Field(None, max_length=30, description="비우면 가장 높은 칭호를 자동으로")


class AuthorOut(BaseModel):
    """글·이웃에 표시되는 익명 작성자 정보. email·years는 절대 넣지 않는다."""
    user_id: int
    nickname: str
    character: str
    color: str = "original"
    job: str | None = None
    title: TitleOut | None = None  # 활동 칭호 (상세·이웃 목록에서만 채움)


class LatestPostOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    map_x: float | None = None  # 글을 쓴 지도 위 자리(%). 없으면 FE가 자리를 정한다
    map_y: float | None = None
    # 내용이 닮은 고민끼리는 지도에 말풍선 하나로 합친다 (이웃이 많아져도 지도가 무거워지지 않게)
    bubble: int | None = None  # 이 글이 합쳐진 대표 글 id (대표 글이면 자기 id, 안 합쳐졌으면 None)
    bubble_size: int = 1  # 대표 글에만: 합쳐진 글 수


class PresenceIn(BaseModel):
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)


class PresenceOut(BaseModel):
    """지금 섬에 접속해 돌아다니는 이웃"""
    author: AuthorOut
    x: float
    y: float


class TemperatureOut(BaseModel):
    """섬 온도: 최근 고민 글과 위로 댓글이 많을수록 35°에서 42° 쪽으로 올라간다 (36.5°가 목표, 38° 이상이 가장 큰 불)"""
    temperature: float
    level: Literal["cold", "mild", "warm", "hot"]
    posts: int
    comments: int
    days: int
    online: int = 0  # 지금 이 섬을 돌아다니는 사람 수 (섬 선택 화면용)


class FootprintOut(BaseModel):
    """최근 섬에 다녀간 이웃의 발자국. x·y가 없으면 FE가 그 이웃의 자리에 찍는다"""
    user_id: int
    character: str
    x: float | None = None
    y: float | None = None
    hours_ago: float


class FootprintsOut(BaseModel):
    visitors: int  # 최근 FOOTPRINT_HOURS 동안 다녀간 이웃 수 (나 제외)
    hours: int
    footprints: list[FootprintOut]


class BottleOut(BaseModel):
    """유리병 편지: 다른 섬(또는 예전)에 남겨진 고민 하나와, 그 뒤 글쓴이가 덧붙인 이야기"""
    post_id: int
    island_id: int
    island_name: str
    topic: str
    title: str
    content: str
    comfort_type: str
    created_at: datetime
    author: AuthorOut
    follow_up: str | None = None
    comment_count: int
    next_at: datetime  # 다음 편지가 떠내려오는 시각 (한국 시간 아침 8시)


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
    waiting: bool = False


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
    color: str = "original"
    accept_invites: bool = True


class SignupResponse(UserResponse):
    access_token: str  # 가입하면 바로 로그인 상태 (인증코드를 한 번 더 받지 않게)
    token_type: str = "bearer"

class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=COMMENT_MAX)
    parent_id: int | None = Field(default=None, ge=1)

    @field_validator('content')
    @classmethod
    def not_blank( cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('댓글 내용을 입력해 주세요')
        return v

class CrisisResource(BaseModel):
    name: str
    phone: str
    hours: str


class CrisisSupport(BaseModel):
    message: str
    resources: list[CrisisResource]


class CommentOut(BaseModel):
    id: int
    content: str  # 삭제된 댓글이면 "삭제된 댓글입니다"
    is_ai: bool
    is_deleted: bool = False
    is_hidden: bool = False
    thanked: bool = False
    parent_id: int | None = None
    author: AuthorOut | None  # AI 댓글·삭제된 댓글이면 None
    is_mine: bool
    created_at: datetime


class CommentCreateOut(CommentOut):
    crisis_support: CrisisSupport | None = None
    ai_reply_pending: bool = False

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

class ThanksOut(BaseModel):
    thanked: bool


class SimilarPostOut(PostSummary):
    similarity: float


class MySummaryOut(BaseModel):
    post_count: int
    comment_count: int
    thanks_received: int
    posts_helped: int


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


class AppealCreate(BaseModel):
    target_type: Literal["post", "comment"]
    target_id: int
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이의 제기 사유를 입력해 주세요")
        return v


class PrivateChatIn(BaseModel):
    """비우면 온도가 먼저 말을 건다 (대화가 비어 있을 때만)"""
    content: str | None = Field(default=None, max_length=500)


class PrivateChatMessage(BaseModel):
    id: int
    is_ai: bool
    content: str
    created_at: datetime


class PrivateChatOut(BaseModel):
    messages: list[PrivateChatMessage]
    remaining: int  # 이 글에서 더 보낼 수 있는 말 수
    crisis_support: CrisisSupport | None = None


class KeeperQuestion(BaseModel):
    text: str
    topic: str  # 이 질문으로 글을 쓸 때 미리 골라 둘 주제


class KeeperWeek(BaseModel):
    days: int
    posts: int
    comforts: int  # 이웃이 건넨 위로 (AI 제외)
    ai_comforts: int  # 온도가 건넨 위로
    thanks: int
    visitors: int
    top_topic: str | None


class KeeperOut(BaseModel):
    """섬지기(운영자 캐릭터) 안내: 인사, 이번 주의 질문, 섬 소식, 이용 원칙, 위기 안내."""
    name: str
    moment: str = ""  # 예: "월요일 아침"
    greeting: str  # 요일·시간대에 맞춘 섬지기 한마디
    question: KeeperQuestion
    week: KeeperWeek
    rules: list[str]
    report_hide_threshold: int
    crisis_support: CrisisSupport
