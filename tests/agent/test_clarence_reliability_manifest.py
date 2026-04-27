import json

from agent.clarence_reliability.cases import load_builtin_cases
from agent.clarence_reliability.manifest import assert_metadata_only, build_manifest, manifest_to_dict, write_manifest


def test_manifest_is_metadata_only_and_deterministic(tmp_path):
    cases = load_builtin_cases()
    manifest_a = manifest_to_dict(build_manifest(cases, case_root=tmp_path))
    manifest_b = manifest_to_dict(build_manifest(cases, case_root=tmp_path))

    assert manifest_a == manifest_b
    assert assert_metadata_only(manifest_a) == []

    raw = json.dumps(manifest_a, sort_keys=True)
    assert "What do you remember" not in raw
    assert "You prefer" not in raw
    assert "args" not in raw
    assert "result" not in raw


def test_manifest_writer_uses_sorted_json(tmp_path):
    path = tmp_path / "manifest.json"
    manifest = build_manifest(load_builtin_cases(), case_root=tmp_path)

    write_manifest(manifest, path)

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == manifest_to_dict(manifest)
    assert text.index('"cases"') < text.index('"harness"')


def test_metadata_only_scanner_rejects_raw_payload_and_secret():
    manifest = {
        "manifest_version": 0,
        "harness": "clarence-reliability",
        "cases": [
            {
                "id": "bad",
                "path": "bad.yaml",
                "prompt": "raw user text",
                "sha256": "sk-test-abcdef123456",
            }
        ],
    }

    errors = assert_metadata_only(manifest)

    assert any("raw payload key" in error for error in errors)
    assert any("secret-shaped value" in error for error in errors)
