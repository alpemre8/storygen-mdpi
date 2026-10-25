from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storygen_measurement_core import MeasurementProtocol, build_request_payload, assert_measurement_equal, ContractMismatchError

def test_contract_and_legacy_request_parity():
    p = MeasurementProtocol.load(ROOT, "configs/feature_measurement_v1.yaml")
    assert p.id == "feature-measurement-v1"
    assert p.config["measurement_protocol_version"] == "1.1.0"
    assert p.validate_legacy_parity()["verified"] is True
    payload = build_request_payload(prompt="PROMPT", model="qwen2.5-7b-q4", schema=p.schema, decoding=p.decoding, system_instruction=p.system_instruction, response_schema_name=p.response_schema_name)
    assert payload["messages"] == [
        {"role": "system", "content": "Return only valid JSON. No markdown. No explanation."},
        {"role": "user", "content": "PROMPT"},
    ]
    assert payload["response_format"]["json_schema"]["name"] == "storygen_response"
    assert payload["temperature"] == 0.0 and payload["max_tokens"] == 256
    assert "top_p" not in payload and "seed" not in payload

def test_exact_measurement_rejects_wrong_request_contract():
    p = MeasurementProtocol.load(ROOT, "configs/feature_measurement_v1.yaml")
    bad = dict(p.manifest())
    bad["request_contract_hash"] = "sha256:wrong"
    try:
        assert_measurement_equal(p.manifest(), bad)
    except ContractMismatchError:
        pass
    else:
        raise AssertionError("wrong request contract must be rejected")
