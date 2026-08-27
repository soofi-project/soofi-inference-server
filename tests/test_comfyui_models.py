from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
VARS_PATH = ROOT / "ansible/inventory/group_vars/gpu_nodes/vars.yaml"


def test_krea2_turbo_manifest_contains_only_the_verified_official_assets():
    variables = yaml.safe_load(VARS_PATH.read_text())

    assert variables["comfyui_service"]["models"] == [
        {
            "path": "diffusion_models/krea2_turbo_int8_convrot.safetensors",
            "size": 13_492_686_496,
            "sha256": (
                "8e4eeda70dd5037ab1ba2bef6b417f9f901e26093117cf397f741fc1fdaaf3f1"
            ),
        },
        {
            "path": "text_encoders/qwen3vl_4b_fp8_scaled.safetensors",
            "size": 5_242_467_968,
            "sha256": (
                "54bd5144df0bbc25dd6ccadfcb826b521445a1b06ae5a42570bdd2974ca87094"
            ),
        },
        {
            "path": "vae/qwen_image_vae.safetensors",
            "size": 253_806_246,
            "sha256": (
                "a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f"
            ),
        },
        {
            "path": "loras/krea2_style_reference.safetensors",
            "size": 457_111_760,
            "sha256": (
                "f50df5a9e62e4be8aa926a63dd5bb1a64770c4004f763c1208007ae13daa82b8"
            ),
        },
    ]
