# 2026_GANZITHON_TEAM_30_BE

FastAPI + SQLAlchemy 백엔드 (로컬 SQLite, 배포 PostgreSQL)

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python seed.py                  # 테스트 계정 생성 (선택)
python demo_seed.py --job 개발 --reset   # 발표용 데이터 (DB를 비우고 새로 만듦, 서버를 끄고 실행)
python demo_seed_b.py                    # 시연용 고민 추가 + 유사 검색용 임베딩 (demo_seed.py 다음에)
pytest -q                                # 테스트
uvicorn app.main:app --reload
```

API 문서: http://localhost:8000/docs

시연 데이터를 넣으면 섬마다 고민을 가진 이웃 캐릭터가 채워집니다. 발표 직무섬 16명, 나머지 직무섬 8명·7명, 통합섬 14명이고, 캐릭터 13종이 모두 등장합니다. 일부 글은 "답을 기다리는 고민"으로 남기고, AI 이어 답글·고마워요·초대 알림 예시도 들어 있습니다.

## 인증 API

| 메서드 | 경로 | 설명 | 토큰 |
|---|---|---|---|
| GET | /auth/options | 직무·연차·캐릭터·고민 주제·위로 방식 선택지 (FE와 같은 값) | - |
| GET | /auth/nickname?character=tiger | 닉네임 추천 (형용사 + 캐릭터 + 4자리 숫자, 예: 포근한 호랑이 4821) | - |
| POST | /auth/email-code | 인증코드 받기 `{email, purpose: signup/login}` → `{expires_in, resend_after, demo_code}` | - |
| POST | /auth/email-code/verify | 코드가 맞는지만 확인 (소모하지 않음) `{email, purpose, code}` → 204 | - |
| POST | /auth/signup | 회원가입 (비밀번호 없음, `code` 필수. 캐릭터·개인정보 동의 필수, 연차 선택: `""`이면 선택 안 함). 응답에 `access_token` 포함 | - |
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

모든 시각(`created_at` 등)은 UTC이며 끝에 `Z`가 붙어서 나갑니다 (예: `2026-11-17T08:30:00Z`). FE는 `new Date(값)`으로 그대로 읽으면 됩니다.

## 서비스 API (모두 토큰 필요)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | /islands | 내 직무섬 + 통합섬, 7일 고민 수, 새 댓글 여부 |
| GET | /islands/{id}/neighbors | 지도에 띄울 이웃 캐릭터 + 최근 고민 |
| GET | /islands/{id}/posts | 최근 고민 목록 (`comfort_type`, `q`, `limit`, `before_id`, `waiting=true`면 이웃 댓글이 없는 글만) |
| PATCH | /users/me | 프로필 수정 (`character`, `nickname`, `accept_invites`). 캐릭터만 바꾸면 닉네임 자동 재생성 |
| GET | /users/me/summary | 내 활동 요약 `{post_count, comment_count, thanks_received, posts_helped}` |
| GET | /users/{id}/profile?island_id= | 간단 프로필 |
| GET | /users/{id}/posts?island_id= | 이웃 한 명의 공개 고민 |
| GET | /users/me/posts | 내 고민 (나만 보기 포함, `visibility` 필터) |
| GET | /users/me/comments | 내가 쓴 댓글 |
| POST | /posts/check | 게시 전 미리 검사 (저장 안 함) `{title, content}` → `{ok, reason, suggestion, issues, crisis}` |
| POST | /posts | 고민 작성 (게시 전 검사, 반려 시 422 `{code, reason, suggestion, issues}`, 위기 신호면 201 + `crisis_support`) |
| PATCH | /posts/{id} | 내 고민 수정 (내용 변경·공개 전환 시 다시 검사) |
| DELETE | /posts/{id} | 내 고민 삭제 |
| GET | /search?q=&island_id= | 비슷한 고민 검색 (임베딩 유사도 순, 결과 없으면 `empty: true` + 추천 키워드) |
| GET | /search/keywords | 자주 찾는 키워드 (토큰 불필요) |
| GET | /posts/{id} | 고민 상세 + 댓글 + 공감 (내 글이면 알림 읽음 처리) |
| POST | /posts/{id}/comments | 댓글·답글 작성 `{content, parent_id?}` (부적절하면 422 `NEED_EDIT`, 위기 신호면 `crisis_support`). 글쓴이가 AI 댓글에 답글을 달면 AI가 이웃이 올 때까지 이어서 답글 (대화당 10번, 하루 30번, 이웃이 오면 한 번 이어 주고 멈춤, `ai_reply_pending`) |
| POST | /posts/{id}/comments/{comment_id}/thanks | 글쓴이가 이웃 댓글에 고마워요 토글 → `{thanked}`. 이웃에게 `thanks` 알림 |
| GET | /posts/{id}/similar | 이 글과 비슷하면서 이웃 답이 달린 글 최대 3개 (`similarity` 포함) |
| DELETE | /posts/{id}/comments/{comment_id} | 내 댓글만 삭제 (남의 댓글은 403). 상세에는 `is_deleted: true`, "삭제된 댓글입니다"로 남음 |
| POST | /posts/{id}/reactions | 공감 토글 |
| GET | /notifications | 알림 목록 + 안 읽은 수 (`limit`, `before_id`) |
| POST | /notifications/read | 읽음 처리 (`{"post_id": 1}` 또는 `{}`로 전체) |
| POST | /reports | 신고 `{target_type: post/comment, target_id, reason}`. 3점이면 AI 재검사 후 가리거나 검토 대기, 6점이면 가림 (새 계정은 0.5점) |
| POST | /reports/appeal | 가려진 내 글·댓글 이의 제기 `{target_type, target_id, reason}` (한 번만) |
| GET | /admin/moderation?state=open | 운영진 전용: 신고 대기열 (이의 제기 먼저). `protected: true`면 운영진이 복구한 뒤 내용이 그대로인 글이라 자동으로 가려지지 않음 |
| POST | /admin/moderation/{case_id} | 운영진 전용: `{action: hide/restore}` |
| GET | /blocks | 내가 차단한 사람 |
| POST | /blocks | 차단 `{user_id}` |
| DELETE | /blocks/{user_id} | 차단 해제 |

## 지표 API (발표용, 토큰 불필요)

`GET /stats/impact` → 공개 고민 수, 첫 반응까지 걸린 시간(중앙값, 분), 이웃 반응 수, AI 대화 수, 고마워요 받은 댓글 수, 초대 수와 초대 후 이웃 답이 달린 글 수, 신고 검토·복구 수

## 보안 · 테스트

- 위협별 대응과 확인 테스트: [SECURITY.md](SECURITY.md)
- AI 사용과 검증 기록: [docs/AI_USAGE.md](docs/AI_USAGE.md)
- `pip install -r requirements-dev.txt` 후 `pytest -q` (87개, CI는 SQLite와 PostgreSQL 양쪽). CI는 push마다 테스트·`pip-audit`·`gitleaks` 실행

## 환경변수

`.env.example`을 `.env`로 복사해서 채우면 자동으로 읽힙니다.

| 이름 | 기본값 |
|---|---|
| ENV | dev (배포 시 `production`: 이때 SECRET_KEY가 없으면 서버가 켜지지 않음) |
| DATABASE_URL | sqlite:///./ganzithon.db (배포는 Supabase의 Session pooler 주소를 Render 대시보드에 입력. `postgres://`·`postgresql://`는 psycopg 드라이버 주소로 자동 변환되고, Supabase 주소는 SSL이 자동으로 켜짐) |
| SECRET_KEY | 개발용 값 (배포 시 반드시 변경) |
| ACCESS_TOKEN_EXPIRE_MINUTES | 1440 (1일) |
| CORS_ORIGINS | 로컬 개발 주소(5500·5173·3000). 배포 시 프론트 주소를 쉼표로 |
| TRUST_PROXY | 0 (Render처럼 프록시 뒤면 1: 요청 제한에 실제 사용자 IP 사용) |
| RATE_LIMIT_ENABLED | 1 (요청 횟수 제한, 표는 SECURITY.md) |
| REPORT_HIDE_THRESHOLD | 3 (이 점수면 AI 재검사, 문제 있으면 가리고 아니면 운영 검토) |
| REPORT_FORCE_HIDE_THRESHOLD | 6 (이 점수면 바로 가림. 운영진이 복구한 글은 내용이 바뀌기 전까지 자동으로 가리지 않음) |
| REPORT_TRUSTED_ACCOUNT_HOURS | 24 (가입 후 이 시간이 지나야 신고 1점, 그 전에는 0.5점) |
| ADMIN_EMAILS | 없음 (운영진 이메일, 쉼표로 여러 개) |
| AI_FOLLOWUP_MAX | 10 (대화 하나에 AI 이어 답글 최대 횟수) |
| AI_DAILY_REPLY_LIMIT | 30 (작성자 한 명당 24시간 AI 이어 답글 수) |
| INVITE_MAX_PER_POST | 3 (새 글마다 초대할 비슷한 고민 작성자 수) |
| INVITE_DAILY_PER_USER | 3 (한 사람이 24시간 동안 받는 초대 수) |
| UPSTAGE_API_KEY | 없음 (AI 기능용, 서버에만 설정) |
| EMAIL_MODE | demo (`smtp`면 실제 메일 발송) |
| SMTP_HOST / SMTP_PORT | smtp.gmail.com / 465 (587이면 STARTTLS) |
| SMTP_USER / SMTP_PASSWORD | 없음 (Gmail은 계정 주소 / 앱 비밀번호) |
| SMTP_FROM | SMTP_USER와 같음 |
| GEMINI_API_KEY | 없음 (Upstage 대신 Gemini를 쓸 때) |
| AI_PROVIDER | auto (`upstage` / `gemini` / `local`) |
| SEARCH_MIN_SIMILARITY | 제공사별 기본값 (upstage 0.30, gemini 0.55, local 0.12) |
| DEMO_JOB | 개발 (배포 시작 때 넣는 시연 데이터의 직무) |

## 배포 (Render)

1. Supabase에서 프로젝트를 만듭니다(지역: Seoul `ap-northeast-2`, DB 비밀번호는 길게 무작위로). 대시보드 > Connect > **Session pooler** 주소를 복사합니다. Direct connection 주소는 IPv6 전용이라 Render에서 접속이 안 될 수 있습니다.
2. Render 대시보드 > New > Blueprint > 이 레포 선택 → `render.yaml` 설정으로 서버가 만들어집니다. 만들 때 `DATABASE_URL`에 1번 주소를 넣습니다.
3. `UPSTAGE_API_KEY`, `CORS_ORIGINS`, `ADMIN_EMAILS`는 대시보드에서 직접 입력합니다. `SECRET_KEY`는 Render가 자동으로 만듭니다.
4. 시작 명령은 `python deploy_start.py`입니다. DB에 시연 데이터가 없을 때(처음 한 번)만 `demo_seed.py` → `demo_seed_b.py`(임베딩)를 실행하고 서버를 띄웁니다. 그 뒤로는 재배포해도 데이터가 그대로 남습니다.
5. FE 배포 주소가 정해지면 `CORS_ORIGINS`를 그 주소로 바꿉니다.

무료 서버는 15분 동안 요청이 없으면 잠들었다가 첫 요청에 30초~1분이 걸립니다(데이터는 Supabase에 남음). 시연 직전에 `/health`를 한 번 열어 깨워 두세요. Supabase 무료 프로젝트는 일주일 넘게 요청이 없으면 일시 정지되니, 정지됐다면 Supabase 대시보드에서 다시 켭니다(요금·조건은 Supabase에서 확인).

시연 데이터를 처음 상태로 되돌리려면 내 PC에서 `.env`의 `DATABASE_URL`을 Supabase 주소로 잠깐 바꾸고 `python demo_seed.py --job 개발 --reset && python demo_seed_b.py`를 실행합니다.

## AI 기능 (B, `app/ai/`)

- 고민 작성 흐름: 검사(`check_text`) → 저장 → [백그라운드] 임베딩(`embed`) → AI 첫 댓글(`write_first_comment`, 공개 글만, `is_ai=true`)
- 검사는 규칙(전화번호·이메일·주민번호·대표 회사명·욕설·위기 표현)을 항상 돌리고, LLM 결과가 5초 안에 오면 합친다. AI가 실패·429여도 게시는 된다.
- 나만 보기 글은 반려하지 않고 위기 신호만 확인한다. AI 첫 댓글·검색에서도 빠진다.
- 프롬프트는 `app/ai/prompts.py`에서 고친다.
