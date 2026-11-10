"""One canonical COMEXIO Local Web-IO command for both firmware write paths.

Firmware 11 uses a JSON base-type import for the initial command and a separate
HTML-form POST to add later commands. Those transports cannot be interchanged.
The values below are therefore defined once and rendered for each transport.

This adapter does not claim that undocumented firmware fields are equivalent in
all versions. It preserves the previously used wire format; the result still
needs a visual and end-to-end test on COMEXIO 11.1.5.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from typing import Any, Mapping

from .discovery import Channel


@dataclass(frozen=True)
class WebIOCommand:
    name: str
    type_id: int
    minimum: int
    maximum: int
    parameter: str
    header_modifier: str
    data: str
    protocol: int = 0
    post_get: int = 1
    authentication: int = 0
    input_index: int = 1
    changed: int = 1
    send_on_one: int = 0
    default_active: int = 1
    default_value: str = ""
    port: str = ""
    req_freq: str = ""
    reply_interpreter: str = ""

    def __post_init__(self) -> None:
        if not self.name.startswith("CL ") or not self.name.strip():
            raise ValueError("COMEXIO-Local-Befehl benötigt einen lesbaren CL-Namen")
        if (self.type_id not in (1, 2) or self.minimum != 0
                or (self.type_id == 1 and self.maximum != 1)
                or (self.type_id == 2 and not 1 <= self.maximum <= 65535)):
            raise ValueError("Ungültige digitale/analoge COMEXIO-Web-IO-Befehlswerte")
        if not self.parameter.startswith("/api/webhook/") or not self.data.startswith("function data(a)"):
            raise ValueError("Web-IO-Befehl ohne gültigen Webhook/Lua-Inhalt")
        if (self.protocol, self.post_get, self.authentication, self.input_index,
                self.changed, self.send_on_one, self.default_active) != (0, 1, 0, 1, 1, 0, 1):
            raise ValueError("Unerwartete COMEXIO-Web-IO-Befehlsoptionen")
        if self.header_modifier != "Content-Type: application/json":
            raise ValueError("Unerwartete COMEXIO-Web-IO-Header")

    @classmethod
    def for_signal(cls, signal: Channel, webhook_path: str, name: str) -> WebIOCommand:
        if signal.kind == "cover":
            if signal.marker_id is None:
                raise ValueError("Rollladen-Istmerker fehlt")
            lua = (f'function data(a)\r\n  return json_stringify('
                   f'{{type="marker",id="{signal.marker_id}",value=a}})\r\nend')
        else:
            ext = json.dumps(signal.extension, ensure_ascii=True)
            identifier = json.dumps(signal.identifier, ensure_ascii=True)
            lua = (f'function data(a)\r\n  return json_stringify('
                   f'{{type="io",ext={ext},io={identifier},value=a}})\r\nend')
        return cls(name=name, type_id=2 if signal.analog else 1,
                   minimum=0, maximum=signal.push_maximum,
                   parameter=webhook_path,
                   header_modifier="Content-Type: application/json", data=lua)

    @classmethod
    def from_import(cls, data: Mapping[str, Any]) -> WebIOCommand:
        """Parse only command definitions from our own trusted builder.

        Refuse inconsistent input before POST rather than substituting defaults
        that could silently create an incompatible firmware command.
        """
        try:
            def number(key: str) -> int:
                value = data[key]
                if isinstance(value, bool):
                    raise ValueError(key)
                return int(value)

            obj = cls(name=str(data["Name"]), type_id=number("TypeId"),
                      minimum=number("Min"), maximum=number("Max"),
                      parameter=str(data["Parameter"]),
                      header_modifier=str(data["HeaderModifier"]),
                      data=str(data["Data"]), protocol=number("Protocol"),
                      post_get=number("PostGet"),
                      authentication=number("Authentication"),
                      input_index=number("Input"), changed=number("Changed"),
                      send_on_one=number("SendOnOne"),
                      default_active=number("DefaultActive"),
                      default_value=str(data["DefaultValue"]),
                      port=str(data["Port"]), req_freq=str(data["ReqFreq"]),
                      reply_interpreter=str(data["ReplyInterpreter"]))
            if data["io"] != [] or number("BaseId") != 0 or number("WebDeviceId") != 0:
                raise ValueError("Unerwartete Web-IO-Basiszuordnung")
            return obj
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError("Unvollständige oder inkonsistente COMEXIO-Web-IO-Befehlsdefinition") from err

    def as_import(self) -> dict[str, Any]:
        """Exact JSON schema accepted by the existing base-type import."""
        return {
            "Name": self.name, "TypeId": self.type_id,
            "Min": self.minimum, "Max": self.maximum,
            "Parameter": self.parameter, "HeaderModifier": self.header_modifier,
            "Data": self.data, "Protocol": self.protocol,
            "PostGet": self.post_get, "WebDeviceId": 0,
            "Authentication": self.authentication, "Input": self.input_index,
            "ReqFreq": self.req_freq, "ReplyInterpreter": self.reply_interpreter,
            "Port": self.port, "SendOnOne": self.send_on_one,
            "Changed": self.changed, "BaseId": 0,
            "DefaultValue": self.default_value,
            "DefaultActive": self.default_active, "io": [],
        }

    def as_append_form(self, device_id: str, base_id: str) -> dict[str, Any]:
        """Render the same logical command as the COMEXIO save_command form.

        The firmware-required `function_cmd_io_0` field is derived from the
        same command definition as the JSON import, keeping both paths in sync.
        """
        if not str(device_id).isdigit() or int(device_id) < 1:
            raise ValueError("Ungültige Web-IO-Geräte-ID")
        if not str(base_id).isdigit() or int(base_id) < 1:
            raise ValueError("Ungültige Web-IO-Basistyp-ID")
        empty_ref = base64.b64encode(b'{"src":"command","id":null}').decode("ascii")
        return {
            "dlg_web_device_id": str(device_id),
            "protocol": self.protocol,
            "parameter": self.parameter,
            "header_modifier": self.header_modifier,
            "data": self.data,
            "port": self.port,
            "post_get": self.post_get,
            "authentication": self.authentication,
            "req_freq": self.req_freq,
            "reply_interpreter": self.reply_interpreter,
            "id_cmd_io_0": empty_ref,
            "name_cmd_io_0": self.name,
            "function_cmd_io_0": f"{self.changed}_{self.input_index}_{self.send_on_one}",
            "input_cmd_io_0": self.input_index,
            "type_cmd_io_0": self.type_id,
            "send_on_one_cmd_io_0": self.send_on_one,
            "min_cmd_io_0": self.minimum,
            "max_cmd_io_0": self.maximum,
            "default_value_cmd_io_0": self.default_value,
            "id_cmd_io_sample": "",
            "name_cmd_io_sample": "",
            "function_cmd_io_sample": "0_1_0",
            "input_cmd_io_sample": 1,
            "type_cmd_io_sample": 2,
            "send_on_one_cmd_io_sample": 0,
            "min_cmd_io_sample": 0,
            "max_cmd_io_sample": 1,
            "default_value_cmd_io_sample": "",
            "DefaultActive": self.default_active,
            "deviceBaseId": str(base_id),
        }

    def readback_mismatch(self, stored: Mapping[str, Any]) -> list[str]:
        """Compare firmware-exposed scalar settings without guessing absent fields.

        Some firmware snapshots omit Data/Parameter altogether. Their absence
        cannot establish success and must not be treated as a mismatch here;
        separate push_audit / input_push checks cover webhook and Lua metadata.
        """
        mismatches: list[str] = []
        expected = self.as_import()
        for field in ("Name", "TypeId", "Min", "Max", "Protocol", "PostGet",
                      "Authentication", "Input", "SendOnOne", "Changed", "DefaultActive"):
            if field not in stored or stored[field] in (None, ""):
                continue
            value = stored[field]
            expected_value = expected[field]
            if field == "Name":
                same = str(value) == str(expected_value)
            else:
                try:
                    same = int(value) == int(expected_value)
                except (TypeError, ValueError):
                    same = False
            if not same:
                mismatches.append(field)
        return mismatches
