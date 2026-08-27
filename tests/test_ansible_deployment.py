from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
STACK_DEPLOY_PATH = ROOT / "ansible/playbooks/stack_deploy.yaml"
OS_SETUP_PATH = ROOT / "ansible/playbooks/os_setup.yaml"
COMFYUI_DOCKERFILE_PATH = ROOT / "docker/Dockerfile.comfyui-krea2"


def _stack_tasks():
    plays = yaml.safe_load(STACK_DEPLOY_PATH.read_text())
    return plays[0]["tasks"]


def _task_named(name):
    return next(task for task in _stack_tasks() if task["name"] == name)


def _os_task_named(name):
    plays = yaml.safe_load(OS_SETUP_PATH.read_text())
    return next(task for task in plays[0]["tasks"] if task["name"] == name)


def test_enabled_krea_download_resumes_with_xet_disabled_until_complete():
    task_names = {task["name"] for task in _stack_tasks()}
    assert "Check if Krea 2 weights are already cached" not in task_names

    download = _task_named("Download Krea 2 weights from HuggingFace")
    command = download["ansible.builtin.command"]["cmd"]
    assert "--entrypoint hf" in command
    assert (
        "-v {{ deploy_dir }}/models/hf_cache:/root/.cache/huggingface"
        in command
    )
    assert "-e HF_HUB_DISABLE_XET=1" in command
    assert "{{ image_generation_service.image }}" in command
    assert "download {{ image_generation_service.hf_name }}" in command
    assert download["when"] == [
        "image_generation_service is defined",
        "image_generation_service.enabled | default(false)",
    ]


def test_image_generation_service_manages_its_configured_firewall_port():
    firewall = _os_task_named(
        "Allow enabled image generation service port through UFW"
    )

    assert firewall["community.general.ufw"] == {
        "rule": "allow",
        "port": "{{ image_generation_service.internal_port }}",
        "proto": "tcp",
    }
    assert "image_generation_service is defined" in firewall["when"]
    assert (
        "image_generation_service.enabled | default(false)" in firewall["when"]
    )

    removal = _os_task_named(
        "Remove disabled image generation service port from UFW"
    )
    assert removal["community.general.ufw"] == {
        "rule": "allow",
        "port": "{{ image_generation_service.internal_port }}",
        "proto": "tcp",
        "delete": True,
    }
    assert "image_generation_service is defined" in removal["when"]
    assert (
        "not (image_generation_service.enabled | default(false))"
        in removal["when"]
    )


def test_comfyui_manages_its_unrestricted_firewall_port():
    firewall = _os_task_named("Allow enabled ComfyUI port through UFW")
    assert firewall["community.general.ufw"] == {
        "rule": "allow",
        "port": "{{ comfyui_service.internal_port }}",
        "proto": "tcp",
    }
    assert firewall["when"] == [
        "comfyui_service is defined",
        "comfyui_service.enabled | default(false)",
    ]

    removal = _os_task_named("Remove disabled ComfyUI port from UFW")
    assert removal["community.general.ufw"] == {
        "rule": "allow",
        "port": "{{ comfyui_service.internal_port }}",
        "proto": "tcp",
        "delete": True,
    }
    assert removal["when"] == [
        "comfyui_service is defined",
        "not (comfyui_service.enabled | default(false))",
    ]


def test_compose_manages_a_defined_image_service_lifecycle_and_removes_orphans():
    start = _task_named("Start inference stack")

    assert "up -d --build --remove-orphans" in start["ansible.builtin.command"][
        "cmd"
    ]
    assert "active_models | length > 0" in start["when"]
    assert "image_generation_service is defined" in start["when"]
    assert "comfyui_service is defined" in start["when"]
    assert "image_generation_service.enabled" not in start["when"]
    assert "comfyui_service.enabled" not in start["when"]


def test_enabled_krea_api_has_an_independent_fail_loud_health_wait():
    health = _task_named("Wait for Krea 2 image API to be ready")

    assert health["ansible.builtin.uri"] == {
        "url": (
            "http://localhost:{{ image_generation_service.internal_port }}"
            "{{ image_generation_service.healthcheck_path | default('/health') }}"
        ),
        "status_code": 200,
    }
    assert health["register"] == "krea_health"
    assert health["until"] == "krea_health.status == 200"
    assert health["retries"] >= 40
    assert health["delay"] == 30
    assert "image_generation_service.enabled | default(false)" in health["when"]
    assert "failed_when" not in health
    assert "ignore_errors" not in health


def test_enabled_comfyui_has_an_independent_fail_loud_health_wait():
    health = _task_named("Wait for ComfyUI to be ready")
    assert health["ansible.builtin.uri"] == {
        "url": (
            "http://localhost:{{ comfyui_service.internal_port }}"
            "{{ comfyui_service.healthcheck_path }}"
        ),
        "status_code": 200,
    }
    assert health["register"] == "comfyui_health"
    assert health["until"] == "comfyui_health.status == 200"
    assert health["retries"] >= 20
    assert health["delay"] == 15
    assert "comfyui_service.enabled | default(false)" in health["when"]
    assert "failed_when" not in health
    assert "ignore_errors" not in health


def test_enabled_comfyui_resolves_its_user_and_preserves_data_directories():
    identity = _task_named("Resolve ComfyUI service account")
    assert identity["ansible.builtin.getent"] == {
        "database": "passwd",
        "key": "{{ comfyui_service.user }}",
        "fail_key": True,
    }
    assert "comfyui_service.enabled | default(false)" in identity["when"]

    directories = _task_named("Create persistent ComfyUI directories")
    assert directories["ansible.builtin.file"] == {
        "path": "{{ item }}",
        "state": "directory",
        "owner": "{{ comfyui_service.user }}",
        "group": "{{ comfyui_service.user }}",
        "mode": "0755",
    }
    assert directories["loop"] == [
        "{{ comfyui_service.models_dir }}",
        "{{ comfyui_service.data_dir }}",
        "{{ comfyui_service.data_dir }}/input",
        "{{ comfyui_service.data_dir }}/output",
        "{{ comfyui_service.data_dir }}/user",
    ]
    assert "comfyui_service.enabled | default(false)" in directories["when"]


def test_enabled_comfyui_selects_its_pinned_custom_image():
    selection = _task_named(
        "Select custom images referenced by enabled models or services"
    )
    expression = selection["ansible.builtin.set_fact"]["active_custom_images"]

    assert "comfyui_service.image" in expression
    assert "comfyui_service.enabled | default(false)" in expression


def test_comfyui_image_pins_the_approved_compatible_local_runtime():
    dockerfile = COMFYUI_DOCKERFILE_PATH.read_text()

    assert "python:3.12-slim-bookworm" in dockerfile
    assert "ARG COMFYUI_VERSION=v0.30.0" in dockerfile
    assert "ARG TORCH_VERSION=2.13.0" in dockerfile
    assert "ARG TORCHVISION_VERSION=0.28.0" in dockerfile
    assert "ARG TORCHAUDIO_VERSION=2.11.0" in dockerfile
    assert '"torch==${TORCH_VERSION}"' in dockerfile
    assert '"torchvision==${TORCHVISION_VERSION}"' in dockerfile
    assert '"torchaudio==${TORCHAUDIO_VERSION}"' in dockerfile
    assert "https://download.pytorch.org/whl/cu130" in dockerfile
    assert "m.version('comfyui-workflow-templates') == '0.11.27'" in dockerfile
    assert 'ENTRYPOINT ["python", "main.py"]' in dockerfile


def test_comfyui_image_fails_build_without_the_official_style_template():
    dockerfile = COMFYUI_DOCKERFILE_PATH.read_text()

    assert "comfyui_workflow_templates_json" in dockerfile
    assert "image_krea2_turbo_int8_image_style_reference.json" in dockerfile
    assert "Krea-2 Int8: Image Style Reference" in dockerfile
    assert "index.json" in dockerfile
    assert ".is_file()" in dockerfile


def test_comfyui_models_resume_and_are_verified_before_stack_start():
    task_names = [task["name"] for task in _stack_tasks()]
    inspect = _task_named("Inspect existing ComfyUI model files")
    reject = _task_named("Reject corrupt existing ComfyUI model files")
    download = _task_named("Download missing ComfyUI model files")
    verify = _task_named("Verify downloaded ComfyUI model files")
    promote = _task_named("Promote verified ComfyUI model files")

    assert inspect["ansible.builtin.stat"] == {
        "path": "{{ comfyui_service.models_dir }}/{{ item.path }}",
        "checksum_algorithm": "sha256",
    }
    assert "expected size {{ item.item.size }}" in reject[
        "ansible.builtin.assert"
    ]["fail_msg"]
    assert "expected SHA-256 {{ item.item.sha256 }}" in reject[
        "ansible.builtin.assert"
    ]["fail_msg"]
    assert "actual size {{ item.stat.size" in reject["ansible.builtin.assert"][
        "fail_msg"
    ]
    assert "actual SHA-256 {{ item.stat.checksum" in reject[
        "ansible.builtin.assert"
    ]["fail_msg"]

    argv = download["ansible.builtin.command"]["argv"]
    assert "--continue-at" in argv
    assert "{{ comfyui_service.models_dir }}/{{ item.item.path }}.partial" in argv
    assert (
        "{{ comfyui_service.model_base_url }}/{{ item.item.path }}" in argv
    )
    assert "not (item.stat.exists | default(false))" in download["when"]
    assert "comfyui_service.enabled | default(false)" in download["when"]
    assert "not ansible_check_mode" in download["when"]

    assert verify["ansible.builtin.assert"]["that"] == [
        "item.stat.exists | default(false)",
        "(item.stat.size | default(-1)) == item.item.item.size",
        "(item.stat.checksum | default('missing')) == item.item.item.sha256",
    ]
    assert promote["ansible.builtin.command"]["argv"][0] == "mv"
    assert task_names.index("Verify downloaded ComfyUI model files") < task_names.index(
        "Start inference stack"
    )
    assert task_names.index("Promote verified ComfyUI model files") < task_names.index(
        "Start inference stack"
    )
