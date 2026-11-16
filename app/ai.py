"""B 담당 파일. 아래는 A가 댓글 API를 테스트하려고 둔 임시 버전으로, B가 Solar 모델 호출로 교체한다.
함수 이름과 CheckResult 형식은 유지할 것."""
from dataclasses import dataclass


@dataclass
class CheckResult:
    ok: bool
    reason: str | None = None
    suggestion: str | None = None


_BANNED = ["시발", "씨발", "병신", "개새끼"]


def check_text(text: str) -> CheckResult:
    if any(word in text for word in _BANNED):
        return CheckResult(ok=False, reason="부적절한 표현이 포함돼 있어요")
    return CheckResult(ok=True)
