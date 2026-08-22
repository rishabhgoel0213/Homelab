{ ... }:

{
  # Keep the App Store/standalone architecture for the first migration. Its
  # node identity is stored under /Library/Tailscale, which is covered by the
  # encrypted backup. Do not enable nix-darwin's open-source tailscaled module
  # at the same time: it uses a different state layout and service model.
  homebrew = {
    enable = true;
    casks = [ "tailscale-app" ];
    onActivation = {
      autoUpdate = false;
      upgrade = false;
      # Never remove or zap unrelated packages during this migration.
      cleanup = "none";
    };
  };

  # Tailscale Serve/Funnel declarations will be added here after the first
  # state-preserving activation and an explicit reachability review.
}
