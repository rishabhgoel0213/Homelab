{ lib, pkgs, ... }:
let
  tools = pkgs.callPackage ../t3code/device-tools { };
  versions = (builtins.fromJSON (builtins.readFile ../t3code/device-tools/package.json)).dependencies;
  setup = pkgs.writeShellApplication {
    name = "mobile-ios-setup";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      export PATH="/run/current-system/sw/bin:$PATH"
      export MOBILE_MAS=${pkgs.mas}/bin/mas
      exec python3 ${./ios-setup.py} "$@"
    '';
  };
in {
  environment.systemPackages = [ tools setup pkgs.nodejs_24 pkgs.cocoapods pkgs.watchman pkgs.rsync pkgs.mas ];
  # SSH's initial environment must find the managed Node before any Homebrew Node.
  programs.zsh.shellInit = lib.mkBefore ''
    export PATH="/run/current-system/sw/bin:$PATH"
  '';
  system.activationScripts.postActivation.text = lib.mkAfter ''
    ${lib.concatMapStringsSep "\n" (name: let version = versions.${name}; in ''
      /usr/bin/install -d -m 0700 -o rishabhgoel -g staff /Users/rishabhgoel/.t3/device/tools
      target=/Users/rishabhgoel/.t3/device/tools/${name}@${version}
      if [ -e "$target" ] && [ ! -L "$target" ]; then
        if [ -e "$target.before-nix" ]; then
          echo "Refusing to overwrite T3 helper backup $target.before-nix" >&2
          exit 1
        fi
        /bin/mv "$target" "$target.before-nix"
      fi
      /bin/ln -sfn ${tools}/tools/${name}/${version} "$target"
    '') [ "agent-device" "expo-device-hub" ]}
  '';
}
