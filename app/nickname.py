"""익명 닉네임 생성: 랜덤 형용사 + 사용자가 고른 동물 + 4자리 숫자. 예) 호랑이 선택 → "포근한 호랑이 4821" """
import random
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import CHARACTERS
from app.models import User

ADJECTIVES = [  # FE js/app.js와 같은 목록
    "느긋한", "다정한", "용감한", "포근한", "씩씩한", "졸린",
    "부지런한", "호기심 많은", "행복한", "상냥한", "차분한", "엉뚱한",
    "재치 있는", "명랑한", "수줍은", "유쾌한", "모험심 많은", "든든한",
    "꼼꼼한", "낙천적인", "정겨운", "발랄한", "온화한", "장난기 많은",
]


def make_nickname(character: str) -> str:
    """형용사 + 동물 + 4자리 숫자(1000~9999). 숫자가 있어 같은 동물끼리도 거의 겹치지 않는다."""
    return f"{random.choice(ADJECTIVES)} {CHARACTERS[character]} {random.randint(1000, 9999)}"


def nickname_taken(db: Session, nickname: str) -> bool:
    return db.scalar(select(User.id).where(User.nickname == nickname)) is not None


def generate_unique_nickname(db: Session, character: str) -> str:
    """DB에 없는 닉네임이 나올 때까지 뽑는다 (동물 하나당 24 x 9000가지라 거의 한 번에 끝난다)."""
    while True:
        nickname = make_nickname(character)
        if not nickname_taken(db, nickname):
            return nickname


def is_valid_nickname(nickname: str, character: str) -> bool:
    """"형용사 동물 숫자4자리" 형식이고, 동물이 선택한 캐릭터와 같은지 확인한다."""
    adjectives = "|".join(map(re.escape, ADJECTIVES))
    animal = re.escape(CHARACTERS[character])
    return re.fullmatch(rf"({adjectives}) {animal} [1-9]\d{{3}}", nickname) is not None
