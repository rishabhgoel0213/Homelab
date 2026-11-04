{ runCommand }:
# Built by build-abstand-mac from v0.1.35 plus patches/brick-release.patch.
# Imported with nix-store --add-fixed sha256 and retained by the artifact runbook.
let
  archive = builtins.storePath "/nix/store/1l0zhggkpcafrkchwq5dpkavgwl42y8s-Abstand-brick-0.1.35-1.tar.gz";
in
runCommand "abstand-brick-archive-0.1.35-1" { } ''
  echo 'cc9cd848ba04721a5e3943a2f560345e2d46569ec2fa6fb92c2337e4bd55ed92  ${archive}' | sha256sum -c -
  cp ${archive} "$out"
''
