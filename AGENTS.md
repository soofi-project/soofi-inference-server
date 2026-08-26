## Rules

- Reduce complexity when solving problems. Always choose the simplest design/architecture that will acomplish the task while respecting requirements.
- If you modify something (or create something new), then update the docs (README, PRD etc.) relevant to the modification if it makes sense.
- If you are implementing something, then use the tdd skill during the implementation phase.
- If you are creating a plan, always include TDD as part of the plan.
- Always create live real integration end-to-end tests (Using the TDD skill) when you are creating or modifying a new feature (if appropiate). And every time you finish implementing/modifying that, run those tests; do not skip them.
- When the user asks you to implement (especially a plan existing in a file) fix or modify something, then interview the user using the grill-me skill, so you can get more details about the task (unless the task is very simple).
- After finishing creating a plan or a PRD then use the grill-me skill to interview the user one more time, so you can confirm that you got all necessary details of the task.
- Only if you are Codex: Always use gpt-5.6-terra model with high reasoning for the subagents that you spawn (e.g for code exploration, web search, testing or implementation (modifying or writing code)).
- Follow YAGNI principles.
- Don't over abstract. Micro classes are most of the time a smell.
- Error handling: Fail early, fail fast, fail loud, never swallow and handle errors gracefully and with meaningful helpful relevant detailed error messages; No silent failures, no generic alert as a catch-all.

Check CLAUDE.md for more info about how to do work in this project.