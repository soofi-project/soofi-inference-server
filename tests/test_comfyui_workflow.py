import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "tests/fixtures/krea2_turbo_style_reference_api.json"


def _node_by_type(workflow, class_type):
    return next(
        node for node in workflow.values() if node["class_type"] == class_type
    )


def test_native_api_workflow_matches_the_official_one_reference_turbo_path():
    workflow = json.loads(WORKFLOW_PATH.read_text())

    assert _node_by_type(workflow, "UNETLoader")["inputs"]["unet_name"] == (
        "krea2_turbo_int8_convrot.safetensors"
    )
    assert _node_by_type(workflow, "CLIPLoader")["inputs"] == {
        "clip_name": "qwen3vl_4b_fp8_scaled.safetensors",
        "type": "krea2",
        "device": "default",
    }
    assert _node_by_type(workflow, "VAELoader")["inputs"]["vae_name"] == (
        "qwen_image_vae.safetensors"
    )
    assert _node_by_type(workflow, "LoraLoaderModelOnly")["inputs"]["lora_name"] == (
        "krea2_style_reference.safetensors"
    )
    assert _node_by_type(workflow, "BasicScheduler")["inputs"]["steps"] == 8
    assert _node_by_type(workflow, "EmptyLatentImage")["inputs"] == {
        "width": 1024,
        "height": 1024,
        "batch_size": 1,
    }
    encoder = _node_by_type(workflow, "TextEncodeQwenImageEditPlus")
    assert encoder["inputs"]["image1"] == ["5", 0]
    assert "image2" not in encoder["inputs"]
    assert "image3" not in encoder["inputs"]
    assert encoder["inputs"]["prompt"] == "__PROMPT__"
    assert _node_by_type(workflow, "LoadImage")["inputs"]["image"] == (
        "__REFERENCE_IMAGE__"
    )
    assert not any(node["class_type"] == "TextGenerate" for node in workflow.values())
