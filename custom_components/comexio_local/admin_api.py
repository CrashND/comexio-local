"""Minimal COMEXIO v11 admin interface for read-only discovery and *explicit* push setup.

No schedule, hidden resync or modifications to the user's existing logic.
Verified, explicitly confirmed cleanup may delete only COMEXIO Local's owned
push plans and exclusive Web-IO device. All destructive GETs are serialized.
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
from urllib.parse import urlsplit, parse_qs
import time
from typing import Any

from aiohttp import ClientSession, FormData
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from .discovery import Channel
from .webio_command import WebIOCommand

_LOGGER = logging.getLogger(__name__)
_DECL = re.compile(r"\bvar\s+\$([A-Za-z][A-Za-z0-9_]*)\s*=\s*", re.M)
_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)
_TAILING_COMMA = re.compile(r",\s*([}\]])")

class AdminError(Exception):
    """Could not inspect/modify the COMEXIO admin interface."""


def web_device_base_id(device: dict | None) -> str:
    """Read the *live device* base type from COMEXIO 11.1.5.

    ``WebDevices[id].WebDeviceBaseId`` identifies the template associated
    with this device. This is different from a command's ``BaseId`` and from
    the ``base_id`` returned by the template upload endpoint. Never guess a
    base type from the display name or silently accept an unrelated field.
    """
    raw = device.get('WebDeviceBaseId') if isinstance(device, dict) else None
    if (isinstance(raw, bool) or not isinstance(raw, (int, str))
            or re.fullmatch(r'[0-9]+', str(raw)) is None or int(raw) <= 0):
        raise AdminError('Web-IO-Gerät ohne eindeutig auslesbare WebDeviceBaseId; '
                         'keine Änderung')
    return str(int(raw))


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

    async def read_plans(self, config: dict[str, Any], limit: int | None = 50,
                         *, strict: bool = False) -> dict[str, dict]:
        """Read COMEXIO logic plans, optionally requiring a *complete* snapshot.

        Default behavior is retained for ordinary discovery and push workflows.
        Destructive HA entity-sync previews use strict=True and no plan limit:
        a missing or unreadable plan must never be interpreted as a removed IO.
        """
        fubs = config.get('Fubs')
        if not isinstance(fubs, dict):
            if strict:
                raise AdminError('COMEXIO-Planliste nicht vollständig auslesbar; keine Bereinigung')
            fubs = {}
        ids = list(fubs)
        if strict and limit is not None and len(ids) > limit:
            raise AdminError('COMEXIO-Planliste abgeschnitten; keine Bereinigung')
        if limit is not None:
            ids = ids[:limit]
        result = {}
        for plan_id in ids:
            try:
                payload = await self.request_json(
                    'GET', '/admin/function_function_module/loadelements/',
                    params={'fubid': plan_id})
                if not isinstance(payload, dict) or not isinstance(
                        payload.get('elements'), (dict, list)):
                    raise AdminError('COMEXIO-Logikplan unvollständig: ' + str(plan_id))
                result[str(plan_id)] = payload
            except AdminError:
                if strict:
                    raise AdminError('COMEXIO-Logikplan nicht lesbar: '
                                     + str(plan_id) + '; keine Bereinigung') from None
                _LOGGER.debug('Could not read COMEXIO plan %s; using IO names', plan_id)
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

        A Web-IO base type is a COMEXIO TEMPLATE, not the live device. It can
        outlive a deleted device and retain its command definitions. Therefore
        a freshly created device must NEVER reuse a pre-existing base type.
        A random, new base identifier is used for EVERY new device; the device
        itself keeps the single canonical, human-readable class name.
        """
        if not commands or not isinstance(name, str) or not name.startswith('CL '):
            raise AdminError('Ungültige Web-IO-Klasse oder leere Befehlsliste')
        if (len({cmd.get('Name') for cmd in commands if isinstance(cmd, dict)}) != len(commands)
                or any(not isinstance(cmd, dict) or not isinstance(cmd.get('Name'), str)
                       or not cmd.get('Name') for cmd in commands)):
            raise AdminError('Mehrdeutige oder unbenannte Web-IO-Importbefehle; keine Änderung')
        # Refuse existing live devices with the same class name before importing
        # even a disposable template. No automatic replacement or merge.
        current = await self.read_config()
        devices = current.get('WebDevices')
        if not isinstance(devices, dict):
            raise AdminError('COMEXIO-Web-IO-Geräteliste nicht lesbar; keine Änderung')
        if any(isinstance(dev, dict) and dev.get('Name') == name
               for dev in devices.values()):
            raise AdminError('Web-IO-Gerät mit diesem Namen bereits vorhanden; keine Neuerstellung')
        # The base list is read before the first write. Unexpected collisions
        # abort instead of reusing a template with unknown saved commands.
        template_name = 'CL Vorlage ' + secrets.token_hex(5).upper()
        if await self._base_id_by_name(template_name) is not None:
            raise AdminError('Neue Web-IO-Vorlage bereits vorhanden; keine Wiederverwendung')
        payload = {"data":"web_io", "format":1,
                   "base":{"Identifier":template_name,"UseCookies":0,"Login":2,"BaseId":0},
                   "commands":commands}
        form = FormData()
        form.add_field('file', io.BytesIO(json.dumps(payload).encode()),
                       filename='local_push.json', content_type='application/json')
        form.add_field('set_name', template_name)
        reply = await self.request_json('POST', '/admin/web_io/upload_device_settings', data=form)
        response_hint = self._upload_response_hint(reply)
        if self._upload_rejected(reply):
            raise AdminError('COMEXIO Web-IO-Import meldet einen Fehler (' + response_hint + ')')
        base_id = self._upload_base_id(reply)
        if base_id is None:
            try:
                base_id = await self._base_id_by_name(template_name)
            except AdminError as err:
                raise AdminError('Web-IO-Import lieferte keine BaseId; Basisliste nicht lesbar ('
                                 + response_hint + ')') from err
        if base_id is None:
            raise AdminError('Web-IO-Import lieferte keine BaseId und die neue Vorlage ist '
                             'nicht nachweisbar (' + response_hint + ')')
        # A numeric upload reply could refer to a different template. Verify
        # the exact newly generated name AND ID before creating the live device.
        await asyncio.sleep(0.5)
        listed_id = await self._base_id_by_name(template_name)
        if listed_id != str(base_id):
            raise AdminError('Importierte Web-IO-Vorlage nicht eindeutig als neue BaseId '
                             'bestätigt; kein Gerät angelegt')

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
        # Do not accept a successful HTTP response or a mere subset match.
        # The new device MUST contain exactly the imported commands and no
        # inherited, unexpected, unnamed or duplicated entries.
        from .managed_resources import unique_webio_commands
        stored_base = web_device_base_id(matches[0][1])
        if stored_base != str(int(base_id)):
            raise AdminError('Neue Web-IO-Klasse hat einen unerwarteten Basistyp; keine Verknüpfung')
        existing = ((config.get('FubModules') or {}).get('10') or {}).get(device_id)
        if not isinstance(existing, dict):
            raise AdminError('Neue Web-IO-Befehle nicht lesbar; keine Verknüpfung')
        actual = unique_webio_commands(config, device_id)
        expected_names = {str(command['Name']) for command in commands}
        if len(actual) != len(existing) or set(actual) != expected_names:
            raise AdminError('Neues Web-IO-Gerät enthält unerwartete Befehle '
                             'oder der Import ist unvollständig; keine Verknüpfung')
        for command in commands:
            name = str(command['Name'])
            cid, stored = actual[name]
            if cid <= 0 or (stored.get('Id') is not None and str(stored['Id']) != str(cid)):
                raise AdminError('Neue Web-IO-Befehls-ID widersprüchlich; keine Verknüpfung')
            if (stored.get('WebDeviceId') not in (None, '', 0, '0')
                    and str(stored['WebDeviceId']) != str(device_id)):
                raise AdminError('Neuer Web-IO-Befehl hat falsche Geräte-ID; keine Verknüpfung')
            if stored.get('TypeId') is None or str(stored['TypeId']) != str(command['TypeId']):
                raise AdminError('Neuer Web-IO-Befehl hat falschen Typ; keine Verknüpfung')
            try:
                mismatch = WebIOCommand.from_import(command).readback_mismatch(stored)
            except ValueError as err:
                raise AdminError('Ungültige importierte Web-IO-Befehlsdefinition') from err
            if mismatch:
                raise AdminError('Neu angelegter Web-IO-Befehl abweichend gespeichert: '
                                 + ', '.join(mismatch) + '; keine Verknüpfung')

    async def ensure_webio_commands_active(self, config: dict, device_id: str,
                                           names: list[str], *, force: bool = False,
                                           force_names: set[str] | None = None) -> dict:
        """Activate selected commands of our managed Web-IO class before linking.

        The real COMEXIO 11.1.5 editor POST uses three DIFFERENT IDs:
        webIo=FubModules/10 device entry, device=WebDevice, and
        command=the entry's WebCommandId. DefaultActive=1 is not the
        current Active flag. An incomplete or ambiguous snapshot must stop
        provisioning instead of activating an unrelated command.

        The caller invokes this only inside an explicitly approved setup,
        rebuild, repair, or input-push write path. There is no global toggle.
        """
        from .managed_resources import unique_webio_commands
        from .push_labels import PREFERRED_PUSH_CLASS

        devices = config.get('WebDevices') or {}
        device = devices.get(str(device_id)) if isinstance(devices, dict) else None
        if not isinstance(device, dict) or device.get('Name') not in (
                PREFERRED_PUSH_CLASS, 'CL Eingänge Home Assistant'):
            raise AdminError('Web-IO-Aktivierung nur für die eigene CL-Push-Klasse erlaubt')
        if not names or len(set(names)) != len(names) or any(
                not isinstance(name, str) or not name.startswith('CL ') for name in names):
            raise AdminError('Web-IO-Aktivierung: ungültige oder doppelte Befehlsnamen')
        if not str(device_id).isdigit() or int(device_id) <= 0:
            raise AdminError('Web-IO-Aktivierung: ungültige Geräte-ID')

        force_names = force_names or set()
        if not isinstance(force_names, set) or not force_names.issubset(set(names)):
            raise AdminError('Ungültige neu angelegte Web-IO-Befehle für Aktivierung')
        existing = unique_webio_commands(config, str(device_id))
        pending = []
        # Validate all IDs BEFORE the first write, including commands later in
        # the batch. A partial failure never triggers an automatic POST retry.
        for name in names:
            match = existing.get(name)
            if match is None:
                raise AdminError('Web-IO-Aktivierung: eigener Befehl nicht sichtbar: ' + name)
            io_id, record = match
            if io_id <= 0 or not isinstance(record, dict) or record.get('Name') != name:
                raise AdminError('Web-IO-Aktivierung: ungültige IO-Referenz: ' + name)
            saved_id = record.get('Id')
            if saved_id is not None and str(saved_id) != str(io_id):
                raise AdminError('Web-IO-Aktivierung: widersprüchliche IO-ID: ' + name)
            stored_device_id = record.get('WebDeviceId')
            if (stored_device_id not in (None, '', 0, '0')
                    and str(stored_device_id) != str(device_id)):
                raise AdminError('Web-IO-Aktivierung: widersprüchliche Geräte-ID: ' + name)
            # A newly created command may advertise Active=1 even while the
            # firmware's separate activation switch remains off. For an
            # approved fresh rebuild, always send the editor's explicit POST.
            if (not force and name not in force_names
                    and str(record.get('Active', '')).strip().lower() in ('1', 'true')):
                continue
            raw_command = record.get('WebCommandId')
            if (isinstance(raw_command, bool) or not str(raw_command).isdigit()
                    or int(raw_command) <= 0):
                raise AdminError('Web-IO-Aktivierung: WebCommandId nicht eindeutig auslesbar: '
                                 + name + '; keine Änderung')
            pending.append((name, io_id, int(raw_command)))

        for name, io_id, web_command_id in pending:
            reply = await self.request_json(
                'POST', '/admin/web_io/set_web_io_active',
                data={'webIo': str(io_id), 'device': str(device_id),
                      'command': str(web_command_id), 'active': '1'})
            updated = (reply.get('io') or {}).get(str(io_id)) if isinstance(reply.get('io'), dict) else None
            if (reply.get('ok') is not True or reply.get('active') is not True
                    or not isinstance(updated, dict)
                    or str(updated.get('Id')) != str(io_id)
                    or str(updated.get('WebDeviceId')) != str(device_id)
                    or str(updated.get('WebCommandId')) != str(web_command_id)
                    or str(updated.get('Active')).strip().lower() not in ('1', 'true')):
                raise AdminError('COMEXIO hat Web-IO-Aktivierung nicht eindeutig bestätigt: '
                                 + name + '; keine automatische Wiederholung')

        if not pending:
            return config
        fresh = await self.read_config()
        refreshed = unique_webio_commands(fresh, str(device_id))
        for name in names:
            before = existing[name][0]
            actual = refreshed.get(name)
            if (actual is None or actual[0] != before
                    or str(actual[1].get('Active', '')).strip().lower() not in ('1', 'true')):
                raise AdminError('COMEXIO-Web-IO nach Aktivierung nicht aktiv zurücklesbar: '
                                 + name + '; keine Verknüpfung')
        return fresh

    async def delete_owned_push_plan(self, fid: int, *, name: str, entry_id: str) -> None:
        """COMEXIO 11.1.5 editor's verified destructive GET, redirect checked.

        A 302 containing delete=ok is corroborated by a fresh configuration
        read; the redirect alone is not treated as proof of deletion.
        """
        from .managed_resources import is_owned_plan
        if type(fid) is not int or fid <= 0:
            raise AdminError('Ungültige ID beim Löschen eines Push-Plans')
        before = await self.read_config()
        meta = (before.get('Fubs') or {}).get(str(fid))
        if (not is_owned_plan(meta, entry_id, 'push')
                or not isinstance(name, str) or meta.get('Name') != name):
            raise AdminError('Push-Plan vor Löschung nicht eindeutig im Eigentum')
        async with self._lock:
            await self._wait_write_slot()
            try:
                async with self.session.get(
                        self.base + '/admin/function_function_module/delete/',
                        params={'id': str(fid)},
                        headers={'Referer': self.base + '/admin/function_function_module/home/'},
                        allow_redirects=False) as response:
                    location = response.headers.get('Location', '')
                    if response.status != 302:
                        raise AdminError('Push-Plan-Löschung nicht bestätigt (HTTP '
                                         + str(response.status) + ')')
            except AdminError:
                raise
            except Exception as exc:
                raise AdminError('Push-Plan-Löschaufruf fehlgeschlagen') from exc
        redirect = urlsplit(location)
        query = parse_qs(redirect.query)
        if (redirect.netloc or redirect.path != '/admin/function_function_module/home/'
                or query.get('delete') != ['ok'] or query.get('name') != [name]):
            raise AdminError('Unerwartete COMEXIO-Löschantwort; Status prüfen')
        after = await self.read_config()
        if str(fid) in (after.get('Fubs') or {}):
            raise AdminError('Push-Plan nach Löschaufruf weiterhin vorhanden')

    async def delete_owned_push_device(self, device_id: str, *, expected_name: str) -> None:
        """Delete complete exclusive Web-IO device; HTTP 200 alone is NOT success."""
        if not str(device_id).isdigit() or int(device_id) <= 0:
            raise AdminError('Ungültige Web-IO-Geräte-ID bei Löschung')
        before = await self.read_config()
        device = (before.get('WebDevices') or {}).get(str(device_id))
        if (not isinstance(device, dict) or device.get('Name') != expected_name):
            raise AdminError('Web-IO-Gerät vor Löschung nicht eindeutig zugeordnet')
        async with self._lock:
            await self._wait_write_slot()
            try:
                async with self.session.get(
                        self.base + '/admin/web_io/delete_device/',
                        params={'id': str(device_id)},
                        headers={'Referer': self.base + '/admin/web_io/home'},
                        allow_redirects=False) as response:
                    # Both rejected and successful deletes return HTML + 200.
                    if response.status != 200:
                        raise AdminError('Web-IO-Löschaufruf: HTTP ' + str(response.status))
                    await response.read()
            except AdminError:
                raise
            except Exception as exc:
                raise AdminError('Web-IO-Löschaufruf fehlgeschlagen') from exc
        after = await self.read_config()
        if (str(device_id) in (after.get('WebDevices') or {})
                or str(device_id) in ((after.get('FubModules') or {}).get('10') or {})):
            raise AdminError('Web-IO-Gerät oder Befehle nach Löschaufruf weiterhin vorhanden')

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
        matches = [(fid, meta) for fid, meta in (config.get('Fubs') or {}).items()
                   if isinstance(meta, dict) and meta.get('Name') == name]
        if len(matches) != 1:
            raise AdminError('Neu angelegter COMEXIO-Logikplan nicht eindeutig sichtbar: '
                             + name + f' ({len(matches)} Treffer); keine weiteren Schreibzugriffe')
        fid, metadata = matches[0]
        if str(metadata.get('Comment') or '') != comment:
            raise AdminError('Neu angelegter COMEXIO-Logikplan hat fremde Eigentumskennung: '
                             + name + '; keine weiteren Schreibzugriffe')
        try:
            return int(fid)
        except (TypeError, ValueError):
            raise AdminError('Ungültige neue COMEXIO-Logikplan-ID: ' + name) from None

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
                # Empty arrays are legitimate on a brand-new plan.  Nonempty
                # arrays must never be discarded: doing so could make an
                # existing graph look empty and provoke duplicate writes.
                if isinstance(response['elements'], list):
                    if response['elements']:
                        raise AdminError('COMEXIO Logikplan enthält unbekanntes Elemente-Listenformat; '
                                         'keine Änderung')
                    response['elements'] = {}
                if isinstance(response.get('connections'), list):
                    if response['connections']:
                        raise AdminError('COMEXIO Logikplan enthält unbekanntes Verbindungs-Listenformat; '
                                         'keine Änderung')
                    response['connections'] = {}
                if not isinstance(response.get('connections'), dict):
                    raise AdminError('COMEXIO Logikplan enthält keine eindeutig lesbaren Verbindungen; '
                                     'keine Änderung')
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

    async def add_element(self, fid: int, ref: int, typ: int, x: int, y: int,
                          *, name: str = "") -> int:
        """Create COMEXIO logic elements using the observed editor sequence.

        Web-IO elements always have an empty element name. The reference
        determines their visible label. Connections are written separately
        via saveconnection/, never embedded in add_element/.
        """
        if typ == 10 and name != '':
            raise AdminError('Ungültiger Web-IO-Bausteinname')
        data = {"fubid":str(fid),"name":name,"ref_id":str(ref),"type":str(typ),"id":"undefined",
                "x":str(x),"y":str(y),"timestamp":_iso_time()}
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


def make_push_command(signal: Channel, webhook_path: str, *, name: str) -> dict[str, Any]:
    """One shared command definition for JSON import and subsequent form POSTs."""
    return WebIOCommand.for_signal(signal, webhook_path, name).as_import()
