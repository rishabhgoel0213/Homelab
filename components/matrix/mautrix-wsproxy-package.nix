{
  lib,
  buildGoModule,
  fetchFromGitHub,
}:

buildGoModule rec {
  pname = "mautrix-wsproxy";
  version = "0-unstable-2022-04-18";

  src = fetchFromGitHub {
    owner = "mautrix";
    repo = "wsproxy";
    rev = "a5dd5f8dbc84c209d1b55a40d02bb2997a52539e";
    hash = "sha256-R5bn2uPlugWnsCCU7faRI5Rgi3kK8Jiai/HkrEFdKIQ=";
  };

  vendorHash = "sha256-fPedW6U5HID/q+0YPq1RBcjS+JUCD294gPWCUqFa2Pw=";

  ldflags = [
    "-s"
    "-w"
  ];

  meta = {
    description = "HTTP push to WebSocket proxy for remote Matrix appservices";
    homepage = "https://github.com/mautrix/wsproxy";
    license = lib.licenses.agpl3Plus;
    mainProgram = "mautrix-wsproxy";
  };
}
