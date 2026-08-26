import base64
import json
import os
import struct
import urllib.error
import urllib.request
import zlib

import pytest


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


@pytest.mark.live
def test_krea2_raw_generates_a_real_1024px_png():
    if os.getenv("RUN_LIVE_KREA2_E2E") != "1":
        pytest.skip("set RUN_LIVE_KREA2_E2E=1 to call the deployed Krea 2 API")

    base_url = os.getenv("KREA2_BASE_URL", "http://10.2.10.33:8005").rstrip("/")
    timeout = float(os.getenv("KREA2_REQUEST_TIMEOUT", "1800"))
    payload = json.dumps(
        {
            "prompt": "A small red fox standing in fresh snow, natural light",
            "size": "1024x1024",
            "num_inference_steps": 28,
            "guidance_scale": 4.5,
            "seed": 42,
        }
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/v1/images/generations",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read()
            assert response.status == 200
    except urllib.error.HTTPError as error:
        error_body = error.read().decode(errors="replace")
        pytest.fail(
            f"Krea 2 returned HTTP {error.code} from {request.full_url}: "
            f"{error_body}"
        )
    except urllib.error.URLError as error:
        pytest.fail(f"Could not reach Krea 2 at {request.full_url}: {error.reason}")

    try:
        result = json.loads(response_body)
        png = base64.b64decode(result["data"][0]["b64_json"], validate=True)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        pytest.fail(f"Krea 2 returned an invalid image response: {error}")

    try:
        dimensions = _validated_png_dimensions(png)
    except ValueError as error:
        pytest.fail(f"Krea 2 returned an invalid PNG: {error}")
    assert dimensions == (1024, 1024)
