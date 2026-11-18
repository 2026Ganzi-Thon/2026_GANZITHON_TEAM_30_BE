# API 명세 (FE 연결용)

요청·응답 전체 모양은 서버의 `/docs`(Swagger)에서 확인할 수 있습니다. 여기에는 FE가 알아야 할 규칙만 적었습니다.

## 0. 공통 규칙

| 항목 | 내용 |
|---|---|
| 형식 | 요청·응답 모두 JSON (`Content-Type: application/json`) |
| 인증 | 로그인·가입 응답의 `access_token`을 `Authorization: Bearer <토큰>` 헤더로 보냄 |
| 401 | 토큰 만료·무효 → 토큰을 지우고 로그인 화면으로 |
| 에러 | `{"detail": "문장"}`. 입력 형식 오류(422)는 `detail`이 배열 |
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
| `GET /islands/{id}/posts?comfort_type=&q=&limit=&before_id=` | `{posts, user_ids, next_before_id}`. `next_before_id`가 `null`이면 끝 |
| `GET /islands/{id}/neighbors` | `[{author, latest_post, post_count, is_me}]` |
| `GET /users/{user_id}/profile?island_id=` · `/users/{user_id}/posts?island_id=` | 이웃 프로필 · 이웃의 공개 고민 |

## 3. 고민 글

| API | 내용 |
|---|---|
| `POST /posts/check` `{title, content}` | **게시 전 점검 화면에서 사용.** `{ok, reason, suggestion, issues, crisis}`. `ok:false`면 게시 버튼 잠금 |
| `POST /posts` `{island_id, topic, title, content, comfort_type, visibility, show_years}` | 201 `{id, ..., crisis_support}`. 문제 표현이 있으면 422 `NEED_EDIT` |
| `GET /posts/{id}` | 상세 + 댓글. 수정·삭제 버튼은 `is_mine`일 때만 |
| `PATCH /posts/{id}` · `DELETE /posts/{id}` | 본인만 가능 (아니면 403) |
| `POST /posts/{id}/reactions` | 공감 켜기·끄기 `{reacted, reaction_count}` |

- 422 `NEED_EDIT`: `detail = {code, message, reason, suggestion, issues:[{type, text, start, end, guide}]}`. `start`/`end`는 "제목 + 줄바꿈 + 본문" 기준 위치(못 찾으면 `null`).
- `crisis_support`가 있으면 글은 게시된 상태입니다. 상담 연락처를 보여 주세요.
- 나만보기 글은 검사로 막지 않습니다.

## 4. 댓글

| API | 내용 |
|---|---|
| `POST /posts/{id}/comments` `{content}` | 400자 이내. 문제 표현이면 422 `{reason, suggestion}` |
| `DELETE /posts/{id}/comments/{cid}` | 내 댓글만 (AI·다른 사람 댓글은 403) |

댓글: `{id, content, is_ai, is_deleted, author, is_mine, created_at}`. 삭제된 댓글과 AI 댓글은 `author: null`.

## 5. 검색 · 마이페이지 · 알림 · 신고 · 차단

| API | 내용 |
|---|---|
| `GET /search?q=&island_id=` | `{items, user_ids, empty, fallback}`. `q`는 2자 이상 |
| `GET /search/keywords` | 추천 키워드 |
| `GET /users/me/posts?visibility=` · `GET /users/me/comments` | 내 글(`has_unread`) · 내 댓글(`post_id: null`이면 볼 수 없는 글) |
| `GET /notifications` · `POST /notifications/read {post_id?}` | `{notifications, unread_count, next_before_id}` · 읽음 처리(비우면 전체) |
| `POST /reports {target_type, target_id, reason}` | 신고 |
| `GET /blocks` · `POST /blocks {user_id}` · `DELETE /blocks/{user_id}` | 차단 목록·차단·해제 |

## 6. FE 남은 작업 (11/18 검수 기준)

- [ ] 게시 전 점검 화면에서 `POST /posts/check` 결과 사용 (지금은 욕설 글이 "통과"로 보임)
- [ ] 가입 응답의 `access_token`으로 바로 로그인 (지금은 가입 후 코드를 다시 받음)
- [ ] 코드 입력 직후 `POST /auth/email-code/verify`로 확인
- [ ] `js/api.js`의 `API` 주소를 배포 서버 주소로 변경
