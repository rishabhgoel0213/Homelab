{
  lib,
  pkgs,
  presets,
}:

let
  dispatcherCases = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (name: preset: ''
      ${lib.escapeShellArg name})
        exec ${preset.cli}/bin/vscodium-open-${name} "$@"
        ;;
    '') presets
  );
  presetListing = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (
      name: preset:
      "printf '%-16s %s\\n' ${lib.escapeShellArg name} ${lib.escapeShellArg preset.displayName}"
    ) presets
  );
in
pkgs.writeShellApplication {
  name = "vscodium-env";
  text = ''
    usage() {
      cat >&2 <<'USAGE'
    Usage:
      vscodium-env list
      vscodium-env open PRESET [PATH...]
    USAGE
    }

    command="''${1:-}"
    case "$command" in
      list)
        [[ "$#" -eq 1 ]] || { usage; exit 2; }
        ${presetListing}
        ;;
      open)
        [[ "$#" -ge 2 ]] || { usage; exit 2; }
        preset="$2"
        shift 2
        case "$preset" in
          ${dispatcherCases}
          *)
            printf 'vscodium-env: unknown preset: %s\n' "$preset" >&2
            exit 2
            ;;
        esac
        ;;
      *)
        usage
        exit 2
        ;;
    esac
  '';
}
