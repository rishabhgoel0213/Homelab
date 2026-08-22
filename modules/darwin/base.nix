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
    settings.experimental-features = [
      "nix-command"
      "flakes"
    ];
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
