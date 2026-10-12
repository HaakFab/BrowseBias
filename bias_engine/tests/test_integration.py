"""
Integration tests for the Bias Engine with Mock LLM Provider.
"""
import json
import os
import tempfile
from pathlib import Path

from bias_engine import BiasEngine
from bias_engine.config import EngineConfig, LLMProviderConfig
from bias_engine.llm_providers import LLMProvider


class MockLLMProvider(LLMProvider):
    """Mock LLM that returns deterministic responses for identification and listwise ranking."""

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature=None,
    ) -> str:
        # Check if identification prompt
        if "Classify each numbered suggestion template" in system_prompt:
            # Parse lines from user_prompt
            lines = [l for l in user_prompt.split("\n") if ":" in l and l.split(":")[0].strip().isdigit()]
            results = []
            for line in lines:
                idx = int(line.split(":")[0].strip())
                text = line.split(":", 1)[1].strip()
                # Flag if text contains words like 'fraud', 'hoax', 'evil'
                is_pol = 1 if "fraud" in text or "president" in text else 0
                is_consp = 1 if "hoax" in text or "flat" in text else 0
                results.append({
                    "i": idx,
                    "p": is_pol,
                    "a": 0,
                    "c": is_consp,
                    "s": 0,
                    "r": 0,
                    "re": 0,
                })
            return json.dumps(results)

        # Check if listwise ranking prompt
        if "Rank them from MOST" in system_prompt:
            lines = [l for l in user_prompt.split("\n") if ":" in l and l.split(":")[0].strip().isdigit()]
            k = len(lines)
            # Return natural order 0..k-1
            return json.dumps({"order": list(range(k))})

        return "{}"


def test_full_pipeline_end_to_end():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = os.path.join(tmpdir, "data")
        engine_state_dir = os.path.join(tmpdir, "engine_state")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(engine_state_dir, exist_ok=True)

        # 1. Create dummy suggestions.jsonl
        suggestions_file = os.path.join(data_dir, "suggestions.jsonl")
        test_entries = [
            {"query": "donald trump", "suggestion": "donald trump fraud"},
            {"query": "climate change", "suggestion": "climate change hoax"},
            {"query": "weather", "suggestion": "weather today"},
            {"query": "pizza", "suggestion": "pizza near me"},
        ]
        with open(suggestions_file, "w", encoding="utf-8") as f:
            for e in test_entries:
                f.write(json.dumps(e) + "\n")

        # 2. Configure engine with mock provider
        cfg = EngineConfig(
            primary_provider="mock_model",
            providers={
                "mock_model": LLMProviderConfig(
                    name="mock_model",
                    provider_type="openai_compatible",
                    model="mock-v1",
                )
            },
            data_dir=data_dir,
            engine_state_dir=engine_state_dir,
            listwise_group_size=4,
        )

        engine = BiasEngine(config=cfg)
        # Inject mock provider
        mock_p = MockLLMProvider(cfg.providers["mock_model"])
        engine.primary_llm = mock_p
        engine.identifier.provider = mock_p
        engine.ranker.provider = mock_p

        # 3. Run Pipeline
        res = engine.run_pipeline()
        assert res["status"] == "ok"
        assert res["new_templates"] > 0

        # 4. Verify Lexicon File Written
        lexicon_file = cfg.lexicon_file
        assert os.path.exists(lexicon_file)
        with open(lexicon_file, "r", encoding="utf-8") as f:
            lexicon_data = json.load(f)

        assert len(lexicon_data) > 0
        # Check that scored entries have expected structure
        for text, entry in lexicon_data.items():
            assert "score" in entry
            assert "scores" in entry
            assert "mouseover" in entry

        # 5. Check Engine Status
        status = engine.get_status()
        assert status["total_scored_templates"] > 0
