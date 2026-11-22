{
  lib,
  buildGoModule,
  fetchFromGitHub,
  olm,
  withGoolm ? false,
}:

buildGoModule rec {
  pname = "mautrix-gmessages";
  version = "26.11";
  tag = "v0.2611.0";

  src = fetchFromGitHub {
    owner = "mautrix";
    repo = "gmessages";
    inherit tag;
    hash = "sha256-Z7Hv8OkQ1qbOLvQ11Vp9ssDXMT/V9Gva+S4eoDh7NgE=";
  };

  vendorHash = "sha256-y2RHc948wDe+LTi8J+Nc7v43kIWsMO9mFVkDSOFKImU=";

  ldflags = [
    "-s"
    "-w"
    "-X"
    "main.Tag=${tag}"
  ];

  buildInputs = lib.optional (!withGoolm) olm;
  tags = lib.optional withGoolm "goolm";

  doCheck = true;

  meta = {
    description = "Matrix-Google Messages puppeting bridge";
    homepage = "https://github.com/mautrix/gmessages";
    changelog = "https://github.com/mautrix/gmessages/blob/${src.rev}/CHANGELOG.md";
    license = lib.licenses.agpl3Only;
    mainProgram = "mautrix-gmessages";
  };
}
