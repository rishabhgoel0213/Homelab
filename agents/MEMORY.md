# Curated Agent Memory

This file contains only stable, deliberately retained cross-conversation
decisions. It is maintained in `/srv/ops`; agents must not append to it unless
the user explicitly asks to preserve something here.

- Use existing canonical roots instead of creating parallel project or document
  trees.
- Keep infrastructure declarative in `/srv/ops` and runtime state in
  `/srv/state`.
- Keep the agent cockpit free of task output.
- Treat native harness session stores as the complete conversation record; the
  shared index contains metadata only.
- Temporary work expires unless it is deliberately promoted or retained.
- There are currently no configured local harnesses besides Codex.
