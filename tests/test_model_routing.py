from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]

RESEARCH_MODELS = {
    "fast": "hf.openai/gpt-oss-120b:cerebras",
    "research": "hf.zai-org/GLM-5.2:zai-org",
    "html": (
        "hf.moonshotai/Kimi-K2.7-Code:novita"
        "?temperature=1.0&top_p=0.95&reasoning=on"
    ),
}
LEGACY_MODEL = "hf.moonshotai/Kimi-K2-Thinking:featherless-ai"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def assert_non_fireworks_route(model: str) -> None:
    route = model.partition("?")[0]
    assert route.startswith("hf.")
    assert ":" in route
    assert route.rsplit(":", 1)[1] != "fireworks-ai"
    assert "fireworks" not in model.casefold()


def test_research_models_pin_non_fireworks_providers() -> None:
    config = load_yaml(ROOT / "research/fast-agent.yaml")
    models = config["model_references"]["system"]

    assert config["default_model"] == "$system.research"
    assert models == RESEARCH_MODELS
    for model in models.values():
        assert_non_fireworks_route(model)


def test_legacy_model_pins_a_non_fireworks_provider() -> None:
    config = load_yaml(ROOT / "deploy/research-tool-one/fast-agent.yaml")

    assert config["default_model"] == LEGACY_MODEL
    assert_non_fireworks_route(config["default_model"])
