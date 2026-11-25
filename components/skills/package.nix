{
  git,
  lib,
  python3,
  runCommand,
  writeShellApplication,
  writeText,
  stateDirectory ? "/srv/state/skills",
  targets ? "codex=/srv/state/codex/skills:claude=/srv/state/claude/skills:antigravity=/srv/state/antigravity/config/skills",
  extraScanDirs ? "/home/rishabh/.agents/skills",
  t3AntigravityRoot ? "/srv/state/t3code/userdata/providers/antigravity",
  declarativeSkills ? { },
}:

let
  declarativeMeta = writeText "homelab-declarative-skills-meta.json" (
    builtins.toJSON (
      lib.mapAttrs (
        _: spec:
        lib.filterAttrs (k: v: k != "path" && v != null) spec
      ) declarativeSkills
    )
  );

  linkCommands = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (
      name: spec:
      ''
        ln -s ${lib.escapeShellArg (toString spec.path)} "$out/${lib.escapeShellArg name}"
        ${python3}/bin/python3 ${./bin/skills.py} validate "$out/${lib.escapeShellArg name}" --expected-name ${lib.escapeShellArg name}
      ''
    ) declarativeSkills
  );

  declarativeDir =
    runCommand "homelab-declarative-skills"
      {
        nativeBuildInputs = [ python3 ];
      }
      ''
        mkdir -p "$out"
        ${linkCommands}
      '';

  skillsBin = writeShellApplication {
    name = "skills";
    runtimeInputs = [
      git
      python3
    ];
    text = ''
      export PYTHONDONTWRITEBYTECODE=1
      export SKILLS_STATE=''${SKILLS_STATE:-${lib.escapeShellArg stateDirectory}}
      export SKILLS_DECLARATIVE_DIR=''${SKILLS_DECLARATIVE_DIR:-${declarativeDir}}
      export SKILLS_DECLARATIVE_META=''${SKILLS_DECLARATIVE_META:-${declarativeMeta}}
      export SKILLS_TARGETS=''${SKILLS_TARGETS:-${lib.escapeShellArg targets}}
      export SKILLS_EXTRA_SCAN_DIRS=''${SKILLS_EXTRA_SCAN_DIRS:-${lib.escapeShellArg extraScanDirs}}
      export SKILLS_T3_ANTIGRAVITY_ROOT=''${SKILLS_T3_ANTIGRAVITY_ROOT:-${lib.escapeShellArg t3AntigravityRoot}}
      exec python3 ${./bin/skills.py} "$@"
    '';
  };
in
runCommand "homelab-skills"
  {
    passthru = {
      inherit declarativeDir declarativeMeta;
    };
    meta = {
      description = "Hybrid declarative and mutable cross-harness global agent skill manager";
      license = lib.licenses.mit;
      platforms = lib.platforms.linux;
      mainProgram = "skills";
    };
  }
  ''
    mkdir -p "$out/bin"
    ln -s ${skillsBin}/bin/skills "$out/bin/skills"
  ''
