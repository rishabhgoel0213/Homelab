# Curated Agent Memory

This file contains only stable, deliberately retained cross-conversation
decisions. It is maintained in `/srv/ops`; agents must not append to it unless
the user explicitly asks to preserve something here.

- Use existing canonical roots instead of creating parallel project or document
  trees.
- Keep infrastructure declarative in `/srv/ops` and runtime state in
  `/srv/state`.
- Create new work in durable projects under `/home/rishabh/Projects`; do not
  create a parallel workspace tree.
- Codex and Pi are configured local harnesses.
