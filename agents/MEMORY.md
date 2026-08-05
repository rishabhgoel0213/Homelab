# Curated Agent Memory

This file contains only stable, deliberately retained cross-conversation
decisions. It is maintained in `/srv/ops`; agents must not append to it unless
the user explicitly asks to preserve something here.

- Use existing canonical roots instead of creating parallel project or document
  trees.
- Keep infrastructure declarative in `/srv/ops` and runtime state in
  `/srv/state`.
- Keep the agent cockpit free of task output.
- Treat native harness session stores as the authoritative conversation record.
  The shared metadata and full-text indexes are derived and rebuildable.
- Temporary work expires unless it is deliberately promoted or retained.
- Codex and Pi are configured local harnesses. Shared history ingestion is
  source-neutral; Pi is the first configured cross-harness destination.
