{ config, lib, pkgs, ... }:

let
  cfg = config.homelab;
in
{
  config = lib.mkIf cfg.privateDns.enable {
    services.coredns = {
      enable = true;
      extraArgs = [ "-dns.port=53" ];
      config = ''
        ${cfg.internalDomain}:53 {
          errors
          log
          template IN A {
            match ^(.+\.)?${cfg.internalSubdomain}\.${cfg.domain}\.$
            answer "{{ .Name }} 60 IN A ${cfg.tailnetIp}"
          }
          ${lib.optionalString (cfg.tailnetIpv6 != null) ''
          template IN AAAA {
            match ^(.+\.)?${cfg.internalSubdomain}\.${cfg.domain}\.$
            answer "{{ .Name }} 60 IN AAAA ${cfg.tailnetIpv6}"
          }
          ''}
        }

        .:53 {
          errors
          cache 300
          forward . 1.1.1.1 1.0.0.1
        }
      '';
    };

    assertions = [
      {
        assertion = cfg.tailnetIp != null;
        message = "homelab.privateDns.enable requires homelab.tailnetIp to be set.";
      }
    ];
  };
}
