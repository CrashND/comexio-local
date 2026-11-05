"""Minimal COMEXIO v11 admin interface for read-only discovery and *explicit* push setup.

No schedule, hidden resync, deletes or modifications to the user's existing logic.
Requests only target the two documented COMEXIO admin pages for discovery and
COMEXIO Local's own namespaced resources when setup is expressly requested.
"""
from __future__ import annotations
import asyncio
import base64
import io
import html
import json
import logging
import re
import secrets
import time
from typing import Any

from aiohttp import ClientSession, FormData
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from .discovery import Channel

_LOGGER = logging.getLogger(__name__)
_DECL = re.compile(r"\bvar\s+\$([A-Za-z][A-Za-z0-9_]*)\s*=\s*", re.M)
_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)
_TAILING_COMMA = re.compile(r",\s*([}\]])")

class AdminError(Exception):
    """Could not inspect/modify the COMEXIO admin interface."""


def _json_after(text: str, pos: int) -> dict | None:
    while pos < len(text) and text[pos].isspace(): pos += 1
    if pos >= len(text) or text[pos] != "{":
        return None
    level, inside, slash = 0, None, False
    for i in range(pos, len(text)):
        ch = text[i]
        if inside:
            if slash: slash = False
            elif ch == "\\": slash = True
            elif ch == inside: inside = None
        elif ch in ('"', "'"): inside = ch
        elif ch == "{": level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                blob = _TAILING_COMMA.sub(r"\1", text[pos:i+1])
                try:
                    result = json.loads(blob)
                    return result if isinstance(result, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def extract_config(html: str) -> dict[str, Any]:
    parsed = {}
    scripts = _SCRIPT.findall(html)
    if not scripts:
        scripts = [html]  # support exported config fragments
    for script in scripts:
        for match in _DECL.finditer(script):
            value = _json_after(script, match.end())
            if value is not None:
                parsed[match.group(1)] = value
    return parsed


class ComexioAdmin:
    def __init__(self, session: ClientSession, host: str, user: str, password: str) -> None:
        self.session = session
        self.host = host
        self.user = user
        self.password = password
        self.base = f"http://{host}"
        self._authenticated = False
        self._lock = asyncio.Lock()
        self._last_write = 0.0
        self.write_gap = 1.25  # conservative COMEXIO configuration-write pacing
        self._headers = {"X-Requested-With":"XMLHttpRequest", "Referer":f"{self.base}/admin/function_function_module/home"}

    async def login(self) -> None:
        """RSA admin login used by COMEXIO firmware 11.x."""
        url = f"{self.base}/board/home/login/"
        try:
            self.session.cookie_jar.update_cookies({"comexio-client-time": str(int(time.time()))})
            async with self.session.post(url, data={"login_keys":"true"}) as response:
                response.raise_for_status()
                keys = await response.json(content_type=None)
            salt = base64.b64decode(keys["salt"]).decode("latin1")
            pub = rsa.RSAPublicNumbers(int(keys["exponent"],16), int(keys["modulus"],16)).public_key()
            nonce = secrets.token_hex(10).upper()
            def encrypt(s: str) -> str:
                return pub.encrypt(s.encode("latin1"), padding.PKCS1v15()).hex()
            # Comexio's encrypted two-part challenge (password and empty password).
            response_data = {
                "target":"/board/home/login", "username":self.user,
                "password": encrypt(salt + nonce + self.password) + " " + encrypt(salt + nonce),
                "loginsubmit":"Anmelden", "encryption":"rsa",
            }
            async with self.session.post(url, data=response_data, headers={"Referer":url}) as response:
                response.raise_for_status()
            self._authenticated = True
        except Exception as exc:
            raise AdminError("COMEXIO admin RSA login failed") from exc

    async def _get_html(self, route: str, **kwargs) -> str:
        async with self.session.get(self.base + route, headers=self._headers, **kwargs) as response:
            response.raise_for_status()
            return await response.text(errors="replace")

    async def read_config(self) -> dict[str, Any]:
        if not self._authenticated:
            await self.login()
        try:
            html = await self._get_html("/admin/function_function_module/home")
            config = extract_config(html)
            if not isinstance(config.get("FubModules"), dict):
                # A login HTML page or an unsupported COMEXIO firmware must not be mistaken
                # for an empty installation (which would purge HA discovery).
                raise AdminError("COMEXIO did not return $FubModules after authentication")
            return config
        except AdminError:
            raise
        except Exception as exc:
            raise AdminError("COMEXIO configuration discovery failed") from exc

    async def read_plans(self, config: dict[str, Any], limit: int = 50) -> dict[str, dict]:
        """One-off, sequential read of plans for room affiliation; no periodic scanning."""
        result = {}
        for plan_id in list((config.get("Fubs") or {}).keys())[:limit]:
            try:
                payload = await self.request_json("GET", "/admin/function_function_module/loadelements/", params={"fubid":plan_id})
                if isinstance(payload, dict):
                    result[str(plan_id)] = payload
            except AdminError:
                _LOGGER.debug("Could not read COMEXIO plan %s; using IO names", plan_id)
        return result

    async def _wait_write_slot(self) -> None:
        """Must be called with _lock held; serializes *all* config writes."""
        pause = self.write_gap - (time.monotonic() - self._last_write)
        if pause > 0:
            await asyncio.sleep(pause)
        self._last_write = time.monotonic()

    async def request_json(self, method: str, route: str, *, data: Any = None, params=None, follow: bool = True) -> dict:
        if method.upper() != "GET":
            async with self._lock:
                await self._wait_write_slot()
                return await self._request_raw(method, route, data=data, params=params, follow=follow)
        return await self._request_raw(method, route, data=data, params=params, follow=follow)

    async def _request_raw(self, method: str, route: str, *, data=None, params=None, follow: bool = True) -> dict:
        try:
            async with self.session.request(method, self.base + route, data=data, params=params, headers=self._headers, allow_redirects=follow) as response:
                status = response.status
                content = await response.text(errors="replace")
                if not follow and status in (301, 302, 303):
                    return {"redirect": response.headers.get("Location", "")}
                if status != 200:
                    raise AdminError(f"COMEXIO {method} {route}: HTTP {status}")
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise AdminError(f"COMEXIO {route} did not return an object")
                return parsed
        except AdminError:
            raise
        except Exception as exc:
            raise AdminError(f"COMEXIO request failed: {method} {route}") from exc

    @staticmethod
    def _upload_base_id(reply: dict) -> str | None:
        """Accept known base-ID spellings, but never confuse a response flag with an ID."""
        candidates = [reply]
        for key in ("data", "base", "result", "device"):
            if isinstance(reply.get(key), dict):
                candidates.append(reply[key])
        for data in candidates:
            for key in ("base_id", "baseId", "BaseId", "baseID", "web_device_base"):
                value = data.get(key)
                if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).isdigit() and int(value) > 0:
                    return str(value)
        return None

    @staticmethod
    def _upload_rejected(reply: dict) -> bool:
        """An explicit negative response takes precedence over apparent IDs."""
        for key in ("ok", "success"):
            if key in reply and reply[key] in (False, 0, "false", "error", "failed"):
                return True
        for key in ("status", "result"):
            if isinstance(reply.get(key), str) and reply[key].lower() in ("error", "failed", "fail", "invalid"):
                return True
        return bool(reply.get("error"))

    @staticmethod
    def _upload_response_hint(reply: dict) -> str:
        """Non-sensitive diagnostic: no arbitrary response values / webhook secrets."""
        keys = ', '.join(sorted(str(k) for k in reply)[:12]) or '(leer)'
        return f"Antwortfelder: {keys}"

    async def _base_id_by_name(self, name: str) -> str | None:
        """Find a Web-IO base type by its exact visible name in COMEXIO's own list."""
        page = await self._get_html('/admin/web_io/add')
        found = []
        for item in re.finditer(r'<option\b([^>]*)>(.*?)</option\s*>', page, re.S | re.I):
            attributes, raw_label = item.groups()
            value = re.search(r"\bvalue\s*=\s*['\"](\d+)['\"]", attributes, re.I)
            if value is None:
                continue
            label = html.unescape(re.sub(r'<[^>]*>', '', raw_label)).strip()
            if label == name:
                found.append(value.group(1))
        unique_ids = set(found)
        if len(unique_ids) > 1:
            raise AdminError(f"COMEXIO enthält mehrere Web-IO-Basistypen namens {name}; keine Änderung")
        return next(iter(unique_ids)) if unique_ids else None

    async def create_push_class(self, name: str, commands: list[dict], target_url: str) -> None:
        """Create a namespaced Web-IO class; verify rather than trust undocumented replies.

        Uploading a base type and creating a device instance are different steps.
        A partial failure may leave the base type behind. Reuse it only if COMEXIO
        itself lists its *exact* expected name; never blindly import it again.
        """
        response_hint = ''
        # The same endpoint is required later when adding commands. If it cannot
        # be inspected, do not write to an installation with uncertain ownership.
        base_id = await self._base_id_by_name(name)
        if base_id is None:
            payload = {"data":"web_io", "format":1,
                "base":{"Identifier":name,"UseCookies":0,"Login":2,"BaseId":0},
                "commands":commands}
            form = FormData()
            form.add_field("file", io.BytesIO(json.dumps(payload).encode()),
                           filename="local_push.json", content_type="application/json")
            form.add_field("set_name", name)
            reply = await self.request_json("POST", "/admin/web_io/upload_device_settings", data=form)
            response_hint = self._upload_response_hint(reply)
            if self._upload_rejected(reply):
                raise AdminError("COMEXIO Web-IO-Import meldet einen Fehler (" + response_hint + ")")
            base_id = self._upload_base_id(reply)
            if base_id is None:
                try:
                    base_id = await self._base_id_by_name(name)
                except AdminError as err:
                    raise AdminError("Web-IO-Import lieferte keine BaseId; COMEXIO-Basisliste nicht lesbar ("
                                     + response_hint + ")") from err
            if base_id is None:
                raise AdminError("Web-IO-Import lieferte keine BaseId und die Klasse ist in COMEXIO "
                                 "nicht nachweisbar (" + response_hint + ")")

        device_data = {"name":name,"ip":target_url,"web_device_base":str(base_id),
            "username":"","password":"","web_device_base_sample":"none",
            "identifier":"","form_login":"2"}
        async with self._lock:
            await self._wait_write_slot()
            async with self.session.post(self.base + "/admin/web_io/saveDeviceWindow",
                                         data=device_data,headers=self._headers) as response:
                if response.status != 200:
                    raise AdminError(f"COMEXIO Web-IO-Gerät anlegen: HTTP {response.status}")
        # A 200 response can be an HTML form or login page, not proof of success.
        await asyncio.sleep(0.7)
        config = await self.read_config()
        matches = [(str(did), dev) for did, dev in (config.get('WebDevices') or {}).items()
                   if isinstance(dev, dict) and dev.get('Name') == name]
        if len(matches) != 1:
            raise AdminError(f"Web-IO-Klasse nach Speichern nicht eindeutig sichtbar: {len(matches)} Treffer "
                             "(Upload " + (response_hint or 'vorhandener Basistyp') + ")")
        device_id = matches[0][0]
        existing = ((config.get('FubModules') or {}).get('10') or {}).get(device_id) or {}
        if not isinstance(existing, dict) or not all(
            any(isinstance(item, dict) and item.get('Name') == command.get('Name')
                for item in existing.values()) for command in commands
        ):
            raise AdminError("Web-IO-Klasse ist vorhanden, aber importierte Befehle sind nicht sichtbar. "
                             "Vor erneutem Versuch COMEXIO-Zustand prüfen; keine automatische Wiederholung.")

    async def create_plan(self, name: str, comment: str) -> int:
        data = {
            "fub_position":"-1","fub_type":"1","fub_page_count_x":"1","fub_page_count_y":"1",
            "fub_name":name,"fub_comment":comment,"fub_active":"0","fub_reset_on_close":"0",
            "fub_paper":"3","fub_orientation":"0","fub_resolution":"90","fub_create":"Erzeugen",
        }
        response = await self.request_json("POST", "/admin/function_function_module/save_fub",data=data,follow=False)
        if "added=1" not in response.get("redirect", ""):
            raise AdminError("COMEXIO did not confirm creation of the push plan")
        config = await self.read_config()
        for fid, plan in config.get("Fubs", {}).items():
            if plan.get("Name") == name:
                return int(fid)
        raise AdminError("New push plan not visible in COMEXIO config")

    async def read_plan(self, fid: int) -> dict:
        """Retry only transient READ errors; never retry configuration writes.

        COMEXIO firmware may intermittently answer HTTP 500 while generating
        the /loadelements/ response. Every retry is a GET and is bounded.
        """
        for attempt in range(3):
            try:
                response = await self.request_json(
                    "GET", "/admin/function_function_module/loadelements/",
                    params={"fubid": str(fid)})
                if not isinstance(response.get("elements"), (list, dict)):
                    raise AdminError("COMEXIO plan response has no elements")
                if isinstance(response["elements"], list):
                    response["elements"] = {}
                if isinstance(response.get("connections"), list):
                    response["connections"] = {}
                return response
            except AdminError as exc:
                message = str(exc)
                transient = any(f'HTTP {status}' in message for status in (500, 502, 503, 504))
                if not transient or attempt == 2:
                    raise
                _LOGGER.warning('COMEXIO Plan %s: transienter Lesefehler, Versuch %s/3',
                                fid, attempt + 1)
                await asyncio.sleep((2.0, 4.0)[attempt])
        raise AdminError('COMEXIO Plan konnte nicht eingelesen werden')

    async def add_element(self, fid: int, ref: int, typ: int, x: int, y: int, connection: dict | None = None) -> int:
        data = {"fubid":str(fid),"name":"","ref_id":str(ref),"type":str(typ),"id":"undefined",
                "x":str(x),"y":str(y),"timestamp":_iso_time()}
        if connection:
            data["connection"] = json.dumps(connection,separators=(",",":"))
        reply = await self.request_json("POST","/admin/function_function_module/add_element/",data=data)
        try:
            return int(reply["id"])
        except (KeyError,ValueError,TypeError) as exc:
            raise AdminError(f"COMEXIO rejected element type {typ} reference {ref}") from exc

    async def wire(self, fid: int, src: int, dest: int, analog: bool) -> None:
        conn = {"id":"new","fub_id":fid,
            "input":{"element":str(src),"pos":"0","inverted":False},
            "type":"analog" if analog else "binary",
            "output":{"0":{"element":str(dest),"pos":"0","inverted":False}}}
        reply=await self.request_json("POST","/admin/function_function_module/saveconnection/",data={"JSON":json.dumps(conn),"timestamp":_iso_time()})
        if reply.get("id") is None:
            raise AdminError("COMEXIO refused Web-IO connection")

    async def run_plan(self, fid: int) -> None:
        plan=await self.read_plan(fid)
        transformed={}
        for cid, val in plan["connections"].items():
            outputs=val.get("output") or []
            if isinstance(outputs,list): outputs={str(i):v for i,v in enumerate(outputs)}
            transformed[cid]={**val,"output":outputs}
        reply=await self.request_json("POST","/admin/function_function_module/run_fup/",
                data={"id":str(fid),"data":json.dumps({"elements":plan["elements"],"connections":transformed})})
        if reply.get("result") is not True:
            raise AdminError(f"COMEXIO did not activate push plan {fid}")


def _iso_time() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")


def command_name(prefix: str, signal: Channel) -> str:
    return f"{prefix} {('M'+str(signal.marker_id)) if signal.kind=='cover' else (signal.extension+' '+signal.identifier)}"


def make_push_command(prefix: str, signal: Channel, webhook_path: str, *, name: str | None = None) -> dict[str, Any]:
    if signal.kind == "cover":
        lua = f'function data(a)\r\n  return json_stringify({{type="marker",id="{signal.marker_id}",value=a}})\r\nend'
    else:
        ext=json.dumps(signal.extension,ensure_ascii=True)
        io_name=json.dumps(signal.identifier,ensure_ascii=True)
        lua=f'function data(a)\r\n  return json_stringify({{type="io",ext={ext},io={io_name},value=a}})\r\nend'
    return {
        "Name":name or command_name(prefix, signal), "TypeId":2 if signal.analog else 1,
        "Min":0,"Max":100 if signal.analog else 1,"Parameter":webhook_path,
        "HeaderModifier":"Content-Type: application/json","Data":lua,
        "Protocol":0,"PostGet":1,"WebDeviceId":0,"Authentication":0,
        "Input":1,"ReqFreq":"","ReplyInterpreter":"","Port":"",
        "SendOnOne":0,"Changed":1,"BaseId":0,"DefaultValue":"", "DefaultActive":1,"io":[],
    }
