#!/usr/bin/env python3
"""Offline, terminal-first x86-64 AT&T instruction reference."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


DATA = Path(os.environ.get("ASMHELP_DATA", Path(__file__).with_name("insn.json")))
COND = {
    "a", "ae", "b", "be", "c", "e", "g", "ge", "l", "le", "na", "nae",
    "nb", "nbe", "nc", "ne", "ng", "nge", "nl", "nle", "no", "np", "ns",
    "nz", "o", "p", "pe", "po", "s", "z",
}
SIZE_SUFFIX = {"b": "8-bit", "w": "16-bit", "l": "32-bit", "q": "64-bit"}
ACTION = {
    "r": "read", "w": "write", "rw": "read/write", "rcw": "read/conditional write",
    "cw": "conditional write", "cr": "conditional read", "crw": "conditional read/write",
    "addr": "address only", "push": "x87 push", "pop": "x87 pop", "pop2": "x87 pop twice",
}
FLAG_ACTION = {
    "T": "tested", "M": "modified", "TM": "tested/modified", "0": "cleared",
    "1": "set", "U": "undefined", "P": "loaded from stack", "A": "loaded from AH",
}

GUIDES = {
    "add": """Canonical form:
  add{b,w,l,q} source, destination

Examples: `addq %rsi, %rax`, `addl $4, %eax`, `addq $8, (%rsp)`.
ADD stores destination + source in destination and updates arithmetic flags.
At most one explicit operand may be memory.""",
    "sub": """Canonical form:
  sub{b,w,l,q} source, destination

Examples: `subq %rsi, %rax`, `subl $4, %eax`. SUB stores destination - source
in destination and updates arithmetic flags. `subq $8, %rsp` allocates eight
stack bytes; preserve the ABI's required stack alignment around calls.""",
    "and": """Canonical form: `and{b,w,l,q} source, destination`.
Examples: `andq %rsi, %rax`, `andl $0xff, %eax`. AND stores the bitwise result
in destination, clears CF and OF, and updates SF, ZF, and PF.""",
    "or": """Canonical form: `or{b,w,l,q} source, destination`.
Examples: `orq %rsi, %rax`, `orl $1, (%rdi)`. OR stores the bitwise result in
destination, clears CF and OF, and updates SF, ZF, and PF.""",
    "xor": """Canonical form: `xor{b,w,l,q} source, destination`.
Examples: `xorq %rsi, %rax`, `xorl %eax, %eax`. The same-register 32-bit form
is the standard dependency-breaking way to produce zero in a 64-bit register.
XOR clears CF and OF and updates SF, ZF, and PF.""",
    "mov": """Common forms (source first, destination last):
  movb  $imm8, r/m8              movb  %al, (%rdi)
  movw  $imm16, r/m16            movw  %ax, 2(%rdi)
  movl  $imm32, r/m32            movl  $42, %eax
  movq  $imm32, r/m64            movq  %rax, -8(%rbp)
  movabsq $imm64, %rax            movabsq $0x1122334455667788, %rax
  mov{b,w,l,q} r/m, reg           movq  8(%rdi,%rcx,4), %rax

The suffix names the transferred width: b=8, w=16, l=32, q=64 bits. A 32-bit
register write zeroes the upper half of the corresponding 64-bit register.
Memory-to-memory MOV is not encodable. GAS can often infer the suffix from a
register, but spell it out when an operand is memory or an immediate.""",
    "lea": """Canonical form:
  leaq  displacement(base,index,scale), %destination

Examples:
  leaq  8(%rdi,%rsi,4), %rax      # rax = rdi + 4*rsi + 8
  leaq  symbol(%rip), %rdi        # address of symbol (position independent)
  leal  3(%edi,%edi,4), %eax      # eax = 5*edi + 3

LEA computes an address; it does not dereference memory and does not change
flags. Scale is 1, 2, 4, or 8. The source must use memory-address syntax even
when LEA is being used only for arithmetic.""",
    "cmp": """Canonical forms (source first, destination last):
  cmp{b,w,l,q} source, destination

Examples:
  cmpq  %rsi, %rdi                # flags from rdi - rsi
  cmpl  $10, %eax                 # flags from eax - 10
  cmpb  $0, (%rdi)                # compare byte in memory with zero

CMP computes destination - source, discards the result, and updates arithmetic
flags. The order is easy to misread when translating Intel syntax: Intel
`CMP rdi, rsi` is AT&T `cmpq %rsi, %rdi`. Use TEST for bitwise zero checks.""",
    "test": """Canonical forms:
  test{b,w,l,q} source, destination

TEST computes source AND destination, discards the result, and sets flags.
`testq %rax, %rax` is the usual zero/sign test. Unlike CMP, operand order does
not change the mathematical result, though encoding restrictions still apply.""",
    "push": """Common 64-bit form:
  pushq source                    # rsp -= 8; [rsp] = source

Examples: `pushq %rbp`, `pushq $1`, `pushq (%rax)`. In 64-bit mode PUSH uses an
8-byte stack slot (or a 2-byte slot with an operand-size override); there is no
32-bit push encoding.""",
    "pop": """Common 64-bit form:
  popq destination               # destination = [rsp]; rsp += 8

Examples: `popq %rbp`, `popq (%rax)`. Avoid `popq (%rsp)`: the effective address
uses the post-incremented RSP, a special architectural case.""",
    "call": """Forms:
  call label                      # direct PC-relative call
  call *%rax                      # indirect through register
  call *(%rax)                    # indirect through memory

CALL pushes the return address, then transfers control. AT&T marks indirect
call/jump operands with `*`; omitting it changes the meaning or is rejected.""",
    "jmp": """Forms:
  jmp label                       # direct PC-relative jump
  jmp *%rax                       # indirect through register
  jmp *(%rax)                     # indirect through memory

AT&T marks indirect call/jump operands with `*`. Conditional branches use a
condition mnemonic such as `je`, `jne`, `jl` (signed), or `jb` (unsigned).""",
    "jcc": """Canonical form: `jcc target`, replacing `cc` with a condition.

Common conditions after CMP/TEST:
  je/jz   equal/zero (ZF=1)       jne/jnz not equal/nonzero (ZF=0)
  jl/jge  signed < / >=           jle/jg  signed <= / >
  jb/jae  unsigned < / >=         jbe/ja  unsigned <= / >
  js/jns  negative / nonnegative  jo/jno  overflow / no overflow

Signed comparisons interpret SF and OF; unsigned comparisons interpret CF and
ZF. The target is normally a label and uses a PC-relative encoding.""",
    "cmovcc": """Canonical form: `cmovcc{w,l,q} source, %destination`, replacing
`cc` with the same conditions used by Jcc (for example `cmove`, `cmovl`, or
`cmova`). The destination is always a general register. If the condition is
false it is left unchanged; flags are read but not modified.""",
    "setcc": """Canonical form: `setcc destination`, replacing `cc` with a Jcc
condition (for example `sete %al`, `setne (%rdi)`, or `setl %cl`). SETcc writes
one byte containing 0 or 1. Use `movzbl %al, %eax` when a full-register Boolean
is required.""",
    "imul": """Useful forms:
  imul{w,l,q} source, destination                 # destination *= source
  imul{w,l,q} $imm, source, destination           # destination = source * imm
  imul{b,w,l,q} source                            # implicit accumulator product

Examples: `imulq %rsi, %rax`, `imulq $10, %rdi, %rax`. The one-operand form
writes the double-width product to AX, DX:AX, EDX:EAX, or RDX:RAX; the two- and
three-operand forms keep only the low half.""",
    "shl": """Forms:
  shl{b,w,l,q} $1, destination
  shl{b,w,l,q} $imm8, destination
  shl{b,w,l,q} %cl, destination

`sal` is an exact synonym. Bits shift toward the most-significant end; zeros
enter at the low end and the last bit shifted out enters CF.""",
    "shr": """Forms: `shr{b,w,l,q} $count, destination` or
`shr{b,w,l,q} %cl, destination`. SHR is a logical right shift: zeros enter at
the high end. Variable counts must use `%cl`, not an arbitrary register.""",
    "sar": """Forms: `sar{b,w,l,q} $count, destination` or
`sar{b,w,l,q} %cl, destination`. SAR is an arithmetic right shift: copies of
the sign bit enter at the high end. For negative signed integers this rounds
toward negative infinity, unlike signed division's rounding toward zero.""",
    "movzx": """GAS spells the source and destination widths in the mnemonic:
  movzbw / movzbl / movzbq        # zero-extend byte
  movzwl / movzwq                 # zero-extend word

Examples: `movzbl (%rdi), %eax`, `movzbq %al, %rax`, `movzwl %ax, %edx`.
There is no movzlq: writing a 32-bit register already clears its upper 32 bits.""",
    "movsx": """GAS spells the source and destination widths in the mnemonic:
  movsbw / movsbl / movsbq        # sign-extend byte
  movswl / movswq                 # sign-extend word
  movslq                          # sign-extend long to quad (also `movsxd`)

Examples: `movsbl (%rdi), %eax`, `movsbq %al, %rax`, `movslq %eax, %rdx`.""",
}


def load_data():
    with DATA.open(encoding="utf-8") as stream:
        data = json.load(stream)
    by_id = {item["id"].lower(): item for item in data["mnemonics"]}
    return data, by_id


def resolve(query, by_id):
    q = query.lower().strip()
    if q in by_id:
        return q, None
    for prefix, target in (("cmov", "cmovcc"), ("set", "setcc"), ("j", "jcc")):
        if q.startswith(prefix) and q[len(prefix):] in COND:
            return target, q
    if len(q) > 1 and q[-1] in SIZE_SUFFIX and q[:-1] in by_id:
        return q[:-1], q
    aliases = {"movsxd": "movsx", "sal": "shl", "retq": "ret", "leaveq": "leave"}
    if q in aliases and aliases[q] in by_id:
        return aliases[q], q
    return None, None


def att_operand(name):
    raw = name
    name = name.replace("GPR", "r").replace("AGEN", "m")
    if re.match(r"^(imm|uimm|simm)", name, re.I):
        return "$" + name.lower()
    if re.match(r"^(rel|ptr)", name, re.I):
        return name.lower()
    if name.upper() in {"AL", "AX", "EAX", "RAX", "CL", "DX", "XMM0"}:
        return "%" + name.lower()
    if re.match(r"^(r|xmm|ymm|zmm|mm|k|st|bnd|tmm|cr|dr)[0-9/{]", name, re.I):
        return "%" + name.lower()
    if raw == "m":
        return "m(address)"
    return name.lower()


def suffix_hint(form):
    syntax = form["syntax"]
    mnemonic = syntax.split(maxsplit=1)[0].lower()
    if mnemonic not in {"mov", "add", "adc", "sub", "sbb", "cmp", "and", "or", "xor", "test", "lea", "xchg", "inc", "dec", "neg", "not", "push", "pop", "imul", "mul", "idiv", "div", "shl", "shr", "sar", "rol", "ror", "rcl", "rcr", "bt", "btc", "btr", "bts"}:
        return mnemonic
    width_groups = re.findall(r"\b(?:m|r)((?:8|16|32|64)(?:/(?:8|16|32|64))*)", syntax, flags=re.I)
    widths = {width for group in width_groups for width in group.split("/")}
    if len(widths) == 1:
        return mnemonic + {"8": "b", "16": "w", "32": "l", "64": "q"}[widths.pop()]
    if widths:
        suffixes = "".join({"8": "b", "16": "w", "32": "l", "64": "q"}[width] for width in ("8", "16", "32", "64") if width in widths)
        return mnemonic + "{" + ",".join(suffixes) + "}"
    return mnemonic


def att_form(form):
    parts = form["syntax"].split(maxsplit=1)
    mnemonic = suffix_hint(form)
    if len(parts) == 1:
        return mnemonic
    operands = [att_operand(item[0]) for item in form.get("operands", [])]
    # XED writes destination first. GAS normally writes source(s) first. ENTER
    # is the documented multi-source exception; x87 has historical exceptions.
    if parts[0].upper() != "ENTER" and not parts[0].upper().startswith("F"):
        operands.reverse()
    return f"{mnemonic} " + ", ".join(operands)


def compact_forms(forms, requested=None):
    rows, seen = [], set()
    for form in forms:
        rendered = att_form(form)
        if requested:
            condition_family = re.match(r"^(cmov|set|j)[a-z]+$", requested.lower())
            if condition_family:
                rendered = re.sub(r"^(cmovcc|setcc|jcc)\b", requested.lower(), rendered)
        key = (rendered, tuple(form.get("tags", [])), form["isa_set"])
        if key not in seen:
            seen.add(key)
            rows.append((key[0], form))
    return rows


def section(title, body):
    return f"\n{title}\n{'-' * len(title)}\n{body.rstrip()}\n"


def render_page(item, data, requested=None, all_forms=False):
    title = item["name"]
    if requested and requested.lower() != item["id"]:
        title += f" (lookup: {requested})"
    out = [f"{title} — x86-64 AT&T instruction reference\n", item["summary"] + "\n"]
    if requested and requested[-1:] in SIZE_SUFFIX:
        out.append(f"Requested suffix: {requested[-1]} means {SIZE_SUFFIX[requested[-1]]}.\n")
    guide = GUIDES.get(item["id"])
    if guide:
        out.append(section("AT&T QUICK REFERENCE", guide))
    else:
        note = (
            "Generated from XED operand metadata. Operands are shown in GNU source-first order; "
            "register/immediate sigils and common scalar suffixes are added. For x87, ENTER, "
            "far-control-transfer, and newly introduced forms, verify the exact spelling with "
            "`asmhelp syntax` and your assembler."
        )
        out.append(section("AT&T SYNTAX", note))
    rows = compact_forms(item["forms"], requested)
    limit = len(rows) if all_forms else min(len(rows), 28)
    lines = []
    for att, form in rows[:limit]:
        suffix = []
        if form.get("tags"):
            suffix.extend(form["tags"])
        suffix.append(form["isa_set"])
        lines.append(f"  {att:<48} [{'; '.join(suffix)}]")
        lines.append(f"      XED/Intel: {form['syntax']}; encoding: {' | '.join(form['encodings'])}")
    if len(rows) > limit:
        lines.append(f"  … {len(rows) - limit} more distinct forms; use `asmhelp --all {item['id']}`.")
    out.append(section(f"FORMS ({len(rows)} distinct)", "\n".join(lines)))

    accesses = {}
    for form in item["forms"]:
        for name, action in form.get("implicit", []):
            accesses.setdefault(name, set()).add(action)
    if accesses:
        implicit = ", ".join(
            f"{name} ({'/'.join(ACTION.get(a, a) for a in sorted(actions))})"
            for name, actions in sorted(accesses.items())
        )
        out.append(section("IMPLICIT STATE", textwrap.fill(implicit, width=88)))

    flag_sets = {}
    for form in item["forms"]:
        for case in form.get("flags", []):
            for flag, action in case.get("flags", {}).items():
                flag_sets.setdefault(flag, set()).add(action)
    if flag_sets:
        flags = ", ".join(
            f"{flag} ({'/'.join(FLAG_ACTION.get(a, a) for a in sorted(actions))})"
            for flag, actions in sorted(flag_sets.items())
        )
        out.append(section("FLAGS", textwrap.fill(flags, width=88)))

    extensions = item.get("extensions") or []
    if extensions:
        names = {ext["id"]: ext["name"] for ext in data.get("extensions", [])}
        out.append(section("EXTENSIONS", ", ".join(names.get(ext, ext) for ext in extensions)))
    out.append(section("NOTATION", """rN is a general register; mN is an N-bit memory operand; immN is an immediate;
relN is a PC-relative target. AT&T concrete operands use `%reg`, `$immediate`, and
`disp(base,index,scale)`. Braces denote alternatives, not literal source text."""))
    out.append(section("SOURCE", f"""x86-64.net instruction dataset, updated {data['updated']}; forms derived from
Intel XED {data['sources']['xed']['version']}. Summaries are CC BY 4.0; XED-derived
tables are Apache-2.0. The packaged NOTICE contains full attribution. This AT&T
presentation is generated locally and is not an Intel or GNU publication."""))
    out.append("SEE ALSO\n--------\nasmhelp syntax; asmhelp search QUERY; man as\n")
    return "\n".join(out)


def syntax_page():
    return """AT&T / GNU AS x86-64 syntax
============================

OPERANDS
  Instructions normally read left to right: source(s), then destination.
  Registers use `%` and immediates use `$`:  addq $4, %rax
  Indirect CALL/JMP operands use `*`:         call *%rax

SIZES
  b = byte (8), w = word (16), l = long (32), q = quad (64 bits).
  The suffix belongs to the mnemonic: movq, addl, cmpb. GAS can infer it when a
  register fixes the width; use an explicit suffix for readable, unambiguous code.

MEMORY
  displacement(base,index,scale)
  Address = displacement + base + index*scale; scale is 1, 2, 4, or 8.
  Examples: (%rax), 8(%rbp), array(,%rcx,4), symbol(%rip)

COMMON TRANSLATIONS
  Intel                         AT&T
  mov rax, rbx                  movq %rbx, %rax
  add eax, 4                    addl $4, %eax
  cmp rdi, rsi                  cmpq %rsi, %rdi
  mov eax, [rbx+rcx*4+8]        movl 8(%rbx,%rcx,4), %eax
  lea rax, [rip+symbol]         leaq symbol(%rip), %rax
  call rax                      call *%rax

GOTCHAS
  • CMP/SUB flags describe destination - source.
  • A bare symbol is a memory operand; `$symbol` is its address as an immediate.
  • `symbol(%rip)` is the usual position-independent data reference.
  • String, x87, ENTER, far transfers, and some multi-operand instructions have
    historical exceptions. Consult the instruction page and GNU `as` manual.
"""


def regs_page():
    rows = [
        ("%rax", "%eax", "%ax", "%al", "return value", "caller"),
        ("%rbx", "%ebx", "%bx", "%bl", "general purpose", "callee"),
        ("%rcx", "%ecx", "%cx", "%cl", "argument 4", "caller"),
        ("%rdx", "%edx", "%dx", "%dl", "argument 3", "caller"),
        ("%rsi", "%esi", "%si", "%sil", "argument 2", "caller"),
        ("%rdi", "%edi", "%di", "%dil", "argument 1", "caller"),
        ("%rsp", "%esp", "%sp", "%spl", "stack pointer", "special"),
        ("%rbp", "%ebp", "%bp", "%bpl", "frame/base pointer", "callee"),
        ("%r8", "%r8d", "%r8w", "%r8b", "argument 5", "caller"),
        ("%r9", "%r9d", "%r9w", "%r9b", "argument 6", "caller"),
        ("%r10", "%r10d", "%r10w", "%r10b", "general purpose", "caller"),
        ("%r11", "%r11d", "%r11w", "%r11b", "general purpose", "caller"),
        ("%r12", "%r12d", "%r12w", "%r12b", "general purpose", "callee"),
        ("%r13", "%r13d", "%r13w", "%r13b", "general purpose", "callee"),
        ("%r14", "%r14d", "%r14w", "%r14b", "general purpose", "callee"),
        ("%r15", "%r15d", "%r15w", "%r15b", "general purpose", "callee"),
    ]
    widths = (7, 7, 7, 7, 20, 8)
    headers = ("64-bit", "32-bit", "16-bit", "8-bit", "System V AMD64 role", "saved by")

    def rule(char="-"):
        return "+" + "+".join(char * (width + 2) for width in widths) + "+"

    def row(values):
        return "| " + " | ".join(f"{value:<{width}}" for value, width in zip(values, widths)) + " |"

    table = [rule(), row(headers), rule("="), *(row(values) for values in rows), rule()]
    return """x86-64 general-purpose registers (AT&T / System V AMD64)
================================================================

""" + "\n".join(table) + """

CALLING-CONVENTION KEY
  caller   The called function may overwrite this register. If the calling
           function needs its value after `call`, the caller must save it.
  callee   A function that changes this register must restore the incoming
           value before it returns.
  special  `%rsp` tracks the stack. Restore it to its entry value before `ret`;
           do not treat it as a general-purpose saved register.

WIDTH RULES
  The names in each row overlap the same physical register. Writing a 32-bit
  name (for example `%eax`) clears the upper 32 bits of the 64-bit register.
  Writing a 16- or 8-bit name leaves the other bits unchanged.

  `%ah`, `%bh`, `%ch`, and `%dh` name bits 8–15 of the first four legacy
  registers. They cannot be encoded in an instruction that uses a REX prefix;
  prefer the low-byte names shown above in 64-bit code.

ARGUMENTS AND RETURN VALUES
  Integer/pointer arguments 1–6: `%rdi`, `%rsi`, `%rdx`, `%rcx`, `%r8`, `%r9`
  Integer/pointer return value: `%rax`
  Narrow integer arguments use the corresponding 32/16/8-bit names. Floating-
  point/vector arguments and returns use XMM registers and follow separate ABI
  rules. Structs and large values can also use different passing rules.

OTHER SPECIAL REGISTERS
  `%rip` is the instruction pointer. It is not a general-purpose register and
  has no directly addressable 32/16/8-bit subregisters. RIP-relative memory,
  such as `symbol(%rip)`, is the normal position-independent form.

This is the terminal equivalent of the CMSC216 `regs.png` table, with ABI
wording clarified. The roles shown are for the 64-bit System V ABI used by the
course and by ordinary Linux/macOS C code, not the Windows x64 convention.
"""


def search(query, data):
    terms = query.lower().split()

    def variants(term):
        words = {term}
        for suffix, keep in (("al", 2), ("ing", 3), ("ed", 2), ("s", 1)):
            if term.endswith(suffix) and len(term) > keep + 3:
                words.add(term[:-keep])
        return words

    scored = []
    for item in data["mnemonics"]:
        haystack = " ".join((item["id"], item["name"], item["summary"])).lower()
        if all(any(word in haystack for word in variants(term)) for term in terms):
            score = 0 if item["id"] == query.lower() else (1 if item["id"].startswith(query.lower()) else 2)
            scored.append((score, item["id"], item))
    lines = [f"Search results for: {query}\n"]
    for _, _, item in sorted(scored)[:80]:
        lines.append(f"  {item['id']:<18} {item['summary']}")
    if len(scored) > 80:
        lines.append(f"  … {len(scored) - 80} more results")
    if not scored:
        lines.append("  No matching instructions.")
    return "\n".join(lines) + "\n"


def emit(text):
    if not sys.stdout.isatty() or os.environ.get("ASMHELP_PAGER") == "cat":
        sys.stdout.write(text)
        return
    pager = os.environ.get("ASMHELP_PAGER") or os.environ.get("MANPAGER") or os.environ.get("PAGER")
    command = pager.split() if pager else ([shutil.which("less"), "-R", "-F", "-X"] if shutil.which("less") else [])
    if not command or not command[0]:
        sys.stdout.write(text)
        return
    try:
        subprocess.run(command, input=text, text=True, check=False)
    except (BrokenPipeError, OSError):
        sys.stdout.write(text)


def main():
    parser = argparse.ArgumentParser(prog="asmhelp", description="offline x86-64 AT&T instruction manual")
    parser.add_argument("--all", action="store_true", help="show every distinct instruction form")
    parser.add_argument("command", nargs="?", help="instruction mnemonic, or search/list/syntax")
    parser.add_argument("terms", nargs="*", help="search terms")
    args = parser.parse_args()
    if args.command == "syntax":
        emit(syntax_page())
        return 0
    if args.command in {"regs", "registers"}:
        emit(regs_page())
        return 0
    data, by_id = load_data()
    if args.command == "search":
        if not args.terms:
            parser.error("search requires one or more terms")
        emit(search(" ".join(args.terms), data))
        return 0
    if args.command == "list":
        emit("\n".join(item["id"] for item in data["mnemonics"]) + "\n")
        return 0
    if not args.command:
        parser.print_help()
        return 0
    if args.terms:
        parser.error("an instruction lookup accepts one mnemonic")
    item_id, requested = resolve(args.command, by_id)
    if item_id is None:
        suggestions = search(args.command, data)
        sys.stderr.write(f"asmhelp: unknown instruction: {args.command}\n\n{suggestions}")
        return 1
    emit(render_page(by_id[item_id], data, requested or args.command, args.all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
