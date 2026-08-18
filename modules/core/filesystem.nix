{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  shellVar = name: value: "${name}=${lib.escapeShellArg (toString value)}";
in
{
  environment.etc."homelab/paths.env".text = ''
    ${shellVar "homelab_user" "rishabh"}
    ${shellVar "homelab_group" "users"}
    ${shellVar "homelab_ops_root" cfg.paths.opsRoot}
    ${shellVar "homelab_state_root" cfg.paths.stateRoot}
    ${shellVar "homelab_projects_root" cfg.paths.projectsRoot}
    ${shellVar "homelab_user_home" cfg.paths.userHome}
    ${shellVar "homelab_sops_config" "${cfg.paths.opsRoot}/.sops.yaml"}
    ${shellVar "homelab_secrets_file" cfg.paths.secretsFile}
    ${shellVar "homelab_blog_site_source" cfg.paths.blogSiteSource}
    ${shellVar "homelab_blog_site_state" cfg.paths.blogSiteState}
    ${shellVar "homelab_resume_pdf" cfg.paths.resumePdf}
    ${shellVar "homelab_github_profile_readme" cfg.paths.githubProfileReadme}
    ${shellVar "homelab_remote_share" cfg.paths.remoteShare}
    ${shellVar "homelab_codex_home" cfg.paths.codexHome}
    ${shellVar "homelab_codex_config_source" cfg.paths.codexConfigSource}
    ${shellVar "homelab_codex_agents_source" cfg.paths.codexAgentsSource}
    ${shellVar "homelab_codex_plugin_root" cfg.paths.codexPluginRoot}
  '';

  systemd.tmpfiles.rules = [
    "d ${cfg.paths.opsRoot} 0755 rishabh users - -"
    "d ${cfg.paths.stateRoot} 0755 root root - -"
    "d ${cfg.paths.stateRoot}/backrest 0700 root root - -"
    "d ${cfg.paths.userHome}/.config 0755 rishabh users - -"
    "d ${cfg.paths.userHome}/.config/homelab 0700 rishabh users - -"
    "d ${cfg.paths.userHome}/Documents/resume 0755 rishabh users - -"
    "d ${cfg.paths.userHome}/Documents/github-profile 0755 rishabh users - -"
    "d ${cfg.paths.projectsRoot} 0755 rishabh users - -"
    "d ${cfg.paths.projectsRoot}/templates 0755 rishabh users - -"
    "d ${cfg.paths.remoteShare} 0755 rishabh users - -"
    "d ${cfg.paths.codexHome} 0700 rishabh users - -"
    "d ${cfg.paths.codexHome}/cache 0700 rishabh users - -"
    "d ${cfg.paths.codexHome}/log 0700 rishabh users - -"
    "d ${cfg.paths.codexHome}/plugins 0700 rishabh users - -"
    "d ${cfg.paths.codexHome}/tmp 0700 rishabh users - -"
    "d ${cfg.paths.opsRoot}/codex 0755 rishabh users - -"
    "d ${cfg.paths.codexPluginRoot} 0755 rishabh users - -"
  ];
}
