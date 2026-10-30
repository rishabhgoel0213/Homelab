{
  lib,
  python3,
  binutils,
  stdenv,
  makeWrapper,
  less,
}:

python3.pkgs.buildPythonApplication rec {
  pname = "asmhelp";
  version = "2026.10.30";
  format = "other";

  src = ./.;
  nativeBuildInputs = [ makeWrapper ];
  nativeCheckInputs = lib.optionals (stdenv.hostPlatform.isLinux && stdenv.hostPlatform.isx86_64) [ binutils ];

  installPhase = ''
    runHook preInstall
    install -Dm755 asmhelp.py "$out/libexec/asmhelp/asmhelp.py"
    install -Dm644 topics.toml "$out/share/asmhelp/topics.toml"
    makeWrapper ${python3}/bin/python3 "$out/bin/asmhelp" \
      --add-flags "$out/libexec/asmhelp/asmhelp.py" \
      --set ASMHELP_DATA "$out/share/asmhelp/topics.toml" \
      --prefix PATH : ${lib.makeBinPath [ less ]}
    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    export ASMHELP_PAGER=cat
    "$out/bin/asmhelp" > topics.txt
    grep -Fq 'There is no network access' topics.txt
    "$out/bin/asmhelp" mov > mov.txt
    grep -Fq 'movl (%rdi), %eax' mov.txt
    "$out/bin/asmhelp" cmpq > cmp.txt
    grep -Fq 'destination - source' cmp.txt
    "$out/bin/asmhelp" lea > lea.txt
    grep -Fq 'symbol(%rip)' lea.txt
    "$out/bin/asmhelp" division > division.txt
    "$out/bin/asmhelp" idivl > idivl.txt
    "$out/bin/asmhelp" remainder > remainder.txt
    grep -Fq 'cltd' division.txt
    grep -Fq 'Quotient' idivl.txt
    grep -Fq 'Remainder' remainder.txt
    "$out/bin/asmhelp" 'how do I divide' > natural.txt
    grep -Fq 'SIGNED 32-BIT DIVISION' natural.txt
    "$out/bin/asmhelp" regs > regs.txt
    grep -Fq '%rax    | %eax' regs.txt
    grep -Fq '%rdi    | %edi' regs.txt
    grep -Fq 'argument 6' regs.txt
    grep -Fq 'caller must save it' regs.txt
    grep -Fq 'clears the upper 32 bits' regs.txt
    "$out/bin/asmhelp" struct > structs.txt
    grep -Fq 'Field offsets are' structs.txt
    if "$out/bin/asmhelp" vaddps > out-of-scope.txt 2>&1; then
      echo 'out-of-scope lookup unexpectedly succeeded' >&2
      exit 1
    fi
    grep -Fq 'no CMSC216 topic matches' out-of-scope.txt
    ${lib.optionalString (stdenv.hostPlatform.isLinux && stdenv.hostPlatform.isx86_64) ''
      as --64 -o examples.o ${./tests/examples.s}
      objdump -dr -M att examples.o > examples.dump
      grep -Fq 'idiv' examples.dump
      grep -Fq 'lea' examples.dump
      grep -Fq 'cmp' examples.dump
    ''}
  '';

  meta = {
    description = "Offline CMSC216 x86-64 AT&T assembly reference";
    platforms = lib.platforms.unix;
    mainProgram = "asmhelp";
  };
}
