{ micro }:

# Embed the shared syntax for every user without changing writable settings.
micro.overrideAttrs (old: {
  postPatch = (old.postPatch or "") + ''
    substituteInPlace runtime/syntax/asm.yaml \
      --replace-fail '(S|s|asm)' '(asm)'
    cp ${./x86-att.yaml} runtime/syntax/x86-att.yaml
    cp ${./syntax_test.go} internal/buffer/homelab_syntax_test.go
  '';
  postBuild = (old.postBuild or "") + ''
    go test ./internal/buffer -run '^TestHomelabAssembly' -count=1 -v
  '';
})
