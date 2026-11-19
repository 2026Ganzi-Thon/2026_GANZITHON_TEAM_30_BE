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

# 목록에 없는 작은 회사도 잡기 위한 "회사 이름 꼴": 이름(2~8자) + 회사 이름에 흔한 끝말.
# 예: 한빛테크, 미래랩스, 대한물산. 일반 단어(신용카드·핀테크·스터디그룹)는 아래 예외로 거른다.
_COMPANY_SUFFIX = (
    "엔터테인먼트|인베스트먼트|모빌리티|네트웍스|파트너스|홀딩스|컴퍼니|캐피탈|중공업|"
    "전자|은행|증권|건설|제약|바이오|테크|랩스|소프트|코리아|그룹|물산|상회|카드"
)
_COMPANY_LIKE = re.compile(
    rf"([가-힣A-Za-z]{{2,8}})({_COMPANY_SUFFIX})"
    r"(?!웨어|레인지|결재|담배|기기|제품|상거래|서명|문서|계약|우편|공학|정부|책|사전|화폐|"
    r"과제|미팅|채팅|발표|리더|장|원)"
)
# 이 말로 끝나면 회사 이름이 아니라 일반 명칭이다 ("우리 은행"이 아니라 "다른은행", "신용카드" 등)
_COMPANY_LIKE_PREFIX_GENERIC = (
    "다른", "저희", "그런", "어떤", "모든", "여러", "이번", "예전", "이전", "지금", "대형", "중소", "중견",
    "외국계", "국내", "해외", "글로벌", "일반", "지역", "동네", "인터넷", "시중", "지방", "저축", "국책",
    "중앙", "주거래", "신용", "체크", "법인", "교통", "사원", "출입", "선불", "기프트", "포인트", "개인",
    "회사", "할인", "스터디", "독서", "포커스", "동아리", "모임", "핀", "에듀", "푸드", "프롭", "헬스",
    "하이", "리걸", "애드", "클린", "그린", "뷰티", "인슈어", "레그", "빅", "딥", "종합", "벤처", "가전",
    "의료", "제약", "생명", "그룹", "마케팅", "애드", "대기업", "계열", "자회사", "협력", "거래처", "경쟁",
)

# 다니는 곳을 말하는 문장: "OO에 다녀요", "OO 입사", "OO에서 근무". OO 자리는 AI가 한 번 더 판단한다.
_WORKPLACE_CONTEXT = re.compile(
    r"([가-힣A-Za-z0-9]{2,12}?)\s?(?:에서|에|으로|로)?\s?(?:다니|다녀|다닌|입사|재직|근무|출근|퇴사|이직|일하|일해|일한)"
)
_WORKPLACE_GENERIC = re.compile(
    r"(회사|직장|기업|스타트업|사무실|본사|지사|공장|매장|팀|부서|여기|거기|이곳|그곳|저곳|곳|데|"
    r"계열사|자회사|협력사|대학|학교|병원|은행|증권사|카페|식당|편의점|지금|이전|예전|오래|계속|같이|열심히|"
    r"그만|바로|처음|새로|다시|빨리|늦게|일찍|정규직|계약직|인턴|알바|아르바이트|외국계|대기업|중소기업|공기업)$"
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
    "check": "회사명·기관명·실명 같은 정보가 남아 있는지 확인하고, '우리 회사'처럼 바꿔 주세요.",
    "banned": "상처가 될 수 있는 표현은 빼고 올려 주세요.",
}


def _find(pattern: re.Pattern, text: str, issue_type: str, guide: str) -> list[Issue]:
    return [Issue(issue_type, m.group(0), m.start(), m.end(), guide) for m in pattern.finditer(text)]


def _find_company_like(text: str) -> list[Issue]:
    """목록에 없는 회사도 '이름+회사 끝말' 꼴이면 잡는다. 일반 명칭으로 끝나는 앞말은 건너뛴다."""
    issues = []
    for m in _COMPANY_LIKE.finditer(text):
        if m.group(1).endswith(_COMPANY_LIKE_PREFIX_GENERIC):
            continue
        issues.append(Issue("PERSONAL_INFO", m.group(0), m.start(), m.end(), GUIDE["company"]))
    return issues


def workplace_candidates(text: str) -> list[str]:
    """'OO에 다녀요'·'OO 입사'의 OO처럼 다니는 곳으로 보이는 말. 막지는 않고 AI에게 판단을 맡긴다."""
    found = []
    for m in _WORKPLACE_CONTEXT.finditer(text):
        word = m.group(1)
        if not _WORKPLACE_GENERIC.search(word) and word not in found:
            found.append(word)
    return found[:5]


def mask_personal_info(text: str) -> str:
    """임베딩 API로 보내기 전에 연락처·이메일·주민번호를 가린다 (검색어 포함)."""
    text = _RRN.sub("[주민번호]", text)
    text = _PHONE.sub("[전화번호]", text)
    return _EMAIL.sub("[이메일]", text)


def has_crisis_signal(text: str) -> bool:
    return bool(_CRISIS.search(text))


def passes_rules(text: str) -> bool:
    personal, offensive, _ = _rule_check(text)
    return not personal and not offensive


MASK_TOKENS = ("[주민번호]", "[전화번호]", "[이메일]")


def _rule_check(text: str) -> tuple[list[Issue], list[Issue], bool]:
    personal = (
        _find(_RRN, text, "PERSONAL_INFO", GUIDE["rrn"])
        + _find(_PHONE, text, "PERSONAL_INFO", GUIDE["phone"])
        + _find(_EMAIL, text, "PERSONAL_INFO", GUIDE["email"])
        + _find(_COMPANY, text, "PERSONAL_INFO", GUIDE["company"])
        + _find_company_like(text)
    )
    offensive = _find_banned(text)
    return personal, offensive, has_crisis_signal(text)


# ---------- LLM ----------

def _llm_check(text: str, kind: Kind) -> dict | None:
    if settings.provider() == "local":
        return None
    user = prompts.wrap_user_text(mask_personal_info(text))
    candidates = workplace_candidates(mask_personal_info(text))
    if candidates:
        user += prompts.workplace_hint(candidates)
    try:
        return client.chat_json(prompts.check_prompt(kind), user, timeout=settings.CHECK_TIMEOUT_SECONDS)
    except client.AIUnavailable as e:
        log.warning("check_text LLM 실패, 규칙 검사만 사용: %s", e)
        return None


def _section(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _llm_issues(section: dict, issue_type: str, text: str, fallback_guide: str) -> list[Issue]:
    guide = (section.get("suggestion") or "").strip() or fallback_guide
    raw = [s for s in section.get("spans") or [] if isinstance(s, str) and s.strip()]
    spans = [s for s in raw if not any(token in s for token in MASK_TOKENS)]
    if not spans:
        # 이미 '[전화번호]'처럼 가린 표현만 짚었다면 문제가 아니다.
        # (가리라고 안내해 놓고 가린 글을 다시 막지 않게. 진짜 개인정보는 규칙 검사가 따로 잡는다)
        if raw or any(token in text for token in MASK_TOKENS):
            return []
        return [Issue(issue_type, None, None, None, guide)]
    issues = []
    for span in spans:
        pos = text.find(span)
        issues.append(Issue(issue_type, span, pos if pos >= 0 else None, pos + len(span) if pos >= 0 else None, guide))
    return issues


def _pointed_nowhere(section: dict, text: str) -> bool:
    """AI가 '개인정보 있음'이라면서 구절을 하나도 짚지 않았고, 글에 가림 표시가 있는 경우.
    가림 표시를 보고 그런 건지, 다른 회사명을 놓친 건지 알 수 없다."""
    has_spans = any(isinstance(s, str) and s.strip() for s in section.get("spans") or [])
    return not has_spans and any(token in text for token in MASK_TOKENS)


def _recheck_without_masks(text: str, kind: Kind) -> list[Issue]:
    """가림 표시를 지우고 한 번 더 물어 본다. 그래도 있다고 하면 막는다 (그냥 통과시키지 않음).
    AI가 응답하지 못하면 규칙 검사 결과만 믿는다."""
    stripped = text
    for token in MASK_TOKENS:
        stripped = stripped.replace(token, "")
    data = _llm_check(stripped, kind)
    pi = _section(data or {}, "personal_info")
    if pi.get("detected") is not True:
        return []
    found = _llm_issues(pi, "PERSONAL_INFO", text, GUIDE["company"])
    return found or [Issue("PERSONAL_INFO", None, None, None, GUIDE["check"])]


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
            found = _llm_issues(pi, "PERSONAL_INFO", text, GUIDE["company"])
            if not found and not personal and _pointed_nowhere(pi, text):
                found = _recheck_without_masks(text, kind)
            personal += found
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
