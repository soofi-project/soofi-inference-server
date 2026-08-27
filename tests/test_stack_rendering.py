from copy import deepcopy
from pathlib import Path

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]
VARS_PATH = ROOT / "ansible/inventory/group_vars/gpu_nodes/vars.yaml"
TEMPLATES_PATH = ROOT / "ansible/templates"


def _combine(base, overrides, recursive=False):
    result = deepcopy(base)
    for key, value in overrides.items():
        if (
            recursive
            and isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = _combine(result[key], value, recursive=True)
        else:
            result[key] = deepcopy(value)
    return result


def _resolve_inventory_templates(value, environment, variables):
    if isinstance(value, dict):
        return {
            key: _resolve_inventory_templates(item, environment, variables)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_inventory_templates(item, environment, variables)
            for item in value
        ]
    if isinstance(value, str) and "{{" in value:
        return environment.from_string(value).render(**variables)
    return value


def _render(template_name, overrides=None, omit_image_generation_enabled=False):
    variables = yaml.safe_load(VARS_PATH.read_text())
    variables["hf_token"] = "hf_test_token"
    variables["ansible_facts"] = {
        "getent_passwd": {"mrk": ["x", "1000", "1000", "", "/home/mrk", "/bin/bash"]}
    }
    if overrides:
        variables = _combine(variables, overrides, recursive=True)
    if omit_image_generation_enabled:
        variables["image_generation_service"].pop("enabled")

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_PATH),
        undefined=jinja2.StrictUndefined,
        autoescape=False,
    )
    environment.filters["combine"] = _combine
    variables = _resolve_inventory_templates(variables, environment, variables)
    variables["active_models"] = [
        model for model in variables["models"] if model.get("enabled") is True
    ]
    rendered = environment.get_template(template_name).render(**variables)
    return yaml.safe_load(rendered)


def test_krea_raw_renders_as_failure_isolated_vllm_omni_service():
    compose = _render(
        "docker-compose.stack.yml.j2",
        overrides={"image_generation_service": {"enabled": True}},
    )
    litellm = _render("litellm-config.stack.yaml.j2")

    krea = compose["services"]["vllm-krea-2-raw"]
    assert krea["image"] == "vllm/vllm-omni:v0.26.0"
    assert krea["command"] == [
        "vllm",
        "serve",
        "krea/Krea-2-Raw",
        "--omni",
        "--enforce-eager",
        "--port",
        "8000",
    ]
    assert krea["ports"] == ["8005:8000"]
    assert krea["deploy"]["resources"]["reservations"]["devices"][0][
        "device_ids"
    ] == ["1"]
    assert krea["volumes"] == [
        "/opt/soofi/models/hf_cache:/root/.cache/huggingface"
    ]
    assert krea["environment"] == [
        "HUGGING_FACE_HUB_TOKEN=hf_test_token",
        "HF_TOKEN=hf_test_token",
        "HF_HUB_DISABLE_XET=1",
    ]
    assert krea["shm_size"] == "16gb"
    assert krea["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-f",
        "http://localhost:8000/health",
    ]
    assert "vllm-krea-2-raw" not in compose["services"]["litellm"]["depends_on"]
    assert "krea-2-raw" not in {
        model["model_name"] for model in litellm["model_list"]
    }


def test_comfyui_renders_as_an_independent_gpu_service():
    compose = _render("docker-compose.stack.yml.j2")
    litellm = _render("litellm-config.stack.yaml.j2")

    comfyui = compose["services"]["comfyui-krea2"]
    assert comfyui["image"] == (
        "soofi/comfyui-krea2:v0.30.0-torch2.13.0-cu130"
    )
    assert comfyui["user"] == "1000:1000"
    assert comfyui["restart"] == "unless-stopped"
    assert comfyui["init"] is True
    assert comfyui["ports"] == ["8188:8188"]
    assert comfyui["environment"] == ["TRITON_CACHE_DIR=/tmp/triton"]
    assert comfyui["deploy"]["resources"]["reservations"]["devices"][0][
        "device_ids"
    ] == ["1"]
    assert comfyui["volumes"] == [
        "/opt/soofi/models/comfyui:/comfyui/models:ro",
        "/home/mrk/image-gen-data/input:/comfyui/input",
        "/home/mrk/image-gen-data/output:/comfyui/output",
        "/home/mrk/image-gen-data/user:/comfyui/user",
    ]
    assert comfyui["command"] == [
        "--listen",
        "0.0.0.0",
        "--port",
        "8188",
        "--multi-user",
        "--disable-api-nodes",
        "--models-directory",
        "/comfyui/models",
        "--input-directory",
        "/comfyui/input",
        "--output-directory",
        "/comfyui/output",
        "--temp-directory",
        "/tmp/comfyui",
        "--user-directory",
        "/comfyui/user",
        "--database-url",
        "sqlite:////comfyui/user/comfyui.db",
    ]
    assert comfyui["shm_size"] == "16gb"
    assert comfyui["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-f",
        "http://localhost:8188/system_stats",
    ]
    assert "comfyui-krea2" not in compose["services"]["litellm"]["depends_on"]
    assert "comfyui-krea2" not in {
        model["model_name"] for model in litellm["model_list"]
    }


def test_disabling_comfyui_removes_only_its_service():
    compose = _render(
        "docker-compose.stack.yml.j2",
        overrides={"comfyui_service": {"enabled": False}},
    )

    assert "comfyui-krea2" not in compose["services"]
    assert "vllm-krea-2-raw" not in compose["services"]
    assert "vllm-qwen3-reranker-4b" in compose["services"]
    assert "falcon-perception" in compose["services"]


def test_krea_capacity_is_freed_without_changing_existing_runtimes():
    compose = _render("docker-compose.stack.yml.j2")
    services = compose["services"]

    assert "vllm-muse-glimmer-30b-multi" not in services
    assert services["vllm-qwen3-reranker-4b"]["image"] == (
        "vllm/vllm-openai:v0.27.1"
    )
    assert services["vllm-qwen38-27b-coding"]["image"] == (
        "vllm/vllm-openai:qwen38-x86_64-cu130"
    )
    assert services["falcon-perception"]["image"] == (
        "soofi/falcon-perception:v1.0.0-lowmem1"
    )


def test_image_generation_service_requires_explicit_enablement():
    compose = _render(
        "docker-compose.stack.yml.j2", omit_image_generation_enabled=True
    )

    assert "vllm-krea-2-raw" not in compose["services"]
