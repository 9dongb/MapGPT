# AGENT.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 5. 가상환경 사용

**가상환경은 conda 환경을 사용하세요.**

가상환경명: mapgpt

## 6. 작업 완료 시 커밋 생성

**변경 사항을 검토하고, 가능한 검증을 수행한 뒤 하나의 커밋을 생성한다.**

코딩 작업이 완료된 경우:
- 커밋 전에 최종 diff를 검토한다.
- 가능한 경우 관련 테스트나 린트 명령을 실행한다.
- 검증 결과를 사용자에게 요약한다.
- 완료된 작업에 대해 하나의 커밋을 생성한다.

커밋 단위:
- 기본적으로 하나의 사용자 요청에서 발생한 변경은 하나의 커밋으로 정리한다.
- 단, 서로 독립적으로 이해되거나 되돌릴 수 있는 변경이 명확하고, 각각이 별도의 검증 가능한 목적을 가진 경우에는 논리적 단위별로 커밋을 나눌 수 있다.
- 단순한 구현 변경과 그에 필요한 테스트 추가는 같은 논리적 변경으로 보고 하나의 커밋에 포함한다.
- 리팩터링과 기능 변경은 가능한 경우 분리한다.
- 포맷 변경과 기능 변경은 가능한 경우 분리한다.
- 사용자가 하나의 커밋을 명시적으로 요청한 경우에는 가능한 한 하나의 커밋으로 정리한다.
- 사용자가 커밋 분리를 명시적으로 요청한 경우에는 요청한 기준에 따라 커밋을 나눈다.

커밋 규칙:
- 구현, 버그 수정, 리팩터링, 테스트 추가 등 코드 변경이 발생한 경우 커밋을 생성한다.
- 커밋 메시지는 변경 내용을 명확히 설명하는 한국어 문장으로 작성한다.
- 여러 독립적인 변경이 포함되었더라도, 사용자가 별도로 요청하지 않는 한 최종적으로 하나의 커밋으로 정리한다.
- 커밋을 만들 수 없는 상황이라면 그 이유를 명확히 설명하고, 커밋하지 않은 변경 사항을 요약한다.

커밋 전 확인:
- `git diff`를 확인하여 의도하지 않은 변경이 포함되지 않았는지 점검한다.
- 작업 과정에서 새로 발생한 미사용 import, 변수, 함수는 제거한다.
- 요청과 무관한 정리, 리팩터링, 포맷 변경은 포함하지 않는다.