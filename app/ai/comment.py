"""AI 첫 위로 댓글 write_first_comment (B 담당)."""
import logging

from app.ai import client, prompts, settings
from app.ai.check import has_crisis_signal
from app.config import COMMENT_MAX

log = logging.getLogger("app.ai")


def _clean(text: str) -> str:
    text = text.strip().strip('"').strip("“”").strip()
    for prefix in ("댓글:", "온도:", "답변:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text[:COMMENT_MAX]


def fallback_comment(comfort_type: str, crisis: bool) -> str:
    if crisis:
        return prompts.FALLBACK_CRISIS_COMMENT
    return prompts.FALLBACK_COMMENTS.get(comfort_type, prompts.FALLBACK_COMMENTS["empathy"])


def write_first_comment(post, crisis: bool | None = None, *, retries: int = 1) -> str:
    """post: title·content·comfort_type·topic 속성이 있는 객체 (models.Post).
    crisis를 안 넘기면 규칙으로 판단한다. AI를 못 쓰면 위로 방식별 기본 문장을 돌려준다."""
    if crisis is None:
        crisis = has_crisis_signal(f"{post.title}\n{post.content}")

    if settings.provider() != "local":
        system = prompts.first_comment_prompt(post.comfort_type, crisis)
        user = prompts.first_comment_user(post.title, post.content, getattr(post, "topic", None))
        for attempt in range(retries + 1):
            try:
                text = _clean(client.chat(system, user, temperature=0.7, timeout=settings.BACKGROUND_TIMEOUT_SECONDS))
            except client.AIUnavailable as e:
                log.warning("AI 첫 댓글 실패 (%s/%s): %s", attempt + 1, retries + 1, e)
                continue
            if len(text) >= 10:
                if crisis and "109" not in text:
                    text = f"{text} 혼자 견디기 힘들 땐 109 또는 1577-0199(24시간)로 연락해 주세요."[:COMMENT_MAX]
                return text

    return fallback_comment(post.comfort_type, crisis)
