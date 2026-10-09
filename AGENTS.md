## Rules

- Always choose the simplest design/architecture that will acomplish the task while respecting requirementsx, taking into account that maintainability and modularity are very important.
- If you modify something (or create something new), then update the docs (README, PRD etc.) relevant to the modification if it makes sense.
- When the user asks you to implement (especially a plan existing in a file) fix or modify something, then interview the user using the grilling skill, so you can get more details about the task (unless the task is very simple).
- After finishing creating a plan or a PRD then use the grilling skill to interview the user one more time, so you can confirm that you got all necessary details of the task.
- Keep maintainability and modularity in mind when implementing or planning.
- Only if you are Codex: Use generic subagents for independent, read-heavy investigations when doing the work in the main thread would add significant noisy context. Guidelines:

  * Prefer 1–3 focused subagents.

  * Keep final decisions and implementation coordination in the main agent.
  * Delegate independent, bounded tasks.

  * Prefer read-only subagents; keep implementation centralized when practical.

  * Do not recursively spawn subagents unless the delegated task genuinely contains multiple independent large investigations.

  * Do not duplicate investigation across agents.

  * Return concise findings, file/line references, conclusions, and unresolved questions.
  * Do not return raw logs or large file contents.

examples of when to use subagents:
  * codebase exploration
  * finding implementations/call sites
  * test execution
  * log analysis
  * reviewing diffs
  * web search
  * researching APIs/documentation
  * analyzing large files
  * stack traces
  * command output 

Use gpt-6-luna model with max reasoning for the subagents.

- Follow YAGNI principles.
- Don't over abstract. Micro classes are most of the time a smell.
- If you are implementing or modifying something related to code (not when modifying a text or .md document or such kind of actions), then use the tdd skill during the implementation phase.
- If you are creating a plan related to implementing or modifying something related to code (not when modifying a text or .md document or such kind of actions), always include TDD (as described by the tdd skill) as part of the plan.
- Always create live real integration end-to-end tests (Using the tdd skill) when you are creating or modifying a new feature (if appropiate i.e related to code). And every time you finish  /modifying that, run those tests; do not skip them.
- Error handling: Fail early, fail fast, fail loud, never swallow and handle errors gracefully and with meaningful helpful relevant detailed error messages; No silent failures, no generic alert as a catch-all.