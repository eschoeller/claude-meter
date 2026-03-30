import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dashboard  # noqa: E402


def _make_record(
    record_id,
    timestamp,
    utilization_5h=0.10,
    input_tokens=100,
    output_tokens=50,
    reset_5h=None,
    reset_7d=None,
    extra_windows=None,
    status_5h="allowed",
    status_7d="allowed",
):
    windows = {
        "5h": {"status": status_5h, "utilization": utilization_5h},
        "7d": {"status": status_7d, "utilization": utilization_5h * 0.5},
    }
    if reset_5h is not None:
        windows["5h"]["reset_ts"] = reset_5h
    if reset_7d is not None:
        windows["7d"]["reset_ts"] = reset_7d
    if extra_windows:
        windows.update(extra_windows)

    return {
        "id": record_id,
        "request_timestamp": timestamp,
        "response_timestamp": timestamp,
        "session_id": "session-1",
        "status": 200,
        "declared_plan_tier": "max_20x",
        "account_fingerprint": "acct-1",
        "response_model": "claude-opus-4-6",
        "usage": {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": output_tokens,
        },
        "ratelimit": {"windows": windows},
    }


def _sample_records():
    return [
        _make_record(1, "2026-03-25T20:00:00.000+00:00", utilization_5h=0.10),
        _make_record(2, "2026-03-25T20:01:00.000+00:00", utilization_5h=0.15),
        _make_record(3, "2026-03-25T20:02:00.000+00:00", utilization_5h=0.20),
    ]


def test_empty_data_returns_no_data_html():
    html = dashboard._generate_no_data_html()
    assert "No data yet" in html
    assert "<!DOCTYPE html>" in html
    assert "viewport" in html


def test_output_structure_with_sample_records():
    records = _sample_records()
    data = dashboard._build_dashboard_data(records)
    html = dashboard._generate_html(data)

    assert "<canvas" in html
    assert "const DATA =" in html
    assert "chart.js@4.4.7" in html
    assert "viewport" in html
    assert "claude-meter" in html
    assert "Window Overview" in html
    assert "Recent Activity" in html


def test_output_includes_window_reset_labels():
    records = [
        _make_record(
            1,
            "2026-03-25T20:00:00.000+00:00",
            utilization_5h=0.10,
            reset_5h=1774900800,
            reset_7d=1775268000,
            extra_windows={
                "7d_sonnet": {
                    "status": "allowed",
                    "utilization": 0.03,
                    "reset_ts": 1775491200,
                }
            },
        ),
        _make_record(
            2,
            "2026-03-25T20:01:00.000+00:00",
            utilization_5h=0.15,
            reset_5h=1774904400,
            reset_7d=1775268000,
            status_5h="allowed_warning",
            extra_windows={
                "7d_sonnet": {
                    "status": "allowed",
                    "utilization": 0.04,
                    "reset_ts": 1775491200,
                }
            },
        ),
    ]

    data = dashboard._build_dashboard_data(records)
    html = dashboard._generate_html(data)

    assert data["token_summary"]["windows"]["5h"]["reset_ts"] == 1774904400
    assert data["token_summary"]["windows"]["7d"]["reset_ts"] == 1775268000
    assert data["token_summary"]["windows"]["5h"]["status"] == "allowed_warning"
    assert "Reset: 2026-03-30 21:00 UTC" in html
    assert "Reset: 2026-04-04 02:00 UTC" in html
    assert "7d sonnet" in html
    assert "In: " in html


def test_output_flag_writes_to_path(tmp_path):
    records = _sample_records()
    data = dashboard._build_dashboard_data(records)
    html = dashboard._generate_html(data)

    out_file = tmp_path / "dashboard.html"
    out_file.write_text(html)

    assert out_file.exists()
    content = out_file.read_text()
    assert "<canvas" in content
    assert len(content) > 1000


def test_build_dashboard_data_returns_dict():
    records = _sample_records()
    data = dashboard._build_dashboard_data(records)
    assert isinstance(data, dict)
    assert "generated_at" in data
    assert "token_summary" in data
    assert "budget_estimates" in data
    assert "time_series_5h" in data
    assert "time_series_7d" in data
    assert "recent_activity" in data


def test_api_json_output():
    records = _sample_records()
    data = dashboard._build_dashboard_data(records)
    json_str = json.dumps(data)
    parsed = json.loads(json_str)
    assert parsed["token_summary"]["api_calls"] == 3
    assert "windows" in parsed["token_summary"]
    assert len(parsed["recent_activity"]) == 3


def test_api_json_empty_data():
    data = dashboard._build_dashboard_data([])
    json_str = json.dumps(data)
    parsed = json.loads(json_str)
    assert parsed["token_summary"]["api_calls"] == 0


def test_api_flag_outputs_json(tmp_path):
    """Integration test: run dashboard.py --api and verify JSON output."""
    norm_dir = tmp_path / "normalized"
    norm_dir.mkdir()
    record = json.dumps({
        "id": 1,
        "request_timestamp": "2026-03-25T20:00:00Z",
        "response_timestamp": "2026-03-25T20:00:01Z",
        "status": 200,
        "declared_plan_tier": "max_20x",
        "response_model": "claude-opus-4-6",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "ratelimit": {"windows": {"5h": {"utilization": 0.1}}},
    })
    (norm_dir / "2026-03-25.jsonl").write_text(record + "\n")

    result = subprocess.run(
        ["python3", "analysis/dashboard.py", str(tmp_path), "--api"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["token_summary"]["api_calls"] == 1
    assert data["recent_activity"]
