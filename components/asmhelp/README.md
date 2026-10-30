# asmhelp

`asmhelp` is a deliberately small, fully offline terminal reference for the
x86-64 GNU/AT&T assembly, System V calling convention, GDB, and binary tools
used in CMSC216.

```console
asmhelp                    # show the complete course-scoped topic list
asmhelp mov
asmhelp cmpq
asmhelp div                # signed and unsigned division recipe
asmhelp remainder          # alias for the same division page
asmhelp signed comparison  # local full-text search
asmhelp regs
asmhelp stack
asmhelp gdb memory
```

There are no subcommands to learn: everything after `asmhelp` is a topic,
instruction spelling, alias, or search phrase. An exact alias opens its page. A
search with one match opens that page; several matches produce a short list.

The editable textual database is [`topics.toml`](topics.toml). It is derived
from the local CMSC216 GDB/assembly reference and Labs 04–07. It intentionally
omits x86 instructions and architecture topics outside that course material.
The installed program never uses the network, an LLM, embeddings, or another
backend; it performs deterministic alias and full-text searches over the
packaged TOML file.

Interactive output uses `$MANPAGER`/`$PAGER`, falling back to `less`. Piped
output is plain text. Set `ASMHELP_PAGER=cat` to disable paging.
