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
| POST | /auth/email-code | 인증코드 받기 `{email, purpose: signup/login}` → `{expires_in, resend_after, demo_code}` | - |
| POST | /auth/signup | 회원가입 (비밀번호 없음, `code` 필수. 캐릭터·개인정보 동의 필수, 연차 선택: `""`이면 선택 안 함) | - |
| POST | /auth/login | `{email, code}`로 로그인 → access_token 발급 | - |
| POST | /auth/logout | 현재 토큰 폐기 | 필요 |
| GET | /auth/me | 내 정보 | 필요 |

| DELETE | /auth/me | 회원 탈퇴 (공개 글·댓글은 "떠난 이용자"로 남음) | 필요 |

### 이메일 인증코드

1. `POST /auth/email-code`로 6자리 코드를 받는다 (5분 유효, 60초 뒤 재요청 가능, 5번 틀리면 폐기)
2. 가입·로그인 요청에 `code`를 같이 보낸다

- `EMAIL_MODE=demo`(기본): 메일을 보내지 않고 응답의 `demo_code`에 코드가 담긴다. FE는 "체험용 인증코드"로 보여 주면 된다.
- `EMAIL_MODE=smtp`: 실제 메일 발송, `demo_code`는 `null`. `SMTP_USER`·`SMTP_PASSWORD`가 없으면 서버가 켜지지 않는다.
- 발송 실패 시 502. 발표 직전에 네트워크가 불안하면 `EMAIL_MODE=demo`로 바꿔 서버를 다시 켜면 된다.

토큰은 요청 헤더에 `Authorization: Bearer <access_token>` 으로 보냅니다.

모든 시각(`created_at` 등)은 UTC이며 `+00:00`이 붙어서 나갑니다. FE는 `new Date(값)`으로 그대로 읽으면 됩니다.

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
| DELETE | /posts/{id}/comments/{comment_id} | 내 댓글만 삭제 (남의 댓글은 403). 상세에는 `is_deleted: true`, "삭제된 댓글입니다"로 남음 |
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
| EMAIL_MODE | demo (`smtp`면 실제 메일 발송) |
| SMTP_HOST / SMTP_PORT | smtp.gmail.com / 465 (587이면 STARTTLS) |
| SMTP_USER / SMTP_PASSWORD | 없음 (Gmail은 계정 주소 / 앱 비밀번호) |
| SMTP_FROM | SMTP_USER와 같음 |
