{ pkgs }:
let
  janestreetAgentSkills = pkgs.fetchFromGitHub {
    owner = "janestreet";
    repo = "agent_skills";
    rev = "469868f4489cbdbe178c775a0af05bb6bef63689";
    hash = "sha256-EuYu0C7d2T4Y3RlsTm5/22jZcCrrTPpdnGhcx7SOOeM=";
  };
in
{
  # Jane Street's Socratic tutoring skill (MIT).
  # Add more pinned external skills with `skills promote <name>` or local skills
  # under ./builtin/<name>/.
  "socratic-tutor" = {
    path = "${janestreetAgentSkills}/socratic-tutor";
    source = "github:janestreet/agent_skills/socratic-tutor";
    rev = "469868f4489cbdbe178c775a0af05bb6bef63689";
  };
}
