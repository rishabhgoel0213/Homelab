{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  cfg = homelab.skills;
  stateDirectory = "${homelab.paths.stateRoot}/skills";
  defaultDeclarative = import ./declarative.nix { inherit pkgs; };
  declarativeSkills = defaultDeclarative // cfg.declarative;
  targets = lib.concatStringsSep ":" [
    "codex=${homelab.paths.codexHome}/skills"
    "claude=${homelab.paths.stateRoot}/claude/skills"
    "antigravity=${homelab.paths.stateRoot}/antigravity/config/skills"
  ];
  skills = pkgs.callPackage ./package.nix {
    inherit stateDirectory targets declarativeSkills;
    extraScanDirs = "${homelab.paths.userHome}/.agents/skills";
    t3AntigravityRoot = "${homelab.paths.t3codeState}/userdata/providers/antigravity";
  };
  runuser = "${pkgs.util-linux}/bin/runuser -u rishabh --";
in
{
  options.homelab.skills = {
    enable = lib.mkEnableOption "global cross-harness agent skills manager";

    declarative = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            path = lib.mkOption {
              type = lib.types.either lib.types.path lib.types.str;
              description = "Path to the skill directory containing SKILL.md.";
            };
            source = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Human-readable upstream source string.";
            };
            rev = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Pinned revision SHA for upstream skills.";
            };
          };
        }
      );
      default = { };
      description = "Additional declarative skills merged on top of components/skills/declarative.nix.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ skills ];

    systemd.tmpfiles.rules = [
      "d ${stateDirectory} 0700 rishabh users -"
      "d ${stateDirectory}/installed 0700 rishabh users -"
    ];

    # Reconcile declarative + mutable installed skills into Codex, Claude Code,
    # and Antigravity immediately after their config directories are prepared.
    system.activationScripts.skillsSync = {
      deps = [
        "users"
        "codexConfig"
        "claudeConfig"
        "antigravityConfig"
      ];
      text = ''
        install -d -m 0700 -o rishabh -g users ${lib.escapeShellArg stateDirectory} ${lib.escapeShellArg "${stateDirectory}/installed"}
        install -d -m 0700 -o rishabh -g users \
          ${lib.escapeShellArg "${homelab.paths.codexHome}/skills"} \
          ${lib.escapeShellArg "${homelab.paths.stateRoot}/claude/skills"} \
          ${lib.escapeShellArg "${homelab.paths.stateRoot}/antigravity/config/skills"}
        ${runuser} ${skills}/bin/skills sync >/dev/null
      '';
    };

    assertions = [
      {
        assertion = lib.hasPrefix "/srv/state/" stateDirectory;
        message = "Skills runtime state must live under /srv/state.";
      }
    ];
  };
}
