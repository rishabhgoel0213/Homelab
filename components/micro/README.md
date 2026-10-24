# Micro assembly highlighting

Both platform base modules install `package.nix` instead of stock Micro. It
embeds `x86-att.yaml` into Micro's runtime and regenerates the syntax headers
with the upstream build. No user configuration or plugin installation is needed.

Files ending in `.s` or `.S` automatically select `x86-att`: GNU/AT&T assembly
with instruction suffixes, `%` registers, `$` immediates, GAS directives and
labels, strings, and `#`, `//`, and block comments. The instruction field is
highlighted lexically, including newer mnemonics; this is not an assembler or
opcode validator. Uppercase `.S` files also get assembler highlighting, including
preprocessor lines as comments. `.asm` retains the upstream NASM syntax.

Micro's user syntax files and explicit filetype settings still take precedence.
Use `Ctrl+E`, then `set filetype x86-att` to select this syntax manually.

The package build runs `syntax_test.go` against Micro's actual buffer detection
and highlighting engine, checking `.s`, `.S`, `.asm`, and C detection plus AT&T
tokens and comment/string precedence. Validate with `just check` and
`just darwin-eval`; apply to the server with `just switch`. Mac activation is a
separate `MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy` step.
