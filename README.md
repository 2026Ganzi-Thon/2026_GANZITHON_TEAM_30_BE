# 2026_GANZITHON_TEAM_30_BE

FastAPI + SQLAlchemy(SQLite) 백엔드

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python seed.py                  # 테스트 계정 생성 (선택)
python demo_seed.py --job 개발 --reset   # 발표용 데이터 (DB를 비우고 새로 만듦, 서버를 끄고 실행)
uvicorn app.main:app --reload
```

API 문서: http://localhost:8000/docs

## 인증 API

| 메서드 | 경로 | 설명 | 토큰 |
|---|---|---|---|
| GET | /auth/options | 직무·연차·캐릭터·고민 주제·위로 방식 선택지 (FE와 같은 값) | - |
| GET | /auth/nickname?character=tiger | 선택한 캐릭터 + 랜덤 형용사 닉네임 추천 | - |
| POST | /auth/signup | 회원가입 (이메일 형식만 검사, 캐릭터·개인정보 동의 필수, 연차 선택) | - |
| POST | /auth/login | 로그인 → access_token 발급 | - |
| POST | /auth/logout | 현재 토큰 폐기 | 필요 |
| GET | /auth/me | 내 정보 | 필요 |

| DELETE | /auth/me | 회원 탈퇴 (공개 글·댓글은 "떠난 이용자"로 남음) | 필요 |

토큰은 요청 헤더에 `Authorization: Bearer <access_token>` 으로 보냅니다.

## 서비스 API (모두 토큰 필요)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | /islands | 내 직무섬 + 통합섬, 7일 고민 수, 새 댓글 여부 |
| GET | /islands/{id}/neighbors | 지도에 띄울 이웃 캐릭터 + 최근 고민 |
| GET | /islands/{id}/posts | 최근 고민 목록 (`comfort_type`, `q`, `limit`, `before_id`) |
| GET | /users/{id}/profile?island_id= | 간단 프로필 |
| GET | /users/{id}/posts?island_id= | 이웃 한 명의 공개 고민 |
| GET | /users/me/posts | 내 고민 (나만 보기 포함, `visibility` 필터) |
| GET | /users/me/comments | 내가 쓴 댓글 |
| GET | /posts/{id} | 고민 상세 + 댓글 + 공감 (내 글이면 알림 읽음 처리) |
| POST | /posts/{id}/comments | 댓글 작성 (부적절하면 422 `{reason, suggestion}`) |
| DELETE | /posts/{id}/comments/{comment_id} | 내 댓글 삭제 |
| POST | /posts/{id}/reactions | 공감 토글 |
| GET | /notifications | 알림 목록 + 안 읽은 수 (`limit`, `before_id`) |
| POST | /notifications/read | 읽음 처리 (`{"post_id": 1}` 또는 `{}`로 전체) |
| POST | /reports | 신고 `{target_type: post/comment, target_id, reason}` |
| GET | /blocks | 내가 차단한 사람 |
| POST | /blocks | 차단 `{user_id}` |
| DELETE | /blocks/{user_id} | 차단 해제 |

## 환경변수

`.env.example`을 `.env`로 복사해서 채우면 자동으로 읽힙니다.

| 이름 | 기본값 |
|---|---|
| ENV | dev (배포 시 `production`: 이때 SECRET_KEY가 없으면 서버가 켜지지 않음) |
| DATABASE_URL | sqlite:///./ganzithon.db |
| SECRET_KEY | 개발용 값 (배포 시 반드시 변경) |
| ACCESS_TOKEN_EXPIRE_MINUTES | 1440 (1일) |
| CORS_ORIGINS | * (배포 시 프론트 주소, 쉼표로 여러 개) |
| UPSTAGE_API_KEY | 없음 (AI 기능용, 서버에만 설정) |
