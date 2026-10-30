    .text
    .globl asmhelp_examples
asmhelp_examples:
    movb %al, (%rdi)
    movw %ax, 2(%rdi)
    movl $42, %eax
    movq %rax, -8(%rbp)
    movabsq $0x1122334455667788, %rax
    movq 8(%rdi,%rcx,4), %rax
    leaq 8(%rdi,%rsi,4), %rax
    leaq asmhelp_examples(%rip), %rdi
    leal 3(%edi,%edi,4), %eax
    cmpq %rsi, %rdi
    cmpl $10, %eax
    cmpb $0, (%rdi)
    testq %rax, %rax
    addq %rsi, %rax
    subl $4, %eax
    andl $0xff, %eax
    orq %rsi, %rax
    xorl %eax, %eax
    shlq $1, %rax
    shrq %cl, %rax
    sarq $2, %rax
    imulq %rsi, %rax
    imulq $10, %rdi, %rax
    movzbl (%rdi), %eax
    movzbq %al, %rax
    movzwl %ax, %edx
    movsbl (%rdi), %eax
    movsbq %al, %rax
    movslq %eax, %rdx
    call *%rax
    jmp *%rax
