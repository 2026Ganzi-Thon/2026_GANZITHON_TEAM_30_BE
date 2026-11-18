# 2026_GANZITHON_TEAM_30_BE

FastAPI + SQLAlchemy(SQLite) 백엔드

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
| GET | /islands/{id}/posts | 최근 고민 목록 (`comfort_type`, `q`, `limit`, `before_id`) |
| PATCH | /users/me | 프로필 수정 (`character`, `nickname`). 캐릭터만 바꾸면 닉네임 자동 재생성 |
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
| GEMINI_API_KEY | 없음 (Upstage 대신 Gemini를 쓸 때) |
| AI_PROVIDER | auto (`upstage` / `gemini` / `local`) |
| SEARCH_MIN_SIMILARITY | 제공사별 기본값 (upstage 0.30, gemini 0.55, local 0.12) |
| DEMO_JOB | 개발 (배포 시작 때 넣는 시연 데이터의 직무) |

## 배포 (Render)

1. Render 대시보드 > New > Blueprint > 이 레포 선택 → `render.yaml` 설정으로 서버가 만들어집니다.
2. `UPSTAGE_API_KEY`만 대시보드에서 직접 입력합니다. `SECRET_KEY`는 Render가 자동으로 만듭니다.
3. 시작 명령은 `python deploy_start.py`입니다. DB에 시연 데이터가 없으면 `demo_seed.py` → `demo_seed_b.py`(임베딩)를 실행한 뒤 서버를 띄웁니다.
4. FE 배포 주소가 정해지면 `CORS_ORIGINS`를 그 주소로 바꿉니다.

무료 플랜은 재시작·재배포 때 SQLite 파일이 초기화되고, 15분 동안 요청이 없으면 잠들었다가 첫 요청에 30초~1분이 걸립니다. 시연 직전에 `/health`를 한 번 열어 깨워 두세요.

## AI 기능 (B, `app/ai/`)

- 고민 작성 흐름: 검사(`check_text`) → 저장 → [백그라운드] 임베딩(`embed`) → AI 첫 댓글(`write_first_comment`, 공개 글만, `is_ai=true`)
- 검사는 규칙(전화번호·이메일·주민번호·대표 회사명·욕설·위기 표현)을 항상 돌리고, LLM 결과가 5초 안에 오면 합친다. AI가 실패·429여도 게시는 된다.
- 나만 보기 글은 반려하지 않고 위기 신호만 확인한다. AI 첫 댓글·검색에서도 빠진다.
- 프롬프트는 `app/ai/prompts.py`에서 고친다.
