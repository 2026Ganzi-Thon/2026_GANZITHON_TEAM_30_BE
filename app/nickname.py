"""익명 닉네임 생성: 사용자가 고른 동물 + 랜덤 형용사. 예) 수달 선택 → "포근한 수달" """
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
    """선택한 동물 이름 앞에 랜덤 형용사를 붙인다."""
    return f"{random.choice(ADJECTIVES)} {CHARACTERS[character]}"


def nickname_taken(db: Session, nickname: str) -> bool:
    return db.scalar(select(User.id).where(User.nickname == nickname)) is not None


def generate_unique_nickname(db: Session, character: str) -> str:
    """DB에 없는 닉네임이 나올 때까지 뽑는다. 형용사 조합이 다 차면 뒤에 숫자를 붙인다."""
    for _ in range(20):
        nickname = make_nickname(character)
        if not nickname_taken(db, nickname):
            return nickname
    while True:
        nickname = f"{make_nickname(character)}{random.randint(100, 9999)}"
        if not nickname_taken(db, nickname):
            return nickname


def is_valid_nickname(nickname: str, character: str) -> bool:
    adjectives = "|".join(map(re.escape, ADJECTIVES))
    animal = re.escape(CHARACTERS[character])
    return re.fullmatch(rf"({adjectives}) {animal}(\d{{3,4}})?", nickname) is not None
