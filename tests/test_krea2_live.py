from copy import deepcopy
import json
import os
from pathlib import Path
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "tests/fixtures/krea2_turbo_style_reference_api.json"


def _validated_png_dimensions(png):
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("missing PNG signature")

    offset = 8
    dimensions = None
    compressed_image_data = []
    found_iend = False

    while offset < len(png):
        if len(png) - offset < 12:
            raise ValueError("truncated PNG chunk header")

        chunk_length = struct.unpack(">I", png[offset : offset + 4])[0]
        chunk_type = png[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_length
        chunk_end = data_end + 4
        if chunk_end > len(png):
            raise ValueError(f"truncated {chunk_type!r} PNG chunk")

        chunk_data = png[data_start:data_end]
        expected_crc = struct.unpack(">I", png[data_end:chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"invalid CRC for {chunk_type!r} PNG chunk")

        if offset == 8 and chunk_type != b"IHDR":
            raise ValueError("IHDR is not the first PNG chunk")
        if chunk_type == b"IHDR":
            if dimensions is not None or chunk_length != 13:
                raise ValueError("invalid PNG IHDR chunk")
            dimensions = struct.unpack(">II", chunk_data[:8])
        elif chunk_type == b"IDAT":
            compressed_image_data.append(chunk_data)
        elif chunk_type == b"IEND":
            if chunk_length != 0:
                raise ValueError("invalid PNG IEND chunk")
            found_iend = True
            offset = chunk_end
            break

        offset = chunk_end

    if not found_iend or offset != len(png):
        raise ValueError("PNG is missing a terminal IEND chunk")
    if dimensions is None:
        raise ValueError("PNG is missing IHDR dimensions")
    if not compressed_image_data:
        raise ValueError("PNG is missing IDAT image data")
    try:
        decompressed = zlib.decompress(b"".join(compressed_image_data))
    except zlib.error as error:
        raise ValueError(f"PNG IDAT data is not valid zlib data: {error}") from error
    if not decompressed:
        raise ValueError("PNG contains no decompressed image data")

    return dimensions


def _png_chunk(chunk_type, data):
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", checksum)
    )


def _reference_png(width=256, height=256):
    rows = []
    for y in range(height):
        pixels = bytearray()
        for x in range(width):
            pixels.extend(((x * 3) % 256, (y * 5) % 256, ((x + y) * 2) % 256))
        rows.append(b"\x00" + bytes(pixels))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        )
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )


def _request_json(request, timeout):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            if response.status < 200 or response.status >= 300:
                pytest.fail(
                    f"ComfyUI returned HTTP {response.status} from "
                    f"{request.full_url}"
                )
    except urllib.error.HTTPError as error:
        error_body = error.read().decode(errors="replace")
        pytest.fail(
            f"ComfyUI returned HTTP {error.code} from {request.full_url}: {error_body}"
        )
    except urllib.error.URLError as error:
        pytest.fail(f"Could not reach ComfyUI at {request.full_url}: {error.reason}")

    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        pytest.fail(f"ComfyUI returned invalid JSON from {request.full_url}: {error}")


def _upload_reference(base_url, png, timeout):
    boundary = f"----soofi-krea2-{uuid.uuid4().hex}"
    filename = "krea2_e2e_reference.png"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + png + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{base_url}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    result = _request_json(request, timeout)
    try:
        name = result["name"]
        subfolder = result.get("subfolder", "")
    except (KeyError, TypeError) as error:
        pytest.fail(f"ComfyUI returned an invalid upload response: {error}: {result!r}")
    return f"{subfolder}/{name}" if subfolder else name


def _wait_for_history(base_url, prompt_id, timeout):
    deadline = time.monotonic() + timeout
    history_url = f"{base_url}/history/{urllib.parse.quote(prompt_id)}"
    while time.monotonic() < deadline:
        history = _request_json(urllib.request.Request(history_url), min(timeout, 30))
        entry = history.get(prompt_id)
        if entry is not None:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                pytest.fail(f"ComfyUI generation failed: {status!r}")
            if status.get("completed") or entry.get("outputs"):
                return entry
        time.sleep(2)
    pytest.fail(f"ComfyUI did not complete prompt {prompt_id} within {timeout}s")


def test_generated_style_reference_fixture_is_a_valid_png():
    assert _validated_png_dimensions(_reference_png()) == (256, 256)


@pytest.mark.live
def test_krea2_turbo_style_reference_generates_a_real_1024px_png():
    if os.getenv("RUN_LIVE_KREA2_E2E") != "1":
        pytest.skip("set RUN_LIVE_KREA2_E2E=1 to call the deployed ComfyUI API")

    base_url = os.getenv("COMFYUI_BASE_URL", "http://10.2.10.33:8188").rstrip("/")
    timeout = float(os.getenv("COMFYUI_E2E_TIMEOUT", "1800"))

    stats = _request_json(
        urllib.request.Request(f"{base_url}/system_stats"), min(timeout, 30)
    )
    devices = stats.get("devices", [])
    assert devices, f"ComfyUI reported no compute devices: {stats!r}"
    assert any("cuda" in str(device.get("type", "")).lower() for device in devices), (
        f"ComfyUI is not reporting a CUDA device: {devices!r}"
    )

    reference_name = _upload_reference(base_url, _reference_png(), timeout)
    workflow = deepcopy(json.loads(WORKFLOW_PATH.read_text()))
    workflow["5"]["inputs"]["image"] = reference_name
    workflow["6"]["inputs"]["prompt"] = (
        "A small red fox standing in fresh snow, natural light, using the color "
        "palette and visual texture of the reference image"
    )
    queue_request = urllib.request.Request(
        f"{base_url}/prompt",
        data=json.dumps(
            {"prompt": workflow, "client_id": f"soofi-e2e-{uuid.uuid4().hex}"}
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    queued = _request_json(queue_request, timeout)
    prompt_id = queued.get("prompt_id")
    assert prompt_id, f"ComfyUI did not return a prompt_id: {queued!r}"

    history = _wait_for_history(base_url, prompt_id, timeout)
    images = [
        image
        for output in history.get("outputs", {}).values()
        for image in output.get("images", [])
    ]
    assert images, f"ComfyUI history contains no output images: {history!r}"
    image = images[0]
    view_query = urllib.parse.urlencode(
        {
            "filename": image["filename"],
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        }
    )
    view_request = urllib.request.Request(f"{base_url}/view?{view_query}")
    try:
        with urllib.request.urlopen(view_request, timeout=timeout) as response:
            png = response.read()
            assert response.status == 200
    except urllib.error.HTTPError as error:
        error_body = error.read().decode(errors="replace")
        pytest.fail(
            f"ComfyUI returned HTTP {error.code} from {view_request.full_url}: "
            f"{error_body}"
        )
    except urllib.error.URLError as error:
        pytest.fail(f"Could not download ComfyUI output: {error.reason}")

    try:
        dimensions = _validated_png_dimensions(png)
    except ValueError as error:
        pytest.fail(f"ComfyUI returned an invalid PNG: {error}")
    assert dimensions == (1024, 1024)
