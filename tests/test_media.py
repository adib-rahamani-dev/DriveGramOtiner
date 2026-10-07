import json
from types import SimpleNamespace

import httpx

from drivegram.security import safe_filename
from drivegram.telegram import Telegram, streamable_video


def box(kind, payload=b""):
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def test_original_filename_preserved_safely_across_windows_and_linux():
    assert safe_filename("ویدیو اصلی.mkv") == "ویدیو اصلی.mkv"
    assert "/" not in safe_filename("../../outside.mp4")
    assert "\\" not in safe_filename("..\\outside.mp4")
    assert safe_filename("CON.mp4") == "file_CON.mp4"
    assert len(safe_filename("نام" * 200 + ".mkv").encode("utf-8")) <= 200
    assert safe_filename("نام" * 200 + ".mkv").endswith(".mkv")


def test_probe_requires_codec_and_fast_start_without_changing_bytes(tmp_path, monkeypatch):
    path = tmp_path / "media.mp4"
    data = box(b"ftyp", b"isom") + box(b"moov") + box(b"mdat", b"data")
    path.write_bytes(data)
    metadata = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
                            {"codec_type": "audio", "codec_name": "aac"}],
                "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "2.5"}}
    monkeypatch.setattr("drivegram.telegram.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(metadata)))
    assert streamable_video(path) == {"width": 1280, "height": 720, "duration": 2}
    assert path.read_bytes() == data
    metadata["streams"][0]["codec_name"] = "hevc"
    assert streamable_video(path) is None
    metadata["streams"][0]["codec_name"] = "h264"
    path.write_bytes(box(b"mdat", b"data") + box(b"moov"))
    assert streamable_video(path) is None


def test_local_file_send_video_or_document_and_result_ids(settings, tmp_path, monkeypatch):
    path = (tmp_path / "media.mp4").resolve()
    path.write_bytes(b"unaltered")
    payloads = []
    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        kind = "video" if request.url.path.endswith("sendVideo") else "document"
        return httpx.Response(200, json={"ok": True, "result": {
            "chat": {"id": -10012345}, "message_id": 5, kind: {"file_id": "stored-id"}}})
    api = Telegram(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("drivegram.telegram.streamable_video", lambda _: {"width": 1280, "height": 720, "duration": 2})
    assert api.send(path, "original.mp4") == ("-10012345", 5, "stored-id")
    assert payloads[-1]["video"] == path.as_uri() and payloads[-1]["supports_streaming"] is True
    monkeypatch.setattr("drivegram.telegram.streamable_video", lambda _: None)
    api.send(path, "original.mkv")
    assert payloads[-1]["document"] == path.as_uri()
    assert payloads[-1]["disable_content_type_detection"] is True
    assert payloads[-1]["caption"] == "original.mkv"
    assert path.read_bytes() == b"unaltered"
    api.close()
