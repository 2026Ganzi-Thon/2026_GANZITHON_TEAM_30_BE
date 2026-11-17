# FE ↔ BE API 연결 가이드

FE(localStorage)를 BE API로 바꿀 때 필요한 내용만 정리했습니다.
요청과 응답의 전체 모양은 서버를 띄운 뒤 `http://<서버주소>:8000/docs`(Swagger)에서 확인할 수 있습니다.

---

## 0. 공통 규칙

| 항목 | 내용 |
|---|---|
| 서버 주소 | `const API = "http://<BE 주소>:8000"` 하나로 모아서 사용 (BE가 시연 주소를 알려 드림) |
| 형식 | 요청과 응답 모두 JSON. 요청에는 `Content-Type: application/json` 헤더를 붙임 |
| 인증 | 로그인하면 `access_token`을 받음. localStorage에 저장하고, 이후 모든 요청에 `Authorization: Bearer <토큰>` 헤더를 붙임 |
| 토큰 만료·무효 | 응답이 `401`이면 토큰을 지우고 로그인 화면으로 보냄 |
| CORS | 모든 출처를 허용해 두었음. 따로 설정할 필요 없음 |
| 시각 | 모든 `created_at`은 UTC이고 끝에 `Z`가 붙음 (예: `2026-11-17T08:30:00Z`). `new Date(값)`으로 읽으면 브라우저가 한국 시간으로 바꿔 줌 |
| 에러 메시지 | 대부분 `{"detail": "사람이 읽을 문장"}` 형태라서 `detail`을 그대로 alert하면 됨. 입력 형식 오류(422)는 `detail`이 배열임 |

```js
// 공통 fetch 함수 예시
const API = "http://localhost:8000";

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem("ondo-token");
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(API + path, { method, headers, body: body && JSON.stringify(body) });
  if (res.status === 401 && auth) {
    localStorage.removeItem("ondo-token");
    location.href = "index.html";
    return;
  }
  if (res.status === 204) return null; // 삭제·로그아웃처럼 응답 본문이 없는 경우
  const data = await res.json();
  if (!res.ok) throw { status: res.status, detail: data.detail };
  return data;
}

// 에러 문장 꺼내기: 422 형식 오류는 배열, 나머지는 문자열
const errorText = (d) => (Array.isArray(d) ? d[0].msg : typeof d === "string" ? d : d.message || d.reason);
```

---

## 1. FE 값 → BE 값 대응표

FE는 지금 번호(index)를 저장하고, BE는 영어 키를 씁니다. 순서가 같아서 배열 하나로 바꾸면 됩니다.

```js
// characterNames와 같은 순서 (assets/characters/0~12.png)
const CHARACTER_KEYS = ["rat","ox","tiger","rabbit","dragon","snake","horse","sheep","monkey","rooster","dog","pig","lion"];
// ways와 같은 순서
const COMFORT_KEYS = ["empathy", "experience", "opinion"];

// FE → BE: CHARACTER_KEYS[animal], COMFORT_KEYS[way]
// BE → FE: CHARACTER_KEYS.indexOf(character), COMFORT_KEYS.indexOf(comfort_type)
```

| FE (지금) | BE | 비고 |
|---|---|---|
| `animal` (0~12) | `character` (`"rat"` 등) | 위 배열로 변환 |
| `nick` | `nickname` | 형식이 정해져 있음 (2장 참고) |
| `way` (0~2) | `comfort_type` (`"empathy"` 등) | 위 배열로 변환 |
| `body` | `content` | |
| `private: true/false` | `visibility: "private"/"public"` | |
| 연차 공개 체크박스 | `show_years: true/false` | 연차 값은 서버가 가입 정보에서 가져옴 |
| `years: ""` (선택 안 함) | `years: ""` 또는 `null` | 둘 다 "연차 없음"으로 저장됨 |
| `jobNames` | `"디자인"`, `"영업"`, `"개발"` | **FE 목록에 "영업"이 빠져 있음** |

직무, 연차, 캐릭터, 고민 주제, 위로 방식의 정답 목록은 `GET /auth/options` 한 번으로 받을 수 있습니다.

---

## 2. 회원가입 · 로그인 (비밀번호 없음, 이메일 인증코드)

### 흐름
```
[이메일 입력] → POST /auth/email-code  → [코드 6자리 입력] → POST /auth/signup  (가입)
                                                         → POST /auth/login   (로그인, 토큰 받음)
```
가입이 끝나도 토큰은 나오지 않습니다. 가입 후에는 **로그인용 코드를 한 번 더 받아서** 로그인합니다.

### 2-1. 인증코드 받기 `POST /auth/email-code` (토큰 필요 없음)
```js
await api("/auth/email-code", { method: "POST", auth: false,
  body: { email, purpose: "signup" } }); // 로그인할 때는 "login"
// → { expires_in: 300, resend_after: 60, demo_code: "123456" | null }
```
- **시연 모드**에서는 메일이 가지 않고 `demo_code`에 코드가 담겨 옵니다. 값이 있으면 화면에 "체험용 인증코드: 123456"처럼 보여 주세요. 실제 메일 모드에서는 `null`입니다.
- 코드는 5분 동안 유효합니다. 다시 받으려면 60초를 기다려야 합니다. "재전송" 버튼을 `resend_after`초 동안 비활성화해 주세요.

| 상태 코드 | 뜻 |
|---|---|
| 409 | (signup) 이미 가입한 이메일 → 로그인 화면으로 안내 |
| 404 | (login) 가입하지 않은 이메일 → 가입 화면으로 안내 |
| 429 | 60초 안에 다시 요청함 |
| 502 | 메일 발송 실패 |

### 2-2. 닉네임 추천 `GET /auth/nickname?character=tiger`
```js
const { nickname } = await api(`/auth/nickname?character=${CHARACTER_KEYS[animal]}`, { auth: false });
// → { nickname: "포근한 호랑이 4821", character: "tiger" }
```
- 닉네임 형식은 **형용사 + 캐릭터 + 4자리 숫자**입니다 (예: `포근한 호랑이 4821`).
- **자유 입력은 받지 않습니다.** 닉네임 입력칸을 읽기 전용으로 두고 "다시 뽑기" 버튼으로 이 API를 다시 부르면 됩니다.
- 캐릭터를 바꾸면 닉네임도 다시 뽑아야 합니다. 닉네임 속 동물과 캐릭터가 다르면 422가 납니다.
- FE의 `adjectives` 목록은 BE와 같습니다. 그래도 숫자와 중복 검사가 필요하니 BE 추천값을 쓰는 것이 안전합니다.

### 2-3. 가입 `POST /auth/signup`
```js
await api("/auth/signup", { method: "POST", auth: false, body: {
  email, code,                       // 2-1에서 받은 6자리
  job: "개발",
  years: "1~3년",                    // 선택 안 함이면 "" 또는 null
  character: CHARACTER_KEYS[animal],
  nickname,                          // 2-2 추천값. 빼면 서버가 자동으로 만들어 줌
  agree_privacy: true,               // ★ 개인정보 동의 체크박스. false면 가입 불가
}});
// → 201 { id, email, job, years, nickname, character }
```
| 상태 코드 | 뜻 |
|---|---|
| 400 | 코드가 틀림, 만료됨, 또는 5번 틀려서 폐기됨 (`detail`에 남은 횟수가 나옴) |
| 409 | 이메일이나 닉네임이 이미 사용 중 → 닉네임을 다시 뽑게 함 |
| 422 | 닉네임 형식 오류, `agree_privacy=false`, 잘못된 직무나 연차 |

> 가입이 실패하면 코드는 소모되지 않습니다. 5분 안이라면 같은 코드로 다시 시도할 수 있습니다.

### 2-4. 로그인 `POST /auth/login`
```js
const { access_token } = await api("/auth/login", { method: "POST", auth: false, body: { email, code } });
localStorage.setItem("ondo-token", access_token);
const me = await api("/auth/me"); // { id, email, job, years, nickname, character }
```
지금 localStorage의 `ondo-profile`에 저장하는 내용은 `GET /auth/me` 응답으로 대신하면 됩니다.

### 2-5. 로그아웃 · 탈퇴
- `POST /auth/logout` → 204. 그다음 FE에서 토큰을 지웁니다.
- `DELETE /auth/me` → 204. 회원 탈퇴입니다. 탈퇴한 사람의 글은 "떠난 이용자"로 표시됩니다.

---

## 3. 프로필 수정 `PATCH /users/me` (설정 탭)

바꿀 필드만 보내면 됩니다.

```js
// ① 캐릭터만 변경 → 서버가 새 캐릭터로 닉네임을 다시 만들어 줌
await api("/users/me", { method: "PATCH", body: { character: "rabbit" } });

// ② 닉네임만 변경 (먼저 /auth/nickname?character=<현재 캐릭터>로 추천받은 값)
await api("/users/me", { method: "PATCH", body: { nickname: "다정한 토끼 5555" } });

// ③ 둘 다 변경
await api("/users/me", { method: "PATCH", body: { character: "rat", nickname: "졸린 쥐 1234" } });
// → 200 { id, email, job, years, nickname, character }  ← 이 값으로 화면 갱신
```
- 지금 설정 탭에 있는 닉네임 자유 입력칸(`profileNick`)은 **읽기 전용 + "다시 뽑기" 버튼**으로 바꿔야 합니다.
- 422는 형식 오류나 동물 불일치, 409는 다른 사람이 쓰는 닉네임입니다.
- 직무와 연차는 섬 배정과 연결되어 있어 바꿀 수 없습니다.

---

## 4. 섬 · 이웃 · 고민 목록

| API | 설명 |
|---|---|
| `GET /islands` | 내가 갈 수 있는 섬 목록. `[{id, type:"common"/"job", name, is_mine, post_count, has_new_comment}]` |
| `GET /islands/{id}/posts?comfort_type=&q=&limit=&before_id=` | 섬의 공개 고민 목록. `{posts, user_ids, next_before_id}` |
| `GET /islands/{id}/neighbors` | 지도에 띄울 이웃 목록. `[{author, latest_post, post_count, is_me}]` |
| `GET /users/{user_id}/profile?island_id=` | 이웃 캐릭터를 눌렀을 때 보이는 간단 프로필 |
| `GET /users/{user_id}/posts?island_id=` | 이웃 한 명의 공개 고민 |

- `comfort_type` 필터에는 **영어 키**를 넣어야 합니다 (`empathy` 등). 한글을 넣으면 빈 목록이 나옵니다.
- 페이지 넘기기: 응답의 `next_before_id`를 다음 요청의 `before_id`로 넣습니다. `null`이면 끝입니다.
- `author`는 `{user_id, nickname, character, job}` 형태이고, 이메일과 연차는 들어 있지 않습니다.

---

## 5. 고민 글 (작성 · 상세 · 수정 · 삭제)

### 작성 `POST /posts`
```js
const res = await api("/posts", { method: "POST", body: {
  island_id, topic: "워라밸", title, content,
  comfort_type: COMFORT_KEYS[way],
  visibility: isPrivate ? "private" : "public",
  show_years: el("shareYears").checked,
}});
// → 201 { id, island_id, visibility, status, crisis_support: null | {message, resources:[...]} }
```
- `crisis_support`가 있으면 글은 정상 게시된 상태입니다. 이때 상담 연락처 팝업을 띄워 주세요.
- **공개 글**에 개인정보나 공격적 표현이 있으면 저장되지 않고 422가 옵니다.
  ```json
  { "detail": { "code": "NEED_EDIT", "message": "공개 전에 한 번만 고쳐 주세요.",
      "reason": "...", "suggestion": "...",
      "issues": [{ "type": "PERSONAL_INFO", "text": "010-1234-5678", "start": 12, "end": 25, "guide": "..." }] } }
  ```
  `issues[].start`와 `end`로 문제 구절에 하이라이트를 칠 수 있습니다. 위치를 못 찾으면 `null`입니다.
- 글을 쓰면 AI가 첫 댓글을 자동으로 달아 줍니다.

### 상세 `GET /posts/{id}`
`{ id, island_id, topic, title, content, comfort_type, visibility, status, created_at, updated_at, author, years, is_mine, reaction_count, reacted_by_me, comments: [...] }`
- `years`는 글쓴이가 연차 공개를 켰을 때만 값이 있고, 아니면 `null`입니다.
- 수정과 삭제 버튼은 `is_mine === true`일 때만 보여 주세요.

### 수정 `PATCH /posts/{id}` · 삭제 `DELETE /posts/{id}`
- 수정할 때는 바꿀 필드만 보냅니다 (`title`, `content`, `topic`, `comfort_type`, `visibility`, `show_years`).
- **글쓴이 본인만** 할 수 있고, 다른 사람이면 403입니다. 삭제하면 204가 오고, 이후 조회하면 404입니다.

### 공감 `POST /posts/{id}/reactions`
누를 때마다 켜짐과 꺼짐이 바뀝니다. 응답은 `{ reacted, reaction_count }`입니다.

---

## 6. 댓글

| API | 설명 |
|---|---|
| `POST /posts/{id}/comments` `{content}` | 작성. 최대 400자. 문제 표현이 있으면 422 `{"detail":{"reason","suggestion"}}` |
| `DELETE /posts/{id}/comments/{cid}` | **내 댓글만** 삭제 가능 (다른 사람 댓글과 AI 댓글은 403) |

댓글 한 개의 모양:
```json
{ "id": 3, "content": "...", "is_ai": false, "is_deleted": false,
  "author": { "user_id": 2, "nickname": "...", "character": "tiger", "job": "개발" },
  "is_mine": true, "created_at": "...Z" }
```
- **삭제된 댓글**은 목록에서 사라지지 않고 `is_deleted: true`, `content: "삭제된 댓글입니다"`, `author: null`로 옵니다. 회색 글씨로 보여 주면 됩니다.
- **AI 댓글**은 `is_ai: true`, `author: null`입니다. AI용 캐릭터와 이름은 FE에서 정해서 보여 주세요.
- 글 목록의 `comment_count`에는 삭제된 댓글이 포함되지 않습니다.

---

## 7. 검색 (AI 유사 고민 찾기)

```js
const r = await api(`/search?q=${encodeURIComponent(q)}&island_id=${islandId}`);
// → { items: [...PostSummary + similarity], user_ids, empty, fallback }
```
- `q`는 2자 이상이어야 합니다.
- `empty: true`이면 `fallback.message`, `fallback.keywords`, 그리고 "이 내용으로 고민 쓰기"용 `fallback.write_prefill.content`를 사용합니다.
- `GET /search/keywords`는 검색창 아래에 띄울 추천 키워드입니다.

---

## 8. 마이페이지 · 알림 · 신고 · 차단

| API | 설명 |
|---|---|
| `GET /users/me/posts?visibility=` | 내 글 (나만 보기 포함). `has_unread`가 true면 새 댓글이 있다는 뜻으로 점 표시 |
| `GET /users/me/comments` | 내 댓글. `post_id`가 `null`이면 볼 수 없는 글 → 클릭 막기 |
| `GET /notifications?limit=&before_id=` | `{notifications, unread_count, next_before_id}` |
| `POST /notifications/read` `{post_id}` | 해당 글 알림을 읽음 처리. `post_id`를 비우면 전체 읽음 |
| `POST /reports` `{target_type:"post"/"comment", target_id, reason}` | 신고 |
| `GET /blocks` · `POST /blocks {user_id}` · `DELETE /blocks/{user_id}` | 차단 목록, 차단, 차단 해제. 차단한 사람의 글과 댓글은 서버에서 빼고 보내 줌 |

---

## 9. FE 작업 체크리스트

- [ ] `API` 주소 상수와 공통 `api()` 함수 추가, 토큰 저장 및 401 처리
- [ ] 가입: 비밀번호 칸 없음, 이메일 → 코드 받기 → 코드 입력, `agree_privacy` 체크박스 추가
- [ ] 시연 모드일 때 `demo_code` 화면에 표시, 재전송 60초 타이머
- [ ] 닉네임: 자유 입력 대신 `GET /auth/nickname`으로 "다시 뽑기" (가입 화면과 설정 탭 모두)
- [ ] 설정 탭 저장 → `PATCH /users/me`
- [ ] `animal`과 `way` 번호를 영어 키로 변환, `body`→`content`, `private`→`visibility`
- [ ] 직무 목록에 "영업" 추가
- [ ] 시각은 `new Date(created_at)`으로 읽어서 표시
- [ ] 글 작성 시 422 `NEED_EDIT` 처리(하이라이트), `crisis_support` 팝업
- [ ] 수정, 삭제 버튼은 `is_mine`일 때만, 삭제된 댓글과 AI 댓글 표시
- [ ] (있으면 좋음) 공감, 신고, 차단, 알림, 탈퇴 UI
