# API 명세 (FE 연결용)

요청·응답 전체 모양은 서버의 `/docs`(Swagger)에서 확인할 수 있습니다. 여기에는 FE가 알아야 할 규칙만 적었습니다.

## 0. 공통 규칙

| 항목 | 내용 |
|---|---|
| 형식 | 요청·응답 모두 JSON (`Content-Type: application/json`) |
| 인증 | 로그인·가입 응답의 `access_token`을 `Authorization: Bearer <토큰>` 헤더로 보냄 |
| 401 | 토큰 만료·무효 → 토큰을 지우고 로그인 화면으로 |
| 에러 | `{"detail": 문장 또는 객체, "code": "NOT_FOUND"}`. 분기는 `code`로 (`UNAUTHORIZED, FORBIDDEN, NOT_FOUND, CONFLICT, VALIDATION_ERROR, NEED_EDIT, RATE_LIMITED, PAYLOAD_TOO_LARGE, INTERNAL_ERROR`). 422 `VALIDATION_ERROR`는 `detail`이 배열 |
| 429 | 요청이 너무 많음. `Retry-After` 헤더(초)만큼 버튼을 잠그고 남은 시간을 보여 주세요 |
| 500 | `detail`은 고정 문구. 그대로 토스트로 보여 주면 됩니다 |
| 시각 | UTC, 끝에 `Z` (`new Date(값)`으로 읽으면 한국 시간) |
| 선택지 | 직무·연차·캐릭터·주제·위로 방식은 `GET /auth/options` |

값 대응: 캐릭터 `rat, ox, tiger, rabbit, dragon, snake, horse, sheep, monkey, rooster, dog, pig, lion`, 위로 방식 `empathy, experience, opinion`, 공개 범위 `public / private`.

## 1. 가입 · 로그인 (이메일 인증코드)

```
가입:   POST /auth/email-code → POST /auth/email-code/verify → POST /auth/signup (토큰 받음)
로그인: POST /auth/email-code → POST /auth/login (토큰 받음)
```

| API | 내용 |
|---|---|
| `POST /auth/email-code` `{email, purpose:"signup"/"login"}` | `{expires_in:300, resend_after:60, demo_code}`. 시연 모드면 `demo_code`에 코드가 옴. 409 이미 가입 / 404 미가입 / 429 60초 안 재요청 |
| `POST /auth/email-code/verify` `{email, purpose, code}` | 204 맞음, 400 틀림(남은 횟수 포함). **코드를 소모하지 않음** → 같은 코드로 가입 |
| `GET /auth/nickname?character=tiger` | `{nickname:"포근한 호랑이 4821"}`. 닉네임은 자유 입력 없이 이것으로만 뽑음 |
| `POST /auth/signup` `{email, code, job, years, character, nickname, agree_privacy}` | 201 `{..., access_token}` → **바로 로그인 상태**. 400 코드 오류 / 409 중복 / 422 형식·미동의 |
| `POST /auth/login` `{email, code}` | `{access_token}` |
| `GET /auth/me` | `{id, email, job, years, nickname, character}` |
| `POST /auth/logout` · `DELETE /auth/me` | 204 (로그아웃 · 탈퇴) |
| `PATCH /users/me` `{character?, nickname?}` | 캐릭터만 보내면 닉네임을 새로 만들어 줌. 422 형식·동물 불일치 / 409 중복 |

## 2. 섬 · 이웃 · 고민 목록

| API | 내용 |
|---|---|
| `GET /islands` | `[{id, type:"common"/"job", name, is_mine, post_count, has_new_comment}]` |
| `GET /islands/{id}/posts?comfort_type=&q=&limit=&before_id=&waiting=` | `{posts, user_ids, next_before_id}`. `next_before_id`가 `null`이면 끝. `waiting=true`면 아직 이웃 댓글이 없는 고민만. 각 글의 `waiting: true`면 "답을 기다리는 고민" 배지 |
| `GET /islands/{id}/neighbors` | `[{author, latest_post, post_count, is_me}]` |
| `GET /users/{user_id}/profile?island_id=` · `/users/{user_id}/posts?island_id=` | 이웃 프로필 · 이웃의 공개 고민 |

## 3. 고민 글

| API | 내용 |
|---|---|
| `POST /posts/check` `{title, content}` | **게시 전 점검 화면에서 사용.** `{ok, reason, suggestion, issues, crisis}`. `ok:false`면 게시 버튼 잠금 |
| `POST /posts` `{island_id, topic, title, content, comfort_type, visibility, show_years}` | 201 `{id, ..., crisis_support}`. 문제 표현이 있으면 422 `NEED_EDIT` |
| `GET /posts/{id}` | 상세 + 댓글. 수정·삭제 버튼은 `is_mine`일 때만. `status: "hidden"`이면 신고 누적으로 가려진 글(작성자만 보임) |
| `PATCH /posts/{id}` · `DELETE /posts/{id}` | 본인만 가능 (아니면 403) |
| `POST /posts/{id}/reactions` | 공감 켜기·끄기 `{reacted, reaction_count}` |

- 422 `NEED_EDIT`: `detail = {code, message, reason, suggestion, issues:[{type, text, start, end, guide}]}`. `start`/`end`는 "제목 + 줄바꿈 + 본문" 기준 위치(못 찾으면 `null`).
- `crisis_support`가 있으면 글은 게시된 상태입니다. 상담 연락처를 보여 주세요.
- 나만보기 글은 검사로 막지 않습니다.

## 4. 댓글

| API | 내용 |
|---|---|
| `POST /posts/{id}/comments` `{content, parent_id?}` | 400자 이내. `parent_id`를 넣으면 답글. 문제 표현이면 422 `{code:"NEED_EDIT", reason, suggestion}` |
| `DELETE /posts/{id}/comments/{cid}` | 내 댓글만 (AI·다른 사람 댓글은 403) |
| `POST /posts/{id}/comments/{cid}/thanks` | 글쓴이만. 이웃 댓글에 "고마워요" 토글 → `{thanked}`. AI·내 댓글은 404, 남의 글이면 403 |
| `GET /posts/{id}/similar` | 이 글과 비슷하고 이웃 답이 달린 글 최대 3개 (`PostSummary` + `similarity`). 없으면 `[]` |

댓글: `{id, content, is_ai, is_deleted, is_hidden, thanked, parent_id, author, is_mine, created_at}`. 삭제·가려진 댓글과 AI 댓글은 `author: null`.

- **답글**: 목록은 평평한 배열입니다. `parent_id`가 `null`이면 댓글, 값이 있으면 그 댓글의 답글입니다. 답글의 답글을 보내도 서버가 맨 위 댓글로 묶어 줍니다(한 단계 들여쓰기만 그리면 됨).
- **AI 이어 답글**: 글쓴이가 AI 댓글(또는 그 답글)에 답글을 달면 응답에 `ai_reply_pending: true`가 옵니다. 1~3초 뒤 `GET /posts/{id}`를 다시 불러 "온도가 답글을 쓰고 있어요" 표시를 바꿔 주세요. 온도는 이웃이 올 때까지 계속 함께합니다(대화당 10번, 하루 30번). 이웃 댓글이 달리면 한 번 "이웃의 이야기도 읽어 보세요"로 이어 주고 멈춥니다. 응답이 `ai_reply_pending: false`면 "이제 이웃들이 함께할 거예요" 안내를 보여 주세요.
- **위기 신호**: 댓글·답글 응답에 `crisis_support`가 있으면 글과 같은 상담 안내(109, 1577-0199)를 띄워 주세요.
- **가려진 댓글**: `is_hidden: true`면 "신고가 쌓여 가려진 댓글입니다"를 회색으로.
- **고마워요**: 내 글의 이웃 댓글에만 버튼을 보여 주고, `thanked: true`면 채워진 하트로.

## 5. 검색 · 마이페이지 · 알림 · 신고 · 차단

| API | 내용 |
|---|---|
| `GET /search?q=&island_id=` | `{items, user_ids, empty, fallback}`. `q`는 2자 이상 |
| `GET /search/keywords` | 추천 키워드 |
| `GET /users/me/posts?visibility=` · `GET /users/me/comments` | 내 글(`has_unread`) · 내 댓글(`post_id: null`이면 볼 수 없는 글) |
| `GET /users/me/summary` | `{post_count, comment_count, thanks_received, posts_helped}` 마이페이지 상단 "내가 도운 고민 N개, 고마워요 N개" |
| `PATCH /users/me {accept_invites}` | 비슷한 고민 초대 알림 받기 켜기·끄기 (`GET /auth/me`의 `accept_invites`) |
| `GET /notifications` · `POST /notifications/read {post_id?}` | `{notifications, unread_count, next_before_id}` · 읽음 처리(비우면 전체). `type`: `comment`(내 글에 댓글) / `reply`(내 댓글에 답글, AI 이어 답글 포함) / `reaction` / `invite`(내 예전 고민과 비슷한 새 고민, 눌러서 그 글로) / `thanks`(글쓴이가 내 댓글에 고마워요) / `hidden`(내 글·댓글이 가려짐) / `restored`(운영진이 다시 보이게 함). `is_ai`는 AI 댓글·답글 알림만 true |
| `POST /reports {target_type, target_id, reason}` | 신고. 바로 가려지지 않고 AI 재검사·운영 검토를 거칩니다. 성공하면 "신고가 접수됐어요. 확인 후 조치할게요" |
| `POST /reports/appeal {target_type, target_id, reason}` | `hidden` 알림을 받은 작성자의 이의 제기 (한 번만, 두 번째는 409) |
| `GET /stats/impact` (토큰 불필요) | 발표용 지표: 첫 반응까지 걸린 시간(중앙값), 이웃 반응 수, AI 대화 수, `thanked_comments`, `invites_sent`, `invited_posts_answered`, `reports_reviewed`, `reports_restored` |
| `GET /blocks` · `POST /blocks {user_id}` · `DELETE /blocks/{user_id}` | 차단 목록·차단·해제 |

## 6. FE 남은 작업 (11/18 BE 보강 기준, 심사 만점용)

**필수 (시연 흐름과 결선 보안 점수에 직결)**
- [ ] 답글 UI: 댓글마다 "답글" 버튼, `parent_id`로 묶어 한 단계 들여쓰기
- [ ] AI 이어 답글: 글쓴이가 AI 댓글에 답하면 `ai_reply_pending`일 때 "온도가 답글을 쓰고 있어요…" 표시 → 1.5초 간격으로 최대 5번 `GET /posts/{id}` 다시 불러오기
- [ ] 댓글·답글 응답의 `crisis_support`도 글과 같은 상담 안내 팝업으로 표시
- [ ] `is_hidden` 댓글은 회색 안내 문구로, `status: "hidden"` 내 글에는 "신고가 쌓여 가려졌어요" 표시
- [ ] `api.js`: `code`로 분기, 429는 `Retry-After`초 동안 버튼 잠금 + 남은 시간 안내, 응답이 JSON이 아닐 때(`response.json()` 실패)도 안전하게 처리
- [ ] 첫 화면에서 `GET /health`를 먼저 호출해 Render 깨우기 + "서버를 깨우는 중" 로딩 문구
- [ ] `innerHTML`에 들어가는 서버 값은 전부 `escapeText`를 거치는지 한 번 더 점검 (닉네임·제목·본문·댓글·검색어·알림 제목)
- [ ] FE 배포 주소가 정해지면 BE 담당에게 알려 `CORS_ORIGINS`에 등록

**활용성 (콜드스타트·재방문)**
- [ ] 글 상세 아래 "비슷한 고민을 먼저 겪은 이웃들" 카드 (`GET /posts/{id}/similar`, 비어 있으면 숨김)
- [ ] 이웃 댓글에 "고마워요" 버튼(글쓴이만), 받은 쪽 알림 문구 "글쓴이가 내 댓글에 고마워했어요"
- [ ] 알림 `invite` 문구 "비슷한 고민을 가진 이웃이 글을 올렸어요. 경험을 나눠 줄래요?" → 누르면 그 글로
- [ ] 마이페이지 상단 `GET /users/me/summary` 카드 + 설정에 "비슷한 고민 초대 받기" 토글
- [ ] `hidden` 알림이면 "이의 제기" 버튼 → 사유 입력 → `POST /reports/appeal`. `restored` 알림 문구도

**점수 올리는 것**
- [ ] 섬 목록에 "답을 기다리는 고민" 탭(`waiting=true`)과 카드 배지(`waiting`) → 콜드스타트 해결을 눈에 보이게
- [ ] 유사 검색 결과에 `similarity`를 "비슷한 정도 ●●●○" 같은 단계로 표시
- [ ] 게시 전 점검 화면: `issues[].start/end`로 문제 구간 하이라이트 + `guide` 문장, "고쳐서 다시 점검" 버튼
- [ ] 알림 `type: "reply"` 문구("내 댓글에 답글이 달렸어요" / AI면 "온도가 답했어요")
- [ ] 신고 사유 선택 모달, 차단 확인 모달, 차단 목록에서 해제
- [ ] 로딩·빈 화면·오류 상태를 모든 목록에 (스켈레톤 또는 문구)
- [ ] 모바일 폭(360px)에서 지도·모달이 잘리지 않는지 확인, 버튼 44px 이상, 이미지 `alt`, 키보드 포커스
- [ ] `village.js`와 `unified-island.js`의 겹치는 코드(약 1,900줄씩)를 공통 파일로 분리 → 코드 품질 점수
- [ ] `index.html`들에 `<meta http-equiv="Content-Security-Policy">` 추가 (script는 self, connect는 API 주소만)

**발표용**
- [ ] `GET /stats/impact` 숫자를 발표 자료에 사용 (첫 반응까지 걸린 시간 중앙값 등)
- [ ] 인터넷이 끊길 때를 대비한 2분 시연 영상 (글 작성 → 게시 전 점검 → AI 첫 댓글 → 답글하면 온도가 이어 답함 → 비슷한 이웃에게 초대 알림 → 이웃 댓글 → 온도가 이웃에게 넘김 → 고마워요)
