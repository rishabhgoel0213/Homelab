{ lib, stdenvNoCC, python3, sudo, writeShellScriptBin }:
let
  darwin = stdenvNoCC.hostPlatform.isDarwin;
  state = if darwin then "/var/db/brick-admin" else "/var/lib/brick-admin";
  user = if darwin then "rishabhgoel" else "rishabh";
  nativeSudo = if darwin then "/usr/bin/sudo" else "/run/wrappers/bin/sudo";
  gate = stdenvNoCC.mkDerivation {
    pname = "brick-admin-gate";
    version = "1";
    dontUnpack = true;
    installPhase = ''
      mkdir -p "$out/libexec"
      substitute ${./gate.py} "$out/libexec/gate.py" \
        --replace-fail '@source@' '${./.}' \
        --replace-fail '@state@' '${state}' \
        --replace-fail '@user@' '${user}' \
        --replace-fail '@helper@' '/etc/brick-admin-root' \
        --replace-fail '@visudo@' '${if darwin then "/usr/sbin/visudo" else "${sudo}/sbin/visudo"}' \
        --replace-fail '@path@' '/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:/usr/bin:/bin:/usr/sbin:/sbin'
      printf '#!${stdenvNoCC.shell}\nexec ${python3}/bin/python3 -I "%s/libexec/gate.py" "$@"\n' "$out" > "$out/libexec/brick-admin-root"
      chmod 0555 "$out/libexec/brick-admin-root"
    '';
  };
in
(writeShellScriptBin "brick-admin" ''
  exec ${nativeSudo} -H /etc/brick-admin-root "$@"
'').overrideAttrs (_: { passthru = { inherit gate state; }; })
