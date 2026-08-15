{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  cfg = homelab.jupyterlab;
  stateDir = "${homelab.paths.stateRoot}/jupyterlab";
  fqdn = "lab.${homelab.internalSubdomain}.${homelab.domain}";
  pythonEnv = import ./jupyterlab-packages.nix { inherit pkgs; };
  codexAcp = pkgs.callPackage ./jupyterlab-codex-acp.nix { };
  jupyterArgs = [
    "--no-browser"
    "--ServerApp.ip=127.0.0.1"
    "--ServerApp.port=${toString cfg.port}"
    "--ServerApp.port_retries=0"
    "--ServerApp.root_dir=/"
    "--ServerApp.allow_remote_access=True"
    "--ServerApp.allow_unauthenticated_access=True"
    "--IdentityProvider.token="
    "--PasswordIdentityProvider.hashed_password="
    "--PasswordIdentityProvider.password_required=False"
    "--ContentsManager.allow_hidden=True"
  ];
in
{
  options.homelab.jupyterlab = {
    enable = lib.mkEnableOption "private authentication-free JupyterLab editor";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8888;
      description = "Loopback port used by JupyterLab.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pythonEnv ];

    systemd.tmpfiles.rules = [
      "d ${stateDir} 0700 rishabh users - -"
      "d ${stateDir}/config 0700 rishabh users - -"
      "d ${stateDir}/data 0700 rishabh users - -"
      "d ${stateDir}/runtime 0700 rishabh users - -"
      "d ${stateDir}/ipython 0700 rishabh users - -"
    ];

    systemd.services.jupyterlab = {
      description = "Private JupyterLab workspace editor";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      path = with pkgs; [
        bash
        coreutils
        git
        gnugrep
        gnused
        jq
        just
        nix
        openssh
        ripgrep
        codexAcp
        pythonEnv
      ];
      environment = {
        CODEX_HOME = homelab.paths.codexHome;
        HOME = homelab.paths.userHome;
        SHELL = "${pkgs.bash}/bin/bash";
        JUPYTER_CONFIG_DIR = "${stateDir}/config";
        JUPYTER_DATA_DIR = "${stateDir}/data";
        JUPYTER_RUNTIME_DIR = "${stateDir}/runtime";
        IPYTHONDIR = "${stateDir}/ipython";
      };
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = "/";
        ExecStart = "${pythonEnv}/bin/jupyter-lab ${lib.escapeShellArgs jupyterArgs}";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0077";
      };
    };

    homelab.routes.lab = {
      enable = true;
      host = "lab";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private authentication-free JupyterLab workspace editor";
    };

    homelab.t3code.browserEditorUrls.jupyterlab = "https://${fqdn}";

    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.jupyterlab.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
