{
  inputs,
  pkgs,
  ...
}:

{
  system.primaryUser = "rishabhgoel";
  system.stateVersion = 6;
  system.configurationRevision = inputs.self.rev or inputs.self.dirtyRev or null;

  networking.hostName = "Rishabhs-MacBook-Air-4";

  nix = {
    # Keep the implementation and installer settings already in use on the
    # Mac. The initial nix-darwin activation takes ownership of nix.conf.
    package = pkgs.lixPackageSets.latest.lix;
    settings = {
      always-allow-substitutes = true;
      bash-prompt-prefix = "(nix:$name) ";
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      trusted-substituters = [ "https://cache.lix.systems" ];
      trusted-public-keys = [
        "cache.lix.systems:aBnZUw8zA7H35Cz2RyKFVs3H4PlGTLawyY5KRbvJR8o="
      ];
    };
    gc = {
      automatic = true;
      interval = {
        Weekday = 7;
        Hour = 3;
        Minute = 15;
      };
      options = "--delete-older-than 14d";
    };
    optimise.automatic = true;
  };

  nixpkgs.config = {
    allowUnfree = true;
    # Tabby 1.0.235 currently pins Electron 38 upstream.
    permittedInsecurePackages = [ "electron-38.8.4" ];
  };

  programs.zsh.enable = true;

  environment.systemPackages = with pkgs; [
    git
    just
    openssh
    ripgrep
  ];
}
