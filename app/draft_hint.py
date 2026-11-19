"""'내용이 부실한 고민' 판단: 막지 않고, 조금 더 적어 보라고 권하기만 한다.

AI 없이 규칙만 쓴다 → 같은 글엔 늘 같은 결과, "왜 권했는지"를 바로 설명할 수 있다.
기준 (시드 고민 본문은 28~80자, 중간값 48자):
  1. same_as_title: 본문이 제목을 거의 그대로 옮겼다 (띄어쓰기 빼고 비교, 80% 이상 같음)
  2. noise: 자음·모음만("ㅠㅠ", "ㅋㅋ")이거나 같은 글자 반복("아아아아")이 본문의 절반 이상
  3. short: 띄어쓰기를 빼고 20자 미만
"""
import re
from difflib import SequenceMatcher

from pydantic import BaseModel

MIN_CONTENT_CHARS = 20
SAME_AS_TITLE_RATIO = 0.8
NOISE_RATIO = 0.5

TIPS = [
    "언제, 어떤 일이 있었나요?",
    "그때 어떤 기분이 들었나요?",
    "이웃에게 어떤 말을 듣고 싶나요?",
]
MESSAGES = {
    "same_as_title": "본문이 제목과 거의 같아요. 무슨 일이 있었는지 조금만 풀어 주면 이웃이 더 깊이 공감할 수 있어요.",
    "noise": "그 마음, 충분히 느껴져요. 어떤 상황이었는지 한 문장만 적어 주면 이웃이 위로를 건네기 쉬워요.",
    "short": "고민이 조금 짧아요. 어떤 상황인지 한두 문장만 더 적어 주면 이웃이 위로하기 쉽고, 비슷한 고민도 더 잘 찾아져요.",
}


class DraftHint(BaseModel):
    reason: str  # same_as_title | noise | short
    message: str
    tips: list[str]
    length: int  # 띄어쓰기를 뺀 본문 글자 수
    min_length: int


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _noise_ratio(compact: str) -> float:
    """자음·모음 낱자 + 3번 넘게 반복된 글자가 차지하는 비율."""
    if not compact:
        return 0.0
    jamo = len(re.findall(r"[ㄱ-ㅎㅏ-ㅣ]", compact))
    squeezed = re.sub(r"([^ㄱ-ㅎㅏ-ㅣ])\1{2,}", r"\1", compact)  # "아아아아" → "아"
    repeated = len(compact) - len(squeezed)
    return (jamo + repeated) / len(compact)


def draft_hint(title: str, content: str) -> DraftHint | None:
    body = _compact(content)
    head = _compact(title)
    reason = None
    if body and head and (body in head or SequenceMatcher(None, head, body).ratio() >= SAME_AS_TITLE_RATIO):
        reason = "same_as_title"
    elif _noise_ratio(body) >= NOISE_RATIO:
        reason = "noise"
    elif len(body) < MIN_CONTENT_CHARS:
        reason = "short"
    if reason is None:
        return None
    return DraftHint(
        reason=reason, message=MESSAGES[reason], tips=TIPS, length=len(body), min_length=MIN_CONTENT_CHARS,
    )
