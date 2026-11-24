{
  config,
  lib,
  macbookArtifacts,
  pkgs,
  ...
}:

let
  cfg = config.homelab.t3code;
  user = "rishabhgoel";
  userHome = "/Users/${user}";
  stateDir = "${userHome}/Library/Application Support/Homelab/t3code";
  launchdLabel = "com.therealrishabh.t3code";
  clientConfig = pkgs.writeText "t3code-mac-client.json" (
    builtins.toJSON {
      inherit stateDir launchdLabel;
      dataDir = cfg.dataDir;
      port = cfg.port;
      tailscaleServe = cfg.tailscaleServe;
      tailscaleServePort = cfg.tailscaleServePort;
      bootstrap = macbookArtifacts.t3code;
      ssh = "${pkgs.openssh}/bin/ssh";
      sshHost = "rishabh@nixos-pc";
      releaseFile = "/srv/state/t3code-mac-release/current.json";
      nix = "${config.nix.package}/bin/nix";
      nixEnv = "${config.nix.package}/bin/nix-env";
      publicKey = lib.removeSuffix "\n" (builtins.readFile ../darwin-deploy/cache-public-key.txt);
    }
  );
  command =
    name: action:
    pkgs.writeShellScriptBin name ''
      exec ${pkgs.python3}/bin/python3 ${./mac-client.py} --config ${clientConfig} ${action} "$@"
    '';
  t3Launcher = command "t3" "run";
  t3codeLauncher = command "t3code" "run";
  serverLauncher = command "t3code-server" "serve";
  updater = command "t3code-update" "update";
  restarter = command "t3code-restart" "restart";
  serverBinPath = lib.makeBinPath [
    pkgs.bash
    pkgs.coreutils
    pkgs.curl
    pkgs.fd
    pkgs.ffmpeg
    pkgs.findutils
    pkgs.gh
    pkgs.git
    pkgs.gnugrep
    pkgs.gnused
    pkgs.jq
    pkgs.just
    pkgs.nodejs_24
    pkgs.openssh
    pkgs.poppler-utils
    pkgs.ripgrep
    config.nix.package
  ];
in
{
  options.homelab.t3code = {
    enable = lib.mkEnableOption "Official T3 Code nightly backend server on macOS";
    port = lib.mkOption {
      type = lib.types.port;
      default = 3773;
      description = "Loopback port used by the T3 Code server.";
    };
    tailscaleServe = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Expose the T3 Code server over Tailscale Serve HTTPS on the tailnet.";
    };
    tailscaleServePort = lib.mkOption {
      type = lib.types.port;
      default = 443;
      description = "HTTPS port for Tailscale Serve when tailscaleServe is enabled.";
    };
    dataDir = lib.mkOption {
      type = lib.types.str;
      default = "${userHome}/.local/state/t3code";
      description = "T3 Code data directory (T3CODE_HOME).";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      t3Launcher
      t3codeLauncher
      serverLauncher
      updater
      restarter
    ];

    launchd.user.agents.t3code.serviceConfig = {
      Label = launchdLabel;
      ProgramArguments = [ "${serverLauncher}/bin/t3code-server" ];
      WorkingDirectory = userHome;
      RunAtLoad = true;
      KeepAlive = true;
      ThrottleInterval = 5;
      ExitTimeOut = 90;
      ProcessType = "Interactive";
      StandardOutPath = "${stateDir}/server.log";
      StandardErrorPath = "${stateDir}/server.err";
      EnvironmentVariables = {
        HOME = userHome;
        SHELL = "/bin/zsh";
        T3CODE_HOME = cfg.dataDir;
        DISABLE_AUTOUPDATER = "1";
        PATH = "/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:${serverBinPath}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
      };
    };

    launchd.user.agents.t3code-update.serviceConfig = {
      Label = "com.therealrishabh.t3code-update";
      ProgramArguments = [ "${updater}/bin/t3code-update" ];
      RunAtLoad = true;
      StartInterval = 1800;
      ProcessType = "Background";
      StandardOutPath = "${stateDir}/update.log";
      StandardErrorPath = "${stateDir}/update.err";
      EnvironmentVariables.PATH = "${
        lib.makeBinPath [
          pkgs.openssh
          config.nix.package
        ]
      }:/usr/bin:/bin";
    };

    system.activationScripts.preActivation.text = lib.mkAfter ''
      /usr/bin/codesign --verify --strict ${macbookArtifacts.t3code}/libexec/t3code/t3
      /usr/bin/install -d -m 0700 -o ${user} -g staff ${lib.escapeShellArg stateDir}
      /usr/bin/install -d -m 0700 -o ${user} -g staff ${lib.escapeShellArg cfg.dataDir}
    '';
  };
}
