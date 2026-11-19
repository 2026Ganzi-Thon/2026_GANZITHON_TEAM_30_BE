"""AI 첫 위로 댓글 write_first_comment (B 담당)."""
import logging
import re

from app.ai import client, prompts, settings
from app.ai.check import has_crisis_signal, mask_personal_info, passes_rules
from app.config import COMMENT_MAX

log = logging.getLogger("app.ai")

HOTLINE_NOTE = " 혼자 견디기 힘들 땐 109 또는 1577-0199(24시간)로 연락해 주세요."


def _clean(text: str) -> str:
    text = text.strip().strip('"').strip("“”").strip()
    for prefix in ("댓글:", "온도:", "답변:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text[:COMMENT_MAX]


def _is_polite(text: str) -> bool:
    """모든 문장이 존댓말(~요, ~니다, ~죠)로 끝나는지. 가끔 반말 댓글이 나와서 거른다 (실측 약 7%)."""
    sentences = [s.rstrip(".!?~ ") for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    return all(s.endswith(("요", "니다", "죠")) for s in sentences)


def fallback_comment(comfort_type: str, crisis: bool) -> str:
    if crisis:
        return prompts.FALLBACK_CRISIS_COMMENT
    return prompts.FALLBACK_COMMENTS.get(comfort_type, prompts.FALLBACK_COMMENTS["empathy"])


def _generate(system: str, user: str, crisis: bool, retries: int, label: str) -> str | None:
    for attempt in range(retries + 1):
        try:
            text = _clean(client.chat(system, user, temperature=0.7, timeout=settings.BACKGROUND_TIMEOUT_SECONDS))
        except client.AIUnavailable as e:
            log.warning("%s 실패 (%s/%s): %s", label, attempt + 1, retries + 1, e)
            continue
        if len(text) < 10:
            continue
        if not _is_polite(text):
            log.warning("%s 반말이라 다시 씀 (%s/%s)", label, attempt + 1, retries + 1)
            continue
        if crisis and "109" not in text:
            text = (text + HOTLINE_NOTE)[:COMMENT_MAX]
        if not passes_rules(text):
            log.warning("%s 규칙 검사 실패라 다시 씀 (%s/%s)", label, attempt + 1, retries + 1)
            continue
        return text
    return None


def write_first_comment(post, crisis: bool | None = None, *, retries: int = 2) -> str:
    """post: title·content·comfort_type·topic 속성이 있는 객체 (models.Post).
    crisis를 안 넘기면 규칙으로 판단한다. AI를 못 쓰면 위로 방식별 기본 문장을 돌려준다."""
    if crisis is None:
        crisis = has_crisis_signal(f"{post.title}\n{post.content}")

    if settings.provider() != "local":
        system = prompts.first_comment_prompt(post.comfort_type, crisis)
        user = prompts.first_comment_user(
            mask_personal_info(post.title), mask_personal_info(post.content), getattr(post, "topic", None)
        )
        text = _generate(system, user, crisis, retries, "AI 첫 댓글")
        if text:
            return text

    return fallback_comment(post.comfort_type, crisis)


def fallback_follow_up(crisis: bool, last_turn: bool, neighbors: int = 0) -> str:
    if crisis:
        return prompts.FALLBACK_CRISIS_COMMENT
    if neighbors:
        return prompts.FALLBACK_FOLLOWUP_NEIGHBORS
    return prompts.FALLBACK_FOLLOWUP_LAST if last_turn else prompts.FALLBACK_FOLLOWUP


def write_follow_up(
    post,
    thread: list[tuple[str, str]],
    *,
    last_turn: bool,
    neighbors: int,
    crisis: bool | None = None,
    retries: int = 2,
) -> str:
    if crisis is None:
        crisis = any(speaker == "작성자" and has_crisis_signal(text) for speaker, text in thread)

    if settings.provider() != "local":
        system = prompts.follow_up_prompt(post.comfort_type, crisis, last_turn, neighbors)
        masked = [(speaker, mask_personal_info(text)) for speaker, text in thread]
        user = prompts.follow_up_user(
            mask_personal_info(post.title), mask_personal_info(post.content), getattr(post, "topic", None), masked
        )
        text = _generate(system, user, crisis, retries, "AI 이어 답글")
        if text:
            return text

    return fallback_follow_up(crisis, last_turn, neighbors)


def write_private_reply(post, thread: list[tuple[str, str]], *, crisis: bool, retries: int = 1) -> str:
    """나만 보기 고민에서 작성자와 나누는 대화의 온도 답. thread가 비어 있으면 첫인사."""
    if settings.provider() != "local":
        system = prompts.private_chat_prompt(post.comfort_type, crisis)
        masked = [(speaker, mask_personal_info(text)) for speaker, text in thread]
        user = prompts.follow_up_user(
            mask_personal_info(post.title), mask_personal_info(post.content), getattr(post, "topic", None), masked
        )
        text = _generate(system, user, crisis, retries, "나만 보기 대화")
        if text:
            return text
    return prompts.FALLBACK_CRISIS_COMMENT if crisis else prompts.FALLBACK_PRIVATE_CHAT
