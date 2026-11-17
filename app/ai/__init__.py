"""B 담당 AI 기능. 다른 코드는 여기 함수만 불러 쓴다 (분담표 'A·B 연결 지점').

    check_text(text) -> CheckResult
    write_first_comment(post) -> str
    embed(text) -> list[float]
    search_similar(query, island_id) -> list[int]   # post_id 목록

AI 키가 없거나 호출이 실패해도 규칙 검사·기본 문장·로컬 임베딩으로 동작한다 (app/ai/settings.py 참고).
"""
from app.ai.check import CRISIS_SUPPORT, CheckResult, Issue, check_text
from app.ai.comment import write_first_comment
from app.ai.embedding import embed
from app.ai.search import search_similar

__all__ = ["CRISIS_SUPPORT", "CheckResult", "Issue", "check_text", "write_first_comment", "embed", "search_similar"]
