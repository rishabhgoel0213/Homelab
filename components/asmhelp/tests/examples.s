    .text
    .globl asmhelp_examples
asmhelp_examples:
    movl %edi, %eax
    movl (%rdi), %eax
    movl %eax, 4(%rdi)
    leaq 4(%rdi), %rax
    leaq (%rdi,%rdi,4), %rax
    movsbl %al, %eax
    movzbl %al, %eax
    movswl %ax, %eax
    movzwl %ax, %eax
    movslq %eax, %rax
    addl %esi, %eax
    subl %esi, %eax
    incl %eax
    decl %eax
    negl %eax
    notl %eax
    imull %esi, %eax
    imull $5, %edi, %eax
    andl %esi, %eax
    orl %esi, %eax
    xorl %eax, %eax
    sall $3, %eax
    shrl $3, %eax
    sarl %cl, %eax
    cltd
    idivl %esi
    cmpl %esi, %edi
    testl %eax, %eax
    sete %al
    setl %al
    cmovl %esi, %eax
    pushq %rbx
    popq %rbx
    ret
