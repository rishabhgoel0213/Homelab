{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.coursework.cmsc216;
  user = "rishabhgoel";
  userHome = "/Users/${user}";
  remoteRoot = if cfg.remoteRoot == null then "/home/${cfg.directoryId}/216-sync" else cfg.remoteRoot;
  coursePackage = pkgs.callPackage ./package.nix {
    inherit pkgs remoteRoot;
    codiumBin = "${config.homelab.apps.vscodium.generated.cmsc216.codiumPackage}/bin/codium-cmsc216";
    inherit (cfg)
      authPersist
      dataRoot
      directoryId
      localRoot
      ;
  };
  sshConfig = ''
    Host zaratan cmsc216-zaratan
      HostName login.zaratan.umd.edu
      HostKeyAlias login.zaratan.umd.edu
      User ${cfg.directoryId}
      Port 22
      PubkeyAuthentication no
      PreferredAuthentications keyboard-interactive,password
      KbdInteractiveAuthentication yes
      PasswordAuthentication yes
      StrictHostKeyChecking yes
      UserKnownHostsFile /etc/ssh/cmsc216_known_hosts
      HostKeyAlgorithms ssh-ed25519
      ForwardAgent no
      ClearAllForwardings yes
      ServerAliveInterval 30
      ServerAliveCountMax 3
      ControlMaster auto
      ControlPath ${userHome}/.ssh/control/cmsc216-%C
      ControlPersist ${cfg.authPersist}
  '';
in
{
  options.homelab.coursework.cmsc216 = {
    enable = lib.mkEnableOption "the isolated CMSC 216 macOS development environment";

    directoryId = lib.mkOption {
      type = lib.types.str;
      default = "r1shabhg";
      description = "UMD Directory ID used for Zaratan authentication.";
    };

    localRoot = lib.mkOption {
      type = lib.types.str;
      default = "${userHome}/Projects/fall-2026/cmsc216";
      description = "Mutable CMSC 216 folder inside the Syncthing-managed Fall 2026 project.";
    };

    remoteRoot = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Zaratan synchronization root; defaults to /home/<directoryId>/216-sync.";
    };

    authPersist = lib.mkOption {
      type = lib.types.str;
      default = "8h";
      description = "Idle lifetime of the reusable Zaratan SSH connection after Duo authentication.";
    };

    dataRoot = lib.mkOption {
      type = lib.types.str;
      default = "${userHome}/Library/Application Support/CMSC216/VSCodium";
      description = "Mutable isolated VSCodium user-data directory.";
    };

    package = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      internal = true;
      description = "Generated CMSC 216 application bundle.";
    };

    cliPackage = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      internal = true;
      description = "Generated CMSC 216 command-line package.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = builtins.match "[A-Za-z0-9._-]+" cfg.directoryId != null;
        message = "homelab.coursework.cmsc216.directoryId must be a plain UMD Directory ID";
      }
      {
        assertion = lib.hasPrefix "${userHome}/" cfg.localRoot;
        message = "homelab.coursework.cmsc216.localRoot must be inside ${userHome}";
      }
    ];

    homelab.coursework.cmsc216 = {
      package = config.homelab.apps.vscodium.generated.cmsc216.package;
      cliPackage = coursePackage.cli;
    };

    homelab.apps.vscodium.presets.cmsc216 = {
      displayName = "VSCodium 216";
      bundleIdentifier = "com.therealrishabh.cmsc216";
      icon = ../vscodium/icons/VSCodium-CMSC216.icns;
      inherit (cfg) dataRoot;
      extensions = [ pkgs.vscode-extensions.llvm-vs-code-extensions.vscode-clangd ];
      settings = coursePackage.settings;
      workspace = coursePackage.workspace;
      workspaceLinkName = "CMSC 216.code-workspace";
      appVersion = "2026.3";
    };

    environment.systemPackages = [
      coursePackage.cli
    ];

    environment.etc = {
      "ssh/cmsc216_known_hosts" = {
        text = builtins.readFile ./config/zaratan-known-hosts;
      };
      "ssh/ssh_config.d/90-cmsc216.conf" = {
        text = sshConfig;
      };
    };

    system.activationScripts.postActivation.text = lib.mkAfter ''
      course_root=${lib.escapeShellArg cfg.localRoot}
      ssh_root=${lib.escapeShellArg "${userHome}/.ssh"}
      legacy_course_root=${lib.escapeShellArg "${userHome}/Coursework/CMSC216"}

      install -d -m 0755 -o ${user} -g staff "$course_root"
      install -d -m 0700 -o ${user} -g staff "$ssh_root" "$ssh_root/control"

      for legacy_link in \
        "$legacy_course_root/CMSC 216.code-workspace" \
        "$legacy_course_root/.vscode/sftp.json"
      do
        if [[ -L "$legacy_link" ]]; then
          rm "$legacy_link"
        fi
      done
    '';
  };
}
