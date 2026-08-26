from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
STACK_DEPLOY_PATH = ROOT / "ansible/playbooks/stack_deploy.yaml"
OS_SETUP_PATH = ROOT / "ansible/playbooks/os_setup.yaml"


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


def test_compose_manages_a_defined_image_service_lifecycle_and_removes_orphans():
    start = _task_named("Start inference stack")

    assert "up -d --build --remove-orphans" in start["ansible.builtin.command"][
        "cmd"
    ]
    assert "active_models | length > 0" in start["when"]
    assert "image_generation_service is defined" in start["when"]
    assert "image_generation_service.enabled" not in start["when"]


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
