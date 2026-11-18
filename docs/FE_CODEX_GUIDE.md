# ON-DO FE 작업 가이드 (Codex용)

> 이 파일을 FE 저장소(`2026_GANZITHON_TEAM_30_FE`) 루트에 `AGENTS.md`로 복사해서 쓰세요.
> 기준: FE `deb7b87`, BE `BE-A` 최신. 마감 11/20 23:59.

---

## 0. 규칙 (꼭 지킬 것)

1. **빌드 없는 바닐라 JS**입니다. 프레임워크·npm·번들러·외부 CDN을 추가하지 마세요.
2. **BE는 수정하지 않습니다.** API 응답이 이 문서와 다르면 작업을 멈추고 보고하세요.
3. 서버에서 온 값(닉네임·제목·본문·댓글·알림 제목·검색어)을 `innerHTML`에 넣을 때는 **반드시 `escapeText()`** 를 거칩니다.
4. `js/village.js`와 `js/unified-island.js`는 **거의 같은 파일**입니다(약 1,950줄, 다른 곳 약 20줄). T14를 하기 전까지는 **두 파일에 똑같이** 수정하세요.
5. 작업 하나 = 커밋 하나. 메시지 형식: `feat(FE): T4 답글 UI` / `fix(FE): T1 api.js 응답 처리`.
6. 새 함수는 짧게, 기존 코드 스타일(2칸 들여쓰기, 큰따옴표, `el()`, `toast()`, `api()`)을 따릅니다.
7. 한국어 문구는 이 문서에 적힌 것을 그대로 씁니다.

## 1. 확인하는 방법

1. `index.html`을 브라우저로 엽니다(VS Code Live Server 권장).
2. 로그인 → 이메일 `demo@example.com` → "인증코드 받기" → 화면에 나온 체험용 코드 입력.
   - `neighbor1~15@example.com`, `other1~15@example.com`도 같은 방식으로 로그인됩니다(이웃 역할 테스트용).
3. 서버: `https://ondo-api.onrender.com` (무료라 첫 요청은 최대 50초 걸릴 수 있음). API 문서는 `/docs`.
4. 각 작업의 **완료 기준**을 직접 눌러 보고 확인합니다. 콘솔(F12)에 에러가 없어야 합니다.

## 2. 파일 지도

| 파일 | 역할 | 주로 손댈 작업 |
|---|---|---|
| `js/api.js` | `API` 주소, `errorText()`, `api()`, `logout()` | T1 |
| `js/app.js` | 시작 화면·가입·로그인(이메일 코드) | T2, T17 |
| `js/village.js` | 직무섬: 지도, 피드 `renderFeed()`, 글 상세 `showPost()`, 알림 `loadNotifications()`, 마이페이지 `personal()` | T3~T13 |
| `js/unified-island.js` | 통합섬. village.js 복사본 | T3~T14 |
| `js/island-select.js` | 섬 선택 | - |
| `js/review.js` | 게시 전 점검 브라우저 규칙 | T18 |
| `*.html` | 4개 화면 | T15 |

## 3. 꼭 알아야 할 API 응답 모양

```js
// 댓글 (GET /posts/{id} 의 comments[] 항목)
{ id, content, is_ai, is_deleted, is_hidden, thanked, parent_id, author, is_mine, created_at }
// author: { user_id, nickname, character, job } | null  (AI·삭제·가려진 댓글은 null)
// is_hidden이면 content = "신고가 쌓여 가려진 댓글입니다"

// 댓글 작성 응답 (POST /posts/{id}/comments)
{ ...댓글, crisis_support: { message, resources: [{ name, phone, hours }] } | null, ai_reply_pending: boolean }

// 글 상세 (GET /posts/{id})
{ id, island_id, topic, title, content, comfort_type, visibility, status, author, years, is_mine,
  reaction_count, reacted_by_me, comments: [...] }   // status: "published" | "hidden"

// 글 목록 항목 (GET /islands/{id}/posts)
{ id, title, preview, topic, comfort_type, created_at, comment_count, author, waiting }

// 알림 (GET /notifications)
{ notifications: [{ id, type, post_id, post_title, actor, is_ai, is_read, created_at }], unread_count, next_before_id }
// type: comment | reply | reaction | invite | thanks | hidden | restored

// 에러 (모든 실패 응답)
{ detail: "문장" | { code, message, reason, suggestion, issues } | [ {msg} ], code: "NOT_FOUND" ... }
```

## 4. 작업 목록 (위에서부터 순서대로)

### T1. `api.js` 응답 처리 안전하게 `P0`
- **파일:** `js/api.js`
- **할 일:**
  1. `const data = await response.json();` 를 `try/catch`로 감싸고, 실패하면 `data = {}`.
  2. `!response.ok`일 때 `error.code = data.code`도 넣기.
  3. `response.status === 429`이면 `Retry-After` 헤더(초)를 읽어 `error.retryAfter = Number(...) || 60`, 메시지는 `` `요청이 많아요. ${error.retryAfter}초 뒤 다시 시도해 주세요.` ``
  4. `response.status >= 502`이고 JSON이 아니면 메시지 `"서버가 깨어나는 중이에요. 잠시 뒤 다시 시도해 주세요."`
- **완료 기준:** 서버가 HTML 에러를 줘도 화면이 멈추지 않고 문구가 나온다. 같은 이메일로 인증코드를 60초 안에 다시 요청하면 남은 초가 표시된다.

### T2. 첫 화면에서 서버 깨우기 `P0`
- **파일:** `js/app.js` (페이지 로드 시점), 필요하면 `index.html`
- **할 일:** 페이지가 열리면 바로 `fetch(API + "/health")`를 한 번 보냄(결과 무시, 실패해도 조용히). 시작 버튼 아래 작은 문구 `"서버를 깨우는 중이에요…"` → 응답 오면 숨김.
- **완료 기준:** 서버가 잠든 상태에서 첫 화면을 열면 문구가 보였다가 사라진다.

### T3. 댓글 그리기 함수 분리 + 가려진/삭제 댓글 정리 `P0`
- **파일:** `village.js`, `unified-island.js` → `showPost()` 안의 `comments.map(...)`
- **할 일:**
  1. `comments.map` 안의 템플릿을 `function renderComment(comment, post)` 로 뺀다(T4·T8에서 재사용).
  2. `comment.is_hidden || comment.is_deleted` 이면: 이름·아바타·신고·삭제 버튼 **모두 숨기고** `<p class="muted">${escapeText(comment.content)}</p>` 만. 색은 `#888`.
  3. 이름: `is_ai`면 `"온도 · AI 이웃"`, 아니면 `author.nickname`. `author`가 null인데 위 두 경우가 아니면 `"떠난 이용자"`.
  4. 신고 버튼은 `!is_mine && !is_ai && !is_hidden && !is_deleted` 일 때만.
- **완료 기준:** 가려진 댓글에 "떠난 이용자"와 신고 버튼이 보이지 않는다.

### T4. 답글 UI `P0`
- **파일:** `showPost()`
- **할 일:**
  1. 댓글을 묶기: `const roots = comments.filter(c => !c.parent_id)`, `const childrenOf = id => comments.filter(c => c.parent_id === id)`.
  2. 루트 댓글 아래에 답글들을 `<div class="reply child">`(왼쪽 여백 24px)로 **한 단계만** 들여쓰기.
  3. 숨김·삭제가 아닌 루트 댓글마다 `답글` 버튼(`data-reply-to="${comment.id}"`).
  4. 누르면 아래 입력창(`#reply`)에 포커스, 입력창 위에 `"○○님에게 답글 · 취소"` 표시, 전송 시 body에 `parent_id` 추가. 취소하면 `parent_id` 제거.
  5. 답글의 답글 버튼을 눌러도 `parent_id`는 그 답글의 id를 보내면 됩니다(서버가 맨 위 댓글로 묶음).
- **완료 기준:** AI 댓글에 답글을 달면 그 아래 들여쓰기로 보인다.

### T5. AI 이어 답글 기다리기 `P0` (콜드스타트 핵심)
- **파일:** `showPost()` 안 `form.onsubmit`
- **할 일:**
  1. 댓글 작성 응답을 `const result = await api(...)` 로 받는다.
  2. `result.ai_reply_pending === true`면 댓글 목록 끝에 `"온도가 답글을 쓰고 있어요…"` 표시 후, **1.5초 간격 최대 5번** `showPost(post.id, false)` 다시 호출. 새 AI 댓글(`is_ai && parent_id`)이 늘어나면 멈춤.
  3. 글쓴이가 AI 댓글(또는 그 답글)에 답했는데 `ai_reply_pending === false`면 toast `"이제 이웃들이 함께할 거예요"`.
  4. 폴링 중 상세 창을 닫거나 다른 글을 열면 멈춤(`detailRequestId` 비교).
- **완료 기준:** `demo@example.com`으로 내 글의 AI 댓글에 답글 → 몇 초 안에 온도의 답글이 자동으로 나타난다.

### T6. 댓글에도 위기 안내 `P0`
- **파일:** `showPost()` 안 `form.onsubmit`
- **할 일:** 글 작성에 있는 `crisis_support` 처리(village.js `result?.crisis_support` 부분)를 `function showCrisisSupport(support)`로 빼고, 댓글 작성 응답에도 호출.
- **완료 기준:** 댓글에 "죽고 싶어요"를 쓰면 상담 안내(109, 1577-0199)가 뜬다.

### T7. 알림 type별 문구 `P0`
- **파일:** `loadNotifications()`
- **할 일:** `"새 댓글"` 고정 문구와 `"떠난 이용자"`를 아래 표로 교체. `actor`가 null이어도 "떠난 이용자"라고 쓰지 않는다.

  | type | 문구 | 이름 표시 |
  |---|---|---|
  | `comment` | `is_ai` ? "온도가 첫 댓글을 남겼어요" : "내 고민에 댓글이 달렸어요" | `is_ai` ? "온도" : `actor.nickname` |
  | `reply` | `is_ai` ? "온도가 답했어요" : "내 댓글에 답글이 달렸어요" | 위와 같음 |
  | `reaction` | "이웃이 내 고민에 공감했어요" | `actor.nickname` |
  | `invite` | "비슷한 고민을 가진 이웃이 글을 올렸어요. 경험을 나눠 줄래요?" | 없음 |
  | `thanks` | "글쓴이가 내 댓글에 고마워했어요" | 없음 |
  | `hidden` | "신고가 쌓여 내 글이나 댓글이 가려졌어요" | 없음 |
  | `restored` | "검토 결과 문제가 없어 다시 보이게 했어요" | 없음 |

  읽지 않은 알림은 앞에 `●`. 누르면 지금처럼 `post_id` 글을 연다.
- **완료 기준:** `demo@example.com` 알림함에서 종류별로 다른 문구가 보인다.

### T8. 고마워요 버튼 `P1`
- **파일:** `renderComment()`
- **할 일:** `post.is_mine && !comment.is_ai && !comment.is_mine && !comment.is_hidden && !comment.is_deleted`일 때 버튼 `${comment.thanked ? "♥ 고마워요" : "♡ 고마워요"}`. 누르면 `POST /posts/${post.id}/comments/${comment.id}/thanks` → 응답 `{thanked}`로 버튼만 갱신.
- **완료 기준:** 내 글의 이웃 댓글에서 눌렀다 뗐다 할 수 있고, 새로고침해도 유지된다.

### T9. 비슷한 고민 카드 `P1`
- **파일:** `showPost()` 끝부분
- **할 일:** 상세를 그린 뒤 `GET /posts/${post.id}/similar` → 배열이 비면 아무것도 안 그림. 있으면 댓글 영역 위에 `"비슷한 고민을 먼저 겪은 이웃들"` 제목 + 카드 최대 3개(제목, `preview`, `답글 ${comment_count}`, `similarityDots(similarity)`). 카드를 누르면 `showPost(그 id)`.
- `similarityDots(s)`: `s >= 0.6` → `●●●●`, `>= 0.5` → `●●●○`, `>= 0.4` → `●●○○`, 그 외 `●○○○` (서버는 약 0.3 이상만 보내므로 이 구간이 적당합니다).
- **완료 기준:** 시연 계정 글을 열면 비슷한 글 카드가 보이고 눌러서 이동된다.

### T10. 답을 기다리는 고민 `P1`
- **파일:** `renderFeed()` + 필터 영역 HTML
- **할 일:**
  1. 필터 옆에 토글 버튼 `"답을 기다리는 고민"`. 켜면 `params.set("waiting", "true")`.
  2. 글 카드에 `post.waiting`이면 작은 배지 `"답을 기다려요"`.
- **완료 기준:** 토글을 켜면 이웃 댓글이 없는 글만 나오고, 배지가 보인다.

### T11. 마이페이지 요약 + 초대 설정 `P1`
- **파일:** `personal()`, `setupProfileSettings()`
- **할 일:**
  1. 마이페이지 상단에 `GET /users/me/summary` → `"내가 도운 고민 ${posts_helped}개 · 받은 고마워요 ${thanks_received}개 · 쓴 글 ${post_count} · 쓴 댓글 ${comment_count}"`.
  2. 설정 탭에 체크박스 `"비슷한 고민 초대 받기"`. 초기값은 `GET /auth/me`의 `accept_invites`, 바꾸면 `PATCH /users/me { accept_invites }`.
- **완료 기준:** 숫자가 보이고, 토글을 바꾸고 새로고침해도 유지된다.

### T12. 가려진 글 배너 + 이의 제기 `P1`
- **파일:** `showPost()`, `renderComment()`
- **할 일:**
  1. `post.is_mine && post.status === "hidden"`이면 제목 위에 배너 `"신고가 쌓여 가려졌어요. 다른 이웃에게는 보이지 않아요."` + `이의 제기` 버튼.
  2. 내 댓글이 `is_hidden`이면 그 자리에 `이의 제기` 버튼.
  3. 누르면 `prompt("이의 제기 사유를 적어 주세요. (1~200자)")` → `POST /reports/appeal { target_type: "post" | "comment", target_id, reason }` → 204면 toast `"이의 제기를 보냈어요. 운영진이 확인할게요"`. 409면 서버 문구 그대로.
- **완료 기준:** 이의 제기 1번은 성공, 2번째는 "이미 이의를 제기했어요" 문구.

### T13. 신고 문구·모달 `P2`
- **파일:** 글·댓글 신고 버튼 핸들러
- **할 일:** 성공 toast를 `"신고가 접수됐어요. 확인 후 조치할게요"`로 통일. 가능하면 `prompt` 대신 사유 선택 `<dialog>`(욕설·비방 / 개인정보 노출 / 광고·도배 / 기타 직접 입력).
- **완료 기준:** 신고 후 바로 글이 사라지지 않고 문구가 나온다.

### T14. 중복 코드 정리 `P2` (코드 품질 점수)
- **파일:** 새 `js/island-core.js`, `village.js`, `unified-island.js`, `village.html`, `unified-island.html`
- **할 일:**
  1. 두 파일의 차이는 ① `const key = "ondo-village-v1"` / `"ondo-unified-v1"` ② 섬 이름 표시(약 10줄) ③ 내 댓글 목록의 `post_id === null` 처리(**village.js 쪽이 맞음**) 뿐입니다.
  2. 공통 코드를 `island-core.js`로 옮기고, 다른 부분은 `window.ISLAND_CONFIG = { storageKey, title(me) }` 로 받게 한다.
  3. 각 html은 `api.js → review.js → island-core.js` 순서로 로드하고, `village.js`/`unified-island.js`는 설정만 남기거나 삭제.
- **완료 기준:** 직무섬·통합섬 둘 다 기존 기능이 그대로 동작하고, 같은 코드가 한 곳에만 있다.

### T15. CSP 추가 `P0` (결선 보안 점수)
- **파일:** 4개 html의 `<head>` 맨 위
- **할 일:**
  ```html
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://ondo-api.onrender.com; base-uri 'self'; form-action 'self'; object-src 'none'">
  ```
  인라인 `<script>`나 `onclick="..."`가 생기면 막히므로 JS 파일 안에서 이벤트를 연결합니다(현재는 없음).
- **완료 기준:** 모든 화면이 정상 동작하고 콘솔에 CSP 위반 에러가 없다.

### T16. 로그인 503 처리 확인 `P0`
- **파일:** `js/app.js` 로그인 코드 요청 부분
- **내용:** 운영 서버에서 실제 회사 이메일로 로그인 코드를 요청하면 `503`, `code: "EMAIL_UNAVAILABLE"`, `detail.message`가 옵니다(남의 이메일로 로그인 코드를 받아 가는 것을 막기 위해서). 지금 코드는 `error.message`를 `loginStatus`에 보여 주므로 문구는 이미 나옵니다. **코드 입력칸으로 포커스가 넘어가지 않는지, 재전송 타이머가 돌지 않는지만** 확인하세요.
- **완료 기준:** `@example.com`이 아닌, 가입된 실제 이메일로 로그인 코드를 요청하면 안내 문구만 나오고 멈춘다. (BE 최신 배포 후 확인 가능)

### T17. 체험 계정 버튼 `P1` (심사위원용)
- **파일:** `index.html`, `js/app.js`
- **할 일:** 로그인 화면에 `"체험 계정으로 둘러보기"` 버튼. 누르면 이메일 칸에 `demo@example.com`을 채우고 코드 요청 → 응답의 `demo_code`를 코드 칸에 채우고 로그인까지 자동 진행.
- **완료 기준:** 버튼 한 번으로 직무섬까지 들어간다.

### T18. 게시 전 점검 하이라이트 `P2`
- **파일:** 글쓰기 `editor()` 안 `renderReview()`
- **할 일:** 서버 결과 `issues[]`의 `start`/`end`(제목 + `"\n"` + 본문 기준 위치, null일 수 있음)로 미리보기에서 해당 구간을 `<mark>`로 감싸고, 옆에 `guide` 문장. 감쌀 때도 각 조각은 `escapeText()`.
- **완료 기준:** 욕설이 들어간 글을 점검하면 그 단어가 형광펜으로 보인다.

### T19. 상태 화면·접근성 `P2`
- 모든 목록에 로딩 / 빈 화면 / 오류 문구가 있는지 확인(피드, 이웃, 알림, 내 글, 내 댓글, 차단 목록, 비슷한 고민).
- 360px 폭에서 지도·모달 잘림 없음, 버튼 높이 44px 이상, 아이콘 버튼에 `aria-label`, 의미 있는 이미지에 `alt`.

### T20. README 갱신 `발표`
- **파일:** `README.md`
- **할 일:** 지금 README는 "브라우저에 저장, 외부 AI 호출 안 함"이라고 되어 있어 **사실과 다릅니다.** 아래로 교체:
  - 서비스 한 줄 소개, FE 배포 주소, BE 주소(`https://ondo-api.onrender.com/docs`)
  - 체험 계정 `demo@example.com` (코드는 화면에 표시됨)
  - 주요 기능: 직무섬·통합섬, 게시 전 AI 점검, AI 첫 댓글·이어 답글, 비슷한 고민 연결·초대, 고마워요, 신고·이의 제기
  - 파일 구성 표(T14 반영)
- **완료 기준:** 심사위원이 README만 보고 바로 체험할 수 있다.

## 5. 끝나면 할 일

1. 2분 시연 흐름을 한 번 끝까지 돌려 본다:
   글 작성 → 게시 전 점검 → AI 첫 댓글 → 답글 → 온도 이어 답글 → 비슷한 고민 카드 → 이웃 계정으로 댓글 → 고마워요 → 알림 → 마이페이지 요약
2. FE 배포 주소를 BE 담당에게 알려 Render `CORS_ORIGINS`에 등록한다.
3. 발표 자료 숫자는 `GET https://ondo-api.onrender.com/stats/impact` 에서 가져온다.
