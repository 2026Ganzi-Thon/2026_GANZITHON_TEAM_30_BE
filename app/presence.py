"""섬 위에서 지금 돌아다니는 사람들의 위치 (실시간 접속 표시용).

DB에 남길 필요가 없는 휘발성 데이터라 서버 메모리에만 둔다.
FE가 몇 초마다 내 위치를 보내면, 최근 PRESENCE_TTL초 안에 위치를 보낸 사람만 '접속 중'으로 본다.
"""
import threading
import time

PRESENCE_TTL = 20  # 이 시간(초) 동안 소식이 없으면 접속 종료로 본다

_lock = threading.Lock()
# island_id -> user_id -> (x, y, 마지막 갱신 시각)
_positions: dict[int, dict[int, tuple[float, float, float]]] = {}


def update(island_id: int, user_id: int, x: float, y: float) -> None:
    with _lock:
        _positions.setdefault(island_id, {})[user_id] = (x, y, time.monotonic())


def online(island_id: int) -> dict[int, tuple[float, float]]:
    """지금 접속 중인 사람들의 위치. 오래된 항목은 이때 정리한다."""
    now = time.monotonic()
    with _lock:
        island = _positions.get(island_id, {})
        for user_id in [u for u, (_, _, ts) in island.items() if now - ts > PRESENCE_TTL]:
            del island[user_id]
        return {u: (x, y) for u, (x, y, _) in island.items()}


# (island_id, user_id) -> 발자국을 DB에 마지막으로 기록한 시각
_recorded: dict[tuple[int, int], float] = {}
FOOTPRINT_EVERY = 60  # 위치는 3초마다 오지만, 발자국은 이 간격(초)으로만 DB에 남긴다


def should_record(island_id: int, user_id: int) -> bool:
    now = time.monotonic()
    with _lock:
        last = _recorded.get((island_id, user_id))
        if last is not None and now - last < FOOTPRINT_EVERY:
            return False
        _recorded[(island_id, user_id)] = now
        return True


def clear() -> None:
    """테스트용."""
    with _lock:
        _positions.clear()
        _recorded.clear()
