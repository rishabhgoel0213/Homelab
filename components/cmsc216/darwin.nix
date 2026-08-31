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
  packageSet = pkgs.callPackage ./package.nix {
    inherit pkgs remoteRoot;
    inherit (cfg)
      autoOpenGlobalProtect
      dataRoot
      directoryId
      globalProtectApp
      identityFile
      localRoot
      ;
  };
  sshConfig = ''
    Host zaratan cmsc216-zaratan
      HostName login.zaratan.umd.edu
      HostKeyAlias login.zaratan.umd.edu
      User ${cfg.directoryId}
      Port 22
      IdentityFile ${cfg.identityFile}
      IdentitiesOnly yes
      AddKeysToAgent yes
      UseKeychain yes
      PreferredAuthentications publickey,keyboard-interactive,password
      StrictHostKeyChecking yes
      UserKnownHostsFile /etc/ssh/cmsc216_known_hosts
      HostKeyAlgorithms ssh-ed25519
      ForwardAgent no
      ClearAllForwardings yes
      ServerAliveInterval 30
      ServerAliveCountMax 3
      ControlMaster auto
      ControlPath ${userHome}/.ssh/control/cmsc216-%C
      ControlPersist 10m
  '';
  sftpHostKey = "3ade1b4e3766bf7b7c2f09f6b844d594014fce116841a7d0eedb7ea0700debdc";
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
      default = "${userHome}/Coursework/CMSC216";
      description = "Mutable local course root; 216-sync is created below it.";
    };

    remoteRoot = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Zaratan synchronization root; defaults to /home/<directoryId>/216-sync.";
    };

    identityFile = lib.mkOption {
      type = lib.types.str;
      default = "${userHome}/.ssh/cmsc216-zaratan-ed25519";
      description = "Runtime private key path. Key material is never placed in Nix or Git.";
    };

    dataRoot = lib.mkOption {
      type = lib.types.str;
      default = "${userHome}/Library/Application Support/CMSC216/VSCodium";
      description = "Mutable isolated VSCodium user-data directory.";
    };

    autoOpenGlobalProtect = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Open GlobalProtect after a passwordless Zaratan probe fails.";
    };

    globalProtectApp = lib.mkOption {
      type = lib.types.str;
      default = "/Applications/GlobalProtect.app";
      description = "Expected path of the separately installed GlobalProtect application.";
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
      {
        assertion = lib.hasPrefix "${userHome}/.ssh/" cfg.identityFile;
        message = "homelab.coursework.cmsc216.identityFile must stay under ${userHome}/.ssh";
      }
    ];

    homelab.coursework.cmsc216 = {
      package = packageSet.app;
      cliPackage = packageSet.cli;
    };

    environment.systemPackages = [
      packageSet.app
      packageSet.cli
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
      sync_root="$course_root/216-sync"
      editor_config="$course_root/.vscode"
      data_root=${lib.escapeShellArg cfg.dataRoot}
      ssh_root=${lib.escapeShellArg "${userHome}/.ssh"}
      extension_state=${lib.escapeShellArg "${userHome}/.vscode-sftp"}

      install -d -m 0755 -o ${user} -g staff "$course_root" "$sync_root" "$editor_config"
      install -d -m 0700 -o ${user} -g staff "$data_root" "$data_root/User"
      install -d -m 0700 -o ${user} -g staff "$ssh_root" "$ssh_root/control" "$extension_state"

      manage_link() {
        target="$1"
        source="$2"
        if [[ -e "$target" && ! -L "$target" ]]; then
          echo "Refusing to replace unmanaged CMSC 216 file at $target" >&2
          exit 1
        fi
        ln -sfn "$source" "$target"
        chown -h ${user}:staff "$target"
      }

      manage_link "$editor_config/sftp.json" ${packageSet.sftpConfig}
      manage_link "$data_root/User/settings.json" ${packageSet.settings}
      manage_link "$course_root/CMSC 216.code-workspace" ${packageSet.workspace}

      sftp_known_hosts="$extension_state/known_hosts.json"
      sftp_key="login.zaratan.umd.edu:22"
      sftp_fingerprint=${lib.escapeShellArg sftpHostKey}
      if [[ -e "$sftp_known_hosts" ]]; then
        current="$(${pkgs.jq}/bin/jq -r --arg key "$sftp_key" '.[$key] // empty' "$sftp_known_hosts")"
        if [[ -n "$current" && "$current" != "$sftp_fingerprint" ]]; then
          echo "Refusing to replace an unexpected SFTP host key for $sftp_key" >&2
          exit 1
        fi
      else
        printf '{}\n' > "$sftp_known_hosts"
      fi

      sftp_known_hosts_tmp="$sftp_known_hosts.tmp.$$"
      ${pkgs.jq}/bin/jq \
        --arg key "$sftp_key" \
        --arg value "$sftp_fingerprint" \
        '.[$key] = $value' \
        "$sftp_known_hosts" > "$sftp_known_hosts_tmp"
      install -m 0600 -o ${user} -g staff "$sftp_known_hosts_tmp" "$sftp_known_hosts"
      rm -f "$sftp_known_hosts_tmp"
    '';
  };
}
