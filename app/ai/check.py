"""게시 전 검사 check_text (B 담당).

1) 규칙 검사(정규식·목록)는 항상 실행한다: 전화번호·이메일·주민번호, 대표 회사명, 욕설, 위기 표현.
2) LLM 검사를 5초 안에 받으면 결과를 합친다. 실패·타임아웃·429면 규칙 결과만으로 판단한다.
   → AI가 죽어도 게시는 된다.
"""
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from app.ai import client, prompts, settings

log = logging.getLogger("app.ai")

Kind = Literal["post", "comment"]

CRISIS_SUPPORT = {
    "message": "지금 많이 힘드신 것 같아요. 혼자 견디지 않으셔도 괜찮아요.",
    "resources": [
        {"name": "자살예방상담전화", "phone": "109", "hours": "24시간"},
        {"name": "정신건강위기상담전화", "phone": "1577-0199", "hours": "24시간"},
    ],
}


@dataclass
class Issue:
    type: str  # PERSONAL_INFO / OFFENSIVE
    text: str | None = None  # 문제가 된 원문 구절
    start: int | None = None  # 원문에서 찾은 경우 위치 (FE 하이라이트용)
    end: int | None = None
    guide: str | None = None


@dataclass
class CheckResult:
    """A의 댓글 API는 ok·reason·suggestion만 쓴다. 나머지는 B의 고민 API·위기 안내용."""

    ok: bool
    reason: str | None = None
    suggestion: str | None = None
    personal_info: bool = False
    offensive: bool = False
    crisis: bool = False
    issues: list[Issue] = field(default_factory=list)
    checked_by: str = "rules"  # rules / llm

    def issues_dict(self) -> list[dict]:
        return [asdict(i) for i in self.issues]


# ---------- 규칙 ----------

_PHONE = re.compile(r"(?<!\d)(01[016789]|0[2-6]\d?)[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RRN = re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")

# 시연에서 확실히 잡혀야 하는 대표 회사명. 일반 단어와 겹치는 이름(라인, 토스, 당근 등)은 LLM에 맡긴다.
_COMPANIES = [
    "삼성전자", "삼성", "LG전자", "엘지", "SK하이닉스", "SK텔레콤", "현대자동차", "현대차", "기아자동차",
    "네이버", "카카오", "쿠팡", "배달의민족", "우아한형제들", "비바리퍼블리카", "롯데", "신한은행",
    "국민은행", "하나은행", "우리은행", "한화", "포스코", "넥슨", "엔씨소프트", "넷마블", "크래프톤",
    "야놀자", "카카오뱅크", "CJ제일제당", "아모레퍼시픽", "현대백화점", "신세계",
]
_COMPANY = re.compile(
    "|".join(re.escape(c) for c in sorted(_COMPANIES, key=len, reverse=True))
    + r"|\(주\)\s*[가-힣A-Za-z]+|주식회사\s*[가-힣A-Za-z]+|[가-힣A-Za-z]+\s*주식회사"
)

# 욕설은 엄격하게 거른다: 누구를 향하지 않은 혼잣말이어도 막는다.
# 초성 줄임말(ㅈㄴ·ㅅㅂ), 변형 표기(개새낑·씨빨), 영문(sibal·tlqkf·fuck)도 포함.
# 숫자·기호를 끼운 변형(ㅆ1발, 시.발)은 _normalize로 숫자·기호를 지운 뒤 찾는다.
# 띄어쓰기는 지우지 않는다 ("다시 발표"가 "시발"로 잡히지 않게).
# AI가 응답하지 못해도 이 규칙만으로 걸러진다.
_BANNED = re.compile(
    r"[시씨쓰ㅅㅆ][발빨벌팔](?!점)|ㅅㅂ|ㅆㅂ|ㅅㅃ|"  # 시발·씨빨·ㅆ발 (시발점은 제외)
    r"병신|븅신|빙신|ㅂㅅ|ㅄ|"
    r"개[새섀색쌔][끼끄낑기키]|[새쌔섀]끼|ㅅㄲ|ㄱㅅㄲ|"  # 개새끼·새끼
    r"좆|ㅈ같|ㅈ까|존나|졸라|조낸|존내|ㅈㄴ|ㅈ나|"
    r"지랄|ㅈㄹ|염병|썅|쌍년|개년|년놈|씹[새세할창]|"
    r"미친[놈년새것]|ㅁㅊ|개같|꺼져|ㄲㅈ|닥쳐|엿\s?먹|"
    r"sibal|ssibal|shibal|tlqkf|qudtls|fuck|shit|bitch|wtf"
)
# 욕설 사이에 끼운 숫자·기호 (띄어쓰기는 남긴다)
_FILLER = re.compile(r"[0-9!@#$%^&*()_+=\-.,~`'\"/\\|<>?:;\[\]{}·•★☆♡♥]")


def _find_banned(text: str) -> list[Issue]:
    """숫자·기호를 지운 글에서 욕설을 찾고, 원문 위치로 되돌려 표시한다."""
    kept = [(i, ch.lower()) for i, ch in enumerate(text) if not _FILLER.match(ch)]
    normalized = "".join(ch for _, ch in kept)
    issues = []
    for m in _BANNED.finditer(normalized):
        start, end = kept[m.start()][0], kept[m.end() - 1][0] + 1
        issues.append(Issue("OFFENSIVE", text[start:end], start, end, GUIDE["banned"]))
    return issues

_CRISIS = re.compile(
    r"죽고\s?싶|자살|자해|극단적\s?(인\s?)?선택|목숨을\s?끊|살기\s?싫|사라지고\s?싶|뛰어내리|"
    r"삶을\s?끝내|끝내고\s?싶|세상을\s?떠나고\s?싶|손목을\s?긋"
)

GUIDE = {
    "phone": "연락처는 빼고 올려 주세요.",
    "email": "이메일 주소는 빼고 올려 주세요.",
    "rrn": "주민등록번호 같은 개인정보는 빼고 올려 주세요.",
    "company": "회사명 대신 '우리 회사'처럼 써 보세요.",
    "banned": "상처가 될 수 있는 표현은 빼고 올려 주세요.",
}


def _find(pattern: re.Pattern, text: str, issue_type: str, guide: str) -> list[Issue]:
    return [Issue(issue_type, m.group(0), m.start(), m.end(), guide) for m in pattern.finditer(text)]


def mask_personal_info(text: str) -> str:
    """임베딩 API로 보내기 전에 연락처·이메일·주민번호를 가린다 (검색어 포함)."""
    text = _RRN.sub("[주민번호]", text)
    text = _PHONE.sub("[전화번호]", text)
    return _EMAIL.sub("[이메일]", text)


def has_crisis_signal(text: str) -> bool:
    return bool(_CRISIS.search(text))


def _rule_check(text: str) -> tuple[list[Issue], list[Issue], bool]:
    personal = (
        _find(_RRN, text, "PERSONAL_INFO", GUIDE["rrn"])
        + _find(_PHONE, text, "PERSONAL_INFO", GUIDE["phone"])
        + _find(_EMAIL, text, "PERSONAL_INFO", GUIDE["email"])
        + _find(_COMPANY, text, "PERSONAL_INFO", GUIDE["company"])
    )
    offensive = _find_banned(text)
    return personal, offensive, has_crisis_signal(text)


# ---------- LLM ----------

def _llm_check(text: str, kind: Kind) -> dict | None:
    if settings.provider() == "local":
        return None
    try:
        return client.chat_json(prompts.check_prompt(kind), text, timeout=settings.CHECK_TIMEOUT_SECONDS)
    except client.AIUnavailable as e:
        log.warning("check_text LLM 실패, 규칙 검사만 사용: %s", e)
        return None


def _section(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _llm_issues(section: dict, issue_type: str, text: str, fallback_guide: str) -> list[Issue]:
    guide = (section.get("suggestion") or "").strip() or fallback_guide
    spans = [s for s in section.get("spans") or [] if isinstance(s, str) and s.strip()]
    if not spans:
        return [Issue(issue_type, None, None, None, guide)]
    issues = []
    for span in spans:
        pos = text.find(span)
        issues.append(Issue(issue_type, span, pos if pos >= 0 else None, pos + len(span) if pos >= 0 else None, guide))
    return issues


def _dedupe(issues: list[Issue]) -> list[Issue]:
    seen, result = set(), []
    for i in issues:
        key = (i.type, i.text)
        if key in seen:
            continue
        seen.add(key)
        result.append(i)
    return result


# ---------- 공개 함수 ----------

def check_text(text: str, kind: Kind = "comment") -> CheckResult:
    """고민글은 kind="post"(제목+본문을 합쳐서), 댓글은 기본값 "comment".

    ok=False면 저장하지 않고 reason·suggestion·issues를 사용자에게 보여 준다.
    crisis=True는 ok와 별개: 막지 않고 게시하되 지원 정보(CRISIS_SUPPORT)를 함께 보여 준다.
    """
    personal, offensive, crisis = _rule_check(text)
    checked_by = "rules"

    data = _llm_check(text, kind)
    if data is not None:
        checked_by = "llm"
        pi, off, cr = _section(data, "personal_info"), _section(data, "offensive"), _section(data, "crisis")
        if pi.get("detected") is True:
            personal += _llm_issues(pi, "PERSONAL_INFO", text, GUIDE["company"])
        if off.get("detected") is True:
            offensive += _llm_issues(off, "OFFENSIVE", text, GUIDE["banned"])
        if cr.get("detected") is True:
            crisis = True

    personal, offensive = _dedupe(personal), _dedupe(offensive)
    reasons, suggestion = [], None
    if personal:
        reasons.append("다른 사람이 나를 알아볼 수 있는 정보(연락처·회사명 등)가 있어요")
        suggestion = personal[0].guide
    if offensive:
        reasons.append("상대가 상처받을 수 있는 표현이 있어요")
        suggestion = suggestion or offensive[0].guide

    return CheckResult(
        ok=not (personal or offensive),
        reason=" / ".join(reasons) or None,
        suggestion=suggestion,
        personal_info=bool(personal),
        offensive=bool(offensive),
        crisis=crisis,
        issues=personal + offensive,
        checked_by=checked_by,
    )
