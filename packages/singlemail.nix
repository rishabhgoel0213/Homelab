{
  lib,
  python3,
  writeShellApplication,
}:

writeShellApplication {
  name = "singlemail";
  runtimeInputs = [ python3 ];
  text = ''
    if [[ -r /run/secrets/singlemail.env ]]; then
      set -a
      # shellcheck disable=SC1091
      . /run/secrets/singlemail.env
      set +a
    fi
    exec python3 ${../scripts/singlemail.py} "$@"
  '';

  meta = {
    description = "Purpose-scoped disposable inbox CLI and private gateway";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "singlemail";
  };
}
