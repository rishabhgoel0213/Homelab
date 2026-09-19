{ lib, pkgs, ... }:

let
  user = "rishabh";
  group = "users";
  home = "/home/${user}";
  projectsExtension = pkgs.callPackage ./projects-extension/package.nix { };
  extensionSets = import ./extensions.nix {
    inherit pkgs projectsExtension;
  };
  extensionJsonFile = pkgs.writeTextFile {
    name = "vscodium-remote-extensions-json";
    destination = "/share/vscode/extensions/extensions.json";
    text = pkgs.vscode-utils.toExtensionJson extensionSets.full;
  };
  managedExtensionDir = pkgs.buildEnv {
    name = "vscodium-remote-extensions";
    paths = extensionSets.full ++ [ extensionJsonFile ];
  };
in
{
  system.activationScripts.vscodiumRemoteExtensions = {
    deps = [ "users" ];
    text = ''
      server_root=${lib.escapeShellArg "${home}/.vscode-server"}
      extensions_root="$server_root/extensions"
      managed_manifest="$extensions_root/.homelab-managed-extensions"

      for managed_directory in "$server_root" "$extensions_root"; do
        if [[ -L "$managed_directory" || ( -e "$managed_directory" && ! -d "$managed_directory" ) ]]; then
          echo "Refusing unsafe remote VSCodium directory at $managed_directory" >&2
          exit 1
        fi
        install -d -m 0700 -o ${user} -g ${group} "$managed_directory"
      done

      if [[ -f "$managed_manifest" ]]; then
        while IFS= read -r extension_name; do
          case "$extension_name" in
            ""|*[!A-Za-z0-9._-]*)
              echo "Refusing invalid managed VSCodium extension name: $extension_name" >&2
              exit 1
              ;;
          esac
          extension_target="$extensions_root/$extension_name"
          if [[ -L "$extension_target" ]]; then
            extension_source="$(readlink "$extension_target")"
            case "$extension_source" in
              /nix/store/*) rm -f "$extension_target" ;;
            esac
          fi
        done < "$managed_manifest"
      fi

      manifest_tmp="$(mktemp "$extensions_root/.homelab-managed-extensions.XXXXXX")"
      for extension_source in ${managedExtensionDir}/share/vscode/extensions/*; do
        [[ -d "$extension_source" ]] || continue
        extension_name="''${extension_source##*/}"
        extension_target="$extensions_root/$extension_name"
        if [[ -e "$extension_target" && ! -L "$extension_target" ]]; then
          echo "Refusing to replace unmanaged remote VSCodium extension at $extension_target" >&2
          rm -f "$manifest_tmp"
          exit 1
        fi
        ln -sfn "$extension_source" "$extension_target"
        chown -h ${user}:${group} "$extension_target"
        printf '%s\n' "$extension_name" >> "$manifest_tmp"
      done

      chown ${user}:${group} "$manifest_tmp"
      chmod 0600 "$manifest_tmp"
      mv -f "$manifest_tmp" "$managed_manifest"

      if [[ -L "$extensions_root/extensions.json" || ( -e "$extensions_root/extensions.json" && ! -f "$extensions_root/extensions.json" ) ]]; then
        echo "Refusing unsafe remote VSCodium extension cache at $extensions_root/extensions.json" >&2
        exit 1
      fi
      install -m 0600 -o ${user} -g ${group} \
        ${managedExtensionDir}/share/vscode/extensions/extensions.json \
        "$extensions_root/extensions.json"
    '';
  };
}
