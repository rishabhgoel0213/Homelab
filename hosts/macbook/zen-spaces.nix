{ lib, ... }:
let
  domain = "therealrishabh.com";
  internal = "internal.${domain}";
  categories = builtins.fromJSON (builtins.readFile ../../components/projects/categories.json);
  categoryNames = [
    "research"
    "coursework"
    "development"
    "writing"
    "uncategorized"
  ];
  labels = {
    research = "Research";
    coursework = "Coursework";
    development = "Development";
    writing = "Writing";
    uncategorized = "Uncategorized";
  };
  pin = folder: position: title: url: {
    inherit
      folder
      position
      title
      url
      ;
    staticLabel = title;
  };
in
{
  homelab.apps.zen.managedSidebar = {
    spaces = {
      Workbench = {
        icon = "🧪";
        position = 10;
      };
      Homelab = {
        icon = "🏠";
        position = 20;
      };
    };
    folders =
      lib.listToAttrs (
        lib.imap0 (index: category: {
          name = "projects-${category}";
          value = {
            name = labels.${category};
            space = "Workbench";
            position = index * 10;
            live = {
              type = "rss";
              state = {
                url = "https://projects.${internal}/feeds/${category}.xml";
                interval = 300000;
                maxItems = 1000;
                timeRange = 0;
              };
            };
          };
        }) (builtins.filter (name: builtins.hasAttr name categories) categoryNames)
      )
      // {
        workbench-tools = {
          name = "Tools & Pages";
          space = "Workbench";
          position = 60;
        };
        homelab-apps = {
          name = "Everyday Apps";
          space = "Homelab";
          position = 0;
        };
        homelab-admin = {
          name = "Administration";
          space = "Homelab";
          position = 10;
        };
      };
    pins = {
      jupyterlab = pin "workbench-tools" 0 "JupyterLab" "https://lab.${internal}/lab";
      t3code = pin "workbench-tools" 10 "T3 Code" "https://t3code.${internal}";
      kicad = pin "workbench-tools" 20 "KiCad" "https://cad.${internal}";
      canvas = pin "workbench-tools" 30 "Canvas Mirror" "https://canvas.${internal}";
      blog-admin = pin "workbench-tools" 40 "Blog Admin" "https://blog.${internal}/admin";
      blog-preview = pin "workbench-tools" 50 "Blog Preview" "https://blog.${internal}";
      public-blog = pin "workbench-tools" 60 "Public Blog" "https://blog.${domain}";
      chat = pin "homelab-apps" 0 "Chat" "https://chat.${internal}";
      jellyfin = pin "homelab-apps" 10 "Jellyfin" "https://media.${internal}";
      vaultwarden = pin "homelab-apps" 20 "Vaultwarden" "https://vault.${internal}";
      syncthing = pin "homelab-admin" 0 "Syncthing" "https://sync.${internal}";
      backrest = pin "homelab-admin" 10 "Backups" "https://backups.${internal}";
      singlemail = pin "homelab-admin" 20 "Singlemail" "https://maildrop.${internal}";
    };
  };
}
