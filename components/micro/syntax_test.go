package buffer

import (
	"strings"
	"testing"

	"github.com/zyedidia/micro/v2/internal/config"
	"github.com/zyedidia/micro/v2/pkg/highlight"
)

func TestHomelabAssemblyDetection(t *testing.T) {
	// Disable asynchronous rendering while retaining buffer filetype detection.
	previous := config.GlobalSettings["syntax"]
	config.GlobalSettings["syntax"] = false
	defer func() { config.GlobalSettings["syntax"] = previous }()
	for _, tc := range []struct{ name, filetype string }{
		{"example.s", "x86-att"}, {"example.S", "x86-att"},
		{"example.asm", "asm"}, {"example.c", "c"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			b := NewBufferFromString("", tc.name, BTDefault)
			defer b.Close()
			if got := b.Settings["filetype"]; got != tc.filetype {
				t.Fatalf("filetype = %v, want %s", got, tc.filetype)
			}
		})
	}
}

func TestHomelabAssemblyHighlighting(t *testing.T) {
	previous := config.GlobalSettings["syntax"]
	config.GlobalSettings["syntax"] = false
	defer func() { config.GlobalSettings["syntax"] = previous }()
	b := NewBufferFromString("", "example.s", BTDefault)
	defer b.Close()
	for _, tc := range []struct{ line, token, group string }{
		{"    movq $42, %rax # comment", "movq", "statement"},
		{"    leaq -8(%rbp,%rcx,8), %r15", "leaq", "statement"},
		{"    nop; retq", "retq", "statement"},
		{"    rep movsb", "movsb", "statement"},
		{".Lloop: addq $1, %rax", "addq", "statement"},
		{"    movq $42, %rax", "$42", "constant"},
		{"    movq $0x2a, %rax", "$0x2a", "constant"},
		{"    movq $symbol, %rax", "$symbol", "constant"},
		{"    movq %r15, %rax", "%r15", "identifier"},
		{"    movb %r15b, %al", "%r15b", "identifier"},
		{"    movq message(%rip), %rax", "%rip", "identifier"},
		{"    fadd %st(0), %st(1)", "%st(0)", "identifier"},
		{"    .globl main", ".globl", "preproc"},
		{".Lloop: addq $1, %rax", ".Lloop:", "identifier"},
		{"1: jmp 1b", "1b", "identifier"},
		{"    movq %rax, %rbx # movq $42", "movq $42", "comment"},
		{"    nop /* movq $42 */", "movq $42", "comment"},
		{"    .asciz \"# hello\"", "# hello", "constant.string"},
		{"    movb $'A, %al", "'A", "constant"},
	} {
		t.Run(tc.line+"/"+tc.token, func(t *testing.T) {
			matches := highlight.NewHighlighter(b.SyntaxDef).HighlightString(tc.line)[0]
			start := strings.Index(tc.line, tc.token)
			for pos := start; pos < start+len(tc.token); pos++ {
				var got highlight.Group
				for i := 0; i <= pos; i++ {
					if group, ok := matches[i]; ok {
						got = group
					}
				}
				if got.String() != tc.group {
					t.Fatalf("%q at column %d: group = %q, want %q", tc.token, pos, got.String(), tc.group)
				}
			}
		})
	}
}
