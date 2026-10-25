"""Additive deterministic reviewer diagnostics; historical kernels stay frozen."""

ANALYZER_VERSION = "reviewer-r1-deterministic-v1"
FEATURES = {
    "pacing": "llm_pacing_score",
    "emotion": "llm_emotion_intensity_score",
    "dialogue": "llm_dialogue_density_score",
    "action": "llm_action_density_score",
    "character": "llm_character_interaction_score",
}
CONDITIONS = ("DP-v1", "CG-v1")
ENDPOINT_ATOL = 1e-12


class BlockedAnalysis(RuntimeError):
    """A diagnostic's required original input is unavailable."""
