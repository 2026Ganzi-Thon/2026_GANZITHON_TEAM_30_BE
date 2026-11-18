# AI 사용과 검증 기록

ON-DO는 AI를 두 곳에서 씁니다. 하나는 **서비스 기능 안의 AI**(Upstage Solar)이고, 다른 하나는 **개발 도구로서의 AI**(코딩 도우미)입니다. 아래에 각각 어디에 쓰고 어떻게 검증했는지 남깁니다.

## 1. 서비스 안의 AI

| 기능 | 모델 | 실패했을 때 | 검증 |
|---|---|---|---|
| 게시 전 검사(개인정보·욕설·위기) | `solar-mini4` JSON 모드 | 규칙 검사만으로 판단하고, 게시는 막지 않습니다. | `test_llm_detection_is_merged`, `test_llm_failure_falls_back_to_rules_and_post_still_publishes` |
| AI 첫 댓글(위로 방식별) | `solar-mini4` | 위로 방식별 기본 문장을 씁니다. | `test_first_comment_uses_llm_and_adds_hotline_for_crisis` |
| AI 이어 답글(이웃이 올 때까지, 대화당 10번·하루 30번) | `solar-mini4` | 기본 문장을 쓰고, 이웃이 오면 이웃에게 대화를 넘기는 문장으로 마무리합니다. | `test_ai_keeps_company_until_limit`, `test_ai_hands_off_once_a_neighbor_arrives`, `test_ai_daily_reply_limit_per_author` |
| 신고 재검사 | 게시 전 검사와 같은 모델 | 규칙 검사 결과로 판단하고, 애매하면 가리지 않고 운영 검토로 넘깁니다. | `test_ai_flag_hides_at_first_threshold`, `test_reports_below_force_threshold_wait_for_review_instead_of_hiding` |
| 비슷한 이웃 초대·비슷한 고민 | `embedding-passage` | 초대를 건너뛰고 빈 목록을 돌려줍니다. 글 작성은 막지 않습니다. | `test_similar_neighbors_are_invited_unless_they_opt_out`, `test_similar_posts_show_only_answered_experiences` |
| 유사 고민 검색 | `embedding-query` / `embedding-passage` | "결과 없음" 안내와 추천 키워드를 보여 줍니다. | `test_similar_search_block_filter_and_empty_result` |

### AI 결과를 그대로 믿지 않는 장치

1. **입력 보호**: 연락처를 가리고 `<user_text>` 태그로 감싼 뒤 보냅니다. 프롬프트 인젝션 대응은 [SECURITY.md](../SECURITY.md)의 T17, T18을 보세요.
2. **출력 검사**:
   - JSON이 깨지면 한 번 다시 요청합니다(실측 깨짐 약 8%).
   - 반말이 섞이면 다시 씁니다(실측 약 7%).
   - 개인정보나 욕설이 들어 있으면 다시 쓰고, 그래도 안 되면 기본 문장을 씁니다.
   - 위기 글에 상담 번호가 빠지면 번호를 붙입니다.
3. **시간 제한**:
   - 게시 전 검사는 사용자가 기다리는 동안 하므로 8초로 제한합니다.
   - 댓글 생성과 임베딩은 백그라운드에서 15초로 제한합니다. 시간을 넘기면 대체 동작으로 넘어갑니다.
4. **비용 통제**: 사용자별 요청 횟수 제한을 두고, AI 이어 답글은 작성자당 하루 30번으로 묶습니다(SECURITY.md 3절, T27). 나만 보기 글에는 AI 댓글을 달지 않고 임베딩도 만들지 않습니다.

## 2. 개발 도구로서의 AI(코딩 도우미)

AI가 만든 코드는 아래 순서로 검증한 뒤에만 반영했습니다.

| 단계 | 내용 |
|---|---|
| 읽기 | 사람이 diff를 직접 읽고, 권한 검사·쿼리·예외 처리 부분을 확인합니다. |
| 테스트 | 기능마다 정상, 권한 없음, 비정상 입력 테스트를 함께 작성합니다. `pytest -q`로 SQLite에서 87개가 통과했고, 로컬 PostgreSQL 16에서도 전체 테스트(당시 85개)가 통과했습니다(2026-11-18). CI는 push마다 두 DB에서 모두 돌립니다. |
| 의존성 | AI가 제안한 새 라이브러리는 받지 않았습니다. 요청 횟수 제한도 외부 패키지 없이 직접 구현했습니다(`app/ratelimit.py`). 모든 버전을 고정하고 `pip-audit`으로 검사합니다. |
| 비밀값 | 코드와 문서에 실제 키를 넣지 않습니다. gitleaks를 CI에서 돌립니다. |

### 검증하면서 실제로 발견하고 고친 문제

| 발견 | 수정 |
|---|---|
| 신고로 가려진 글을 작성자가 수정하면 다시 "게시됨"으로 바뀌어 공개됨 | 가려진 상태를 유지하도록 고쳤습니다. 테스트: `test_force_threshold_hides_post_and_edit_keeps_it_hidden` |
| 신고 3건이면 바로 가려져서 새 계정 몇 개로 멀쩡한 글을 숨길 수 있었음 | 새 계정 0.5점, AI 재검사, 운영 검토, 이의 제기로 바꿨습니다. 테스트: `test_new_accounts_count_half_so_sock_puppets_cannot_hide` |
| 가려진 글에 걸린 알림이 남의 알림 목록에 제목째 보일 수 있었음 | 내 글이 아니면 공개·게시 상태인 글의 알림만 보여 줍니다. |
| 섬 목록 검색어에 `%`를 넣으면 모든 글이 검색됨(LIKE 와일드카드) | 이스케이프 처리했습니다. 테스트: `test_sql_injection_and_like_wildcards_are_harmless` |
| 422 응답이 사용자 입력값을 그대로 돌려줌 | `input` 필드를 빼서 반환하도록 고쳤습니다. 테스트: `test_invalid_input_is_rejected_without_echoing_it` |
| AI 첫 댓글에 전화번호가 섞여도 그대로 저장될 수 있었음 | AI 결과에도 규칙 검사를 적용했습니다. 테스트: `test_ai_output_that_breaks_rules_is_replaced` |
| 외부 LLM에 사용자 원문(연락처 포함)이 그대로 전송됨 | 가린 뒤 보내도록 고쳤습니다. 테스트: `test_personal_info_is_masked_before_reaching_llm` |
| 테스트 파일 하나가 DB 주소를 SQLite로 강제로 바꿔서, Postgres로 돌려도 실제로는 SQLite에서 테스트됨 | 환경변수가 있으면 그대로 쓰도록 고치고, 로컬 PostgreSQL 16에서 85개 통과와 DB에 데이터가 실제로 생긴 것까지 확인했습니다. CI에 `test-postgres` 작업을 추가했습니다. |
| 시연 데이터가 AI 이어 답글을 이웃 댓글보다 나중에 넣어서, 발표 때 AI가 답하지 않을 뻔함 | 넣는 순서를 바꾸고 `test_demo_seed_fills_every_island_with_worried_neighbors`에서 확인합니다. |
| CI가 `pytest`를 바로 실행하면 `app` 모듈을 못 찾아 테스트 전체가 실행되지 않음(로컬은 `python -m pytest`라 통과) | `pytest.ini`에 `pythonpath = .`를 넣어 어떻게 실행해도 같게 만들었습니다. |
| `.env.example`에 `CORS_ORIGINS=*`가 기본값으로 들어 있었음 | 허용 목록 방식으로 바꿨습니다. 테스트: `test_security_headers_and_cors_allowlist` |
