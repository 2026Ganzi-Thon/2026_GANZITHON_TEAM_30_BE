"""LLM·임베딩 제공사 호출 (Upstage Solar / Google Gemini). 실패하면 AIUnavailable을 던지고,
호출한 쪽이 규칙 검사·템플릿 같은 대체 동작으로 넘어간다 (429 한도 초과여도 게시는 되게)."""
import json
import logging
import re

import httpx

from app.ai import settings

log = logging.getLogger("app.ai")


class AIUnavailable(Exception):
    """키 없음, 타임아웃, 429, 응답 형식 오류 등 AI를 쓸 수 없는 모든 경우."""


def _post(url: str, *, headers: dict, body: dict, timeout: float) -> dict:
    try:
        res = httpx.post(url, headers=headers, json=body, timeout=timeout)
    except httpx.HTTPError as e:
        raise AIUnavailable(f"network: {e.__class__.__name__}") from e
    if res.status_code != 200:
        # 429(한도 초과)·5xx 모두 여기로. 본문은 키가 섞일 수 있어 앞부분만 남긴다.
        log.warning("AI API %s → %s %s", url.split("?")[0], res.status_code, res.text[:200])
        raise AIUnavailable(f"http {res.status_code}")
    try:
        return res.json()
    except ValueError as e:
        raise AIUnavailable("invalid json") from e


# ---------- 채팅 ----------

def chat(system: str, user: str, *, json_mode: bool = False, temperature: float = 0.3, timeout: float) -> str:
    p = settings.provider()
    if p == "upstage":
        body = {
            "model": settings.UPSTAGE_CHAT_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            # 없으면 가끔 쉼표가 두 번 찍힌 JSON(",,")이 와서 검사가 규칙 검사로 떨어진다 (실측 약 8%)
            body["response_format"] = {"type": "json_object"}
        data = _post(
            f"{settings.UPSTAGE_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.UPSTAGE_API_KEY}"},
            body=body,
            timeout=timeout,
        )
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AIUnavailable("unexpected upstage response") from e

    if p == "gemini":
        config: dict = {"temperature": temperature}
        if json_mode:
            config["responseMimeType"] = "application/json"
        data = _post(
            f"{settings.GEMINI_BASE_URL}/models/{settings.GEMINI_CHAT_MODEL}:generateContent",
            headers={"x-goog-api-key": settings.GEMINI_API_KEY},
            body={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": config,
            },
            timeout=timeout,
        )
        try:
            return "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as e:
            raise AIUnavailable("unexpected gemini response") from e

    raise AIUnavailable("no provider")


def chat_json(system: str, user: str, *, timeout: float) -> dict:
    """JSON 답을 dict로 받는다. 형식이 깨져 오면 한 번만 다시 묻는다 (연결 실패·시간 초과는 바로 포기)."""
    for attempt in range(2):
        text = chat(system, user, json_mode=True, temperature=0.0, timeout=timeout)
        try:
            return parse_json_object(text)
        except AIUnavailable:
            if attempt == 1:
                raise
    raise AIUnavailable("unreachable")


def parse_json_object(text: str) -> dict:
    """```json 코드블록이나 앞뒤 설명이 붙어 와도 첫 번째 {...}만 꺼내서 읽는다."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise AIUnavailable("no json in response")
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise AIUnavailable("broken json") from e
    if not isinstance(value, dict):
        raise AIUnavailable("json is not an object")
    return value


# ---------- 임베딩 ----------

def embedding_model() -> str:
    """post_embeddings에 같이 저장해서, 제공사를 바꿔도 다른 모델 벡터끼리 비교하지 않게 한다."""
    p = settings.provider()
    if p == "upstage":
        return f"upstage:{settings.UPSTAGE_EMBED_PASSAGE_MODEL}"
    if p == "gemini":
        return f"gemini:{settings.GEMINI_EMBED_MODEL}:{settings.GEMINI_EMBED_DIM}"
    return f"local:ngram:{settings.LOCAL_EMBED_DIM}"


def embed_remote(texts: list[str], *, task: str, timeout: float) -> list[list[float]]:
    """task: "query"(검색어) / "passage"(저장할 고민)."""
    p = settings.provider()
    if p == "upstage":
        model = settings.UPSTAGE_EMBED_QUERY_MODEL if task == "query" else settings.UPSTAGE_EMBED_PASSAGE_MODEL
        data = _post(
            f"{settings.UPSTAGE_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {settings.UPSTAGE_API_KEY}"},
            body={"model": model, "input": texts},
            timeout=timeout,
        )
        try:
            rows = sorted(data["data"], key=lambda r: r.get("index", 0))
            return [r["embedding"] for r in rows]
        except (KeyError, TypeError) as e:
            raise AIUnavailable("unexpected upstage embedding response") from e

    if p == "gemini":
        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        model = f"models/{settings.GEMINI_EMBED_MODEL}"
        data = _post(
            f"{settings.GEMINI_BASE_URL}/{model}:batchEmbedContents",
            headers={"x-goog-api-key": settings.GEMINI_API_KEY},
            body={
                "requests": [
                    {
                        "model": model,
                        "content": {"parts": [{"text": t}]},
                        "taskType": task_type,
                        "outputDimensionality": settings.GEMINI_EMBED_DIM,
                    }
                    for t in texts
                ]
            },
            timeout=timeout,
        )
        try:
            return [e["values"] for e in data["embeddings"]]
        except (KeyError, TypeError) as e:
            raise AIUnavailable("unexpected gemini embedding response") from e

    raise AIUnavailable("no provider")
