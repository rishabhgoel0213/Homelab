{ lib, pkgs, ... }:
let
  tools = pkgs.callPackage ../t3code/device-tools { iosOnly = true; };
  versions = (builtins.fromJSON (builtins.readFile ../t3code/device-tools/package.json)).dependencies;
  deviceNode = pkgs.writeShellScript "mobile-device-node" ''
    # T3 prepends ~/.local/bin and Homebrew to PATH before starting Node.
    # Only its dedicated SSH alias sends this marker. Ordinary Mac shells keep adb.
    if [ "''${T3_DEVICE_IOS_ONLY:-}" = 1 ]; then
      export PATH=/run/current-system/sw/bin:/usr/bin:/bin:/usr/sbin:/sbin
      unset ANDROID_HOME ANDROID_SDK_ROOT
    fi
    exec ${pkgs.nodejs_24}/bin/node "$@"
  '';
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
  services.openssh.extraConfig = ''
    AcceptEnv T3_DEVICE_IOS_ONLY
  '';
  environment.systemPackages = [ tools setup pkgs.nodejs_24 pkgs.cocoapods pkgs.watchman pkgs.rsync pkgs.mas ];
  # SSH's initial environment must find the managed Node before any Homebrew Node.
  programs.zsh.shellInit = lib.mkBefore ''
    export PATH="/run/current-system/sw/bin:$PATH"
  '';
  system.activationScripts.postActivation.text = lib.mkAfter ''
    /usr/bin/install -d -m 0755 -o rishabhgoel -g staff /Users/rishabhgoel/.local/bin
    if [ -e /Users/rishabhgoel/.local/bin/node ] && [ ! -L /Users/rishabhgoel/.local/bin/node ]; then
      echo "Refusing to replace an unmanaged ~/.local/bin/node" >&2
      exit 1
    fi
    /bin/ln -sfn ${deviceNode} /Users/rishabhgoel/.local/bin/node
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
