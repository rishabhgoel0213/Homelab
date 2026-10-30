{
  lib,
  python3,
  fetchurl,
  binutils,
  stdenv,
  makeWrapper,
  less,
}:

let
  insnData = fetchurl {
    url = "https://x86-64.net/data/insn.json";
    hash = "sha256-+HsyBkJJOkSea7iH2u80wJz2gaU5ajqxYT/xY4QYwkE=";
  };
  notice = fetchurl {
    url = "https://x86-64.net/data/insn-NOTICE.txt";
    hash = "sha256-duXwNIHKws+WXkiG6XPtuDQzgz7uu51mVU9kR5D31e0=";
  };
in
python3.pkgs.buildPythonApplication rec {
  pname = "asmhelp";
  version = "2026.10.27";
  format = "other";

  src = ./.;
  nativeBuildInputs = [ makeWrapper ];
  nativeCheckInputs = lib.optionals (stdenv.hostPlatform.isLinux && stdenv.hostPlatform.isx86_64) [ binutils ];

  installPhase = ''
    runHook preInstall
    install -Dm755 asmhelp.py "$out/libexec/asmhelp/asmhelp.py"
    install -Dm644 ${insnData} "$out/share/asmhelp/insn.json"
    install -Dm644 ${notice} "$out/share/doc/asmhelp/NOTICE"
    makeWrapper ${python3}/bin/python3 "$out/bin/asmhelp" \
      --add-flags "$out/libexec/asmhelp/asmhelp.py" \
      --set ASMHELP_DATA "$out/share/asmhelp/insn.json" \
      --prefix PATH : ${lib.makeBinPath [ less ]}
    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    export ASMHELP_PAGER=cat
    "$out/bin/asmhelp" mov > mov.txt
    grep -Fq 'movq  %rax, -8(%rbp)' mov.txt
    grep -Fq 'AT&T QUICK REFERENCE' mov.txt
    "$out/bin/asmhelp" cmpq > cmp.txt
    grep -Fq 'flags from rdi - rsi' cmp.txt
    "$out/bin/asmhelp" lea > lea.txt
    grep -Fq 'symbol(%rip)' lea.txt
    "$out/bin/asmhelp" jnz > jnz.txt
    grep -Fq 'Jcc' jnz.txt
    "$out/bin/asmhelp" search 'address memory' > search.txt
    grep -Fq 'lea' search.txt
    "$out/bin/asmhelp" search 'conditional jump' > search-condition.txt
    grep -Fq 'jcc' search-condition.txt
    "$out/bin/asmhelp" syntax > syntax.txt
    grep -Fq 'displacement(base,index,scale)' syntax.txt
    "$out/bin/asmhelp" regs > regs.txt
    grep -Fq '%rax    | %eax' regs.txt
    grep -Fq '%rdi    | %edi' regs.txt
    grep -Fq 'argument 6' regs.txt
    grep -Fq 'caller must save it' regs.txt
    grep -Fq 'Writing a 32-bit' regs.txt
    ${lib.optionalString (stdenv.hostPlatform.isLinux && stdenv.hostPlatform.isx86_64) ''
      as --64 -o examples.o ${./tests/examples.s}
      objdump -dr -M att examples.o > examples.dump
      grep -Fq 'movabs' examples.dump
      grep -Fq 'lea' examples.dump
      grep -Fq 'cmp' examples.dump
    ''}
  '';

  meta = {
    description = "Offline terminal reference for x86-64 instructions in AT&T syntax";
    homepage = "https://x86-64.net/";
    license = with lib.licenses; [ cc-by-40 asl20 ];
    platforms = lib.platforms.unix;
    mainProgram = "asmhelp";
  };
}
