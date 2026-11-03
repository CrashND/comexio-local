"""Pure offline tests: no COMEXIO or Home Assistant calls required."""
from comexio_local.discovery import discover
from comexio_local.admin_api import command_name, make_push_command
from comexio_local.push_audit import audit_config
from comexio_local.push_setup import _stable_groups, push_sources
from test_discovery import _config

ENTRY = "aabbccdd-0101-test-entry"
PATH = "/api/webhook/REDACTED-TEST-SECRET"
BASE = "http://192.168.10.6:8123"


def _installed():
    config = _config()
    channels = discover(config)
    prefix = "CL" + ENTRY[:8].upper()
    device_id = "19"
    config["WebDevices"] = {device_id: {"Name": f"{prefix} Push", "Ip": " 192.168.10.6:8123", "BaseId": 9}}
    commands = {}
    plans = {}
    config.setdefault("FubModules", {})["10"] = {device_id: commands}
    for index, c in enumerate(push_sources(channels), 1):
        commands[str(200 + index)] = make_push_command(prefix, c, PATH)
    for group_index, (bucket, group) in enumerate(_stable_groups(push_sources(channels)), 1):
        fid = 100 + group_index
        config["Fubs"][str(fid)] = {"Name": f"{prefix} {bucket}", "Comment": f"Managed exclusively by COMEXIO Local ({ENTRY}), do not rename", "Active": True}
        elements, connections = {}, {}
        for i, channel in enumerate(group, 1):
            cmd_id = next(int(k) for k, v in commands.items() if v["Name"] == command_name(prefix, channel))
            ref_kind = 2 if channel.kind == "cover" else 1
            ref_id = channel.marker_id if channel.kind == "cover" else channel.io_id
            src_id, dest_id = 1000 + i * 2, 1001 + i * 2
            elements[str(src_id)] = {"reference": {"type": ref_kind, "ref_id": ref_id}}
            elements[str(dest_id)] = {"reference": {"type": 10, "ref_id": cmd_id}}
            connections[str(i)] = {"input": {"element": str(src_id)}, "output": {"0": {"element": str(dest_id)}}}
        plans[str(fid)] = {"elements": elements, "connections": connections}
    return config, plans, channels


def test_push_audit_new_install_reports_missing_but_does_not_write():
    config = _config()
    report = audit_config(config, {}, discover(config), ENTRY, PATH, BASE)
    assert report.sources == 2
    assert report.linked == 0
    assert report.as_dict()["status"] == "incomplete"
    assert len(report.missing_commands) == 2


def test_push_audit_ready_when_webio_target_commands_and_wires_match():
    config, plans, channels = _installed()
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert report.ready
    assert report.linked == report.sources == 2
    assert not report.missing_links
    assert not report.wrong_settings


def test_push_audit_detects_stale_ha_ip_without_exposing_secret():
    config, plans, channels = _installed()
    config["WebDevices"]["19"]["Ip"] = "192.168.10.99:8123"
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert report.wrong_settings
    assert "REDACTED" not in str(report.as_dict())
    assert not report.ready


def test_push_audit_detects_stale_webhook_without_exposing_secret():
    config, plans, channels = _installed()
    config["FubModules"]["10"]["19"]["201"]["Parameter"] = "/api/webhook/OLD"
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert any("Parameter" in item for item in report.wrong_settings)
    assert "OLD" not in str(report.as_dict())


def test_push_audit_detects_missing_physical_output_wire():
    config, plans, channels = _installed()
    first_plan = next(iter(plans.values()))
    first_plan["connections"].clear()
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert not report.ready
    assert report.linked == 1
    assert len(report.missing_links) == 1


def test_push_audit_detects_foreign_plan_name_collision():
    config, plans, channels = _installed()
    first_fub = next(k for k in config["Fubs"] if str(config["Fubs"][k].get("Name", "")).startswith("CL"))
    config["Fubs"][first_fub]["Comment"] = "Other integration"
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert any("Eigentümerkennung" in item for item in report.errors)
    assert not report.ready


def test_push_audit_marks_missing_comexio_metadata_as_unverified_not_ready():
    config, plans, channels = _installed()
    config["FubModules"]["10"]["19"]["201"].pop("Data")
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert report.as_dict()["status"] == "linked_unverified"
    assert not report.ready
