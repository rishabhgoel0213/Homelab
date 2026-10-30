# asmhelp

`asmhelp` is a fully offline, terminal-first x86-64 instruction manual focused
on GNU assembler (AT&T) syntax.

```console
asmhelp mov
asmhelp cmpq
asmhelp lea
asmhelp search 'conditional jump'
asmhelp syntax
asmhelp list
```

Interactive output uses the configured `$MANPAGER`/`$PAGER`, falling back to
`less`. Piped output is plain text. Set `ASMHELP_PAGER=cat` to disable paging.

The pinned dataset is published by [x86-64.net](https://x86-64.net/about/),
generated from Intel XED and Clang, and includes forms, encodings, operand
access, flags, ISA sets, extension metadata, and concise original summaries.
The package preserves its attribution notice. `asmhelp` generates an AT&T view
and adds hand-checked quick references for commonly used instructions.

Generated AT&T forms are a convenience layer, not a replacement for GNU `as`
in exceptional syntax families. Pages explicitly call out the x87, `ENTER`,
far-control-transfer, and newly introduced instruction caveat, and retain the
source XED/Intel form and encoding beside every generated form.
