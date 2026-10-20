#!/usr/bin/env python3
"""Pydroid 3 Telegram bot: Macweb'in en fazla beş özel iframe kanalını yönetir.

Gizli bilgiler yalnızca yanındaki pydroid_channel_sync_config.json dosyasından okunur.
Hiçbir token kaynak koda, GitHub commit'ine, URL'ye veya loga yazılmaz.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, urlopen

REPO = "inadinatv/macweb"
BRANCH = "main"
MANIFEST_PATH = "output/custom_channels.json"
MAX_CHANNELS = 5
MAX_NAME_LENGTH = 48
MAX_IFRAME_URL_LENGTH = 2048
CONFIG_PATH = Path(__file__).with_name("pydroid_channel_sync_config.json")
TELEGRAM_API = "https://api.telegram.org"
GITHUB_API = "https://api.github.com"
SENSITIVE_QUERY_KEYS = {
    "token", "access_token", "accesstoken", "refresh_token", "refreshtoken",
    "id_token", "idtoken", "auth", "auth_token", "authtoken", "authorization",
    "bearer", "password", "passwd", "secret", "api_key", "apikey", "key",
    "signature", "sig", "accesskey", "xamzsignature", "xgoogsignature",
}


class PublicIframeParser(HTMLParser):
    """Accept one iframe's src only; never preserve or execute submitted HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []
        self.blocked_markup = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "object", "embed", "base", "form"}:
            self.blocked_markup = True
        if tag == "iframe":
            attributes = {str(key).lower(): value for key, value in attrs}
            self.sources.append(str(attributes.get("src") or ""))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def clean_channel_name(value: str) -> str:
    name = "".join(ch for ch in str(value or "").strip() if not unicodedata.category(ch).startswith("C"))
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        raise ValueError("Kanal adı boş olamaz.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Kanal adı en fazla {MAX_NAME_LENGTH} karakter olabilir.")
    return name


def extract_public_iframe_url(value: str) -> str:
    """Return a public HTTPS iframe URL or raise ValueError without echoing input."""
    source = str(value or "").strip()
    if not source or len(source) > 6000:
        raise ValueError("HTTPS adresi veya tek bir iframe kodu girin.")

    if not source.lower().startswith("https://"):
        parser = PublicIframeParser()
        try:
            parser.feed(source)
            parser.close()
        except Exception as exc:
            raise ValueError("Iframe kodu okunamadı.") from exc
        if parser.blocked_markup or len(parser.sources) != 1:
            raise ValueError("Yalnızca tek iframe içeren bir kod kabul edilir; script/obje kodları alınmaz.")
        source = parser.sources[0].strip()

    if not source or len(source) > MAX_IFRAME_URL_LENGTH:
        raise ValueError("Iframe adresi boş veya çok uzun.")
    parts = urlsplit(source)
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Yalnızca herkese açık HTTPS iframe adresleri kabul edilir.")
    hostname = parts.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise ValueError("Yerel ağ adresleri yayımlanamaz.")
    import ipaddress
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValueError("Yerel veya özel IP adresleri yayımlanamaz.")
    for key, _ in parse_qsl(parts.query, keep_blank_values=True):
        normalized = re.sub(r"[^a-z0-9_]", "", key.lower())
        if normalized in SENSITIVE_QUERY_KEYS:
            raise ValueError("Gizli token/anahtar içerebilecek sorgu parametreleri yayımlanamaz.")
    return source


def normalize_manifest(value: Any) -> dict[str, Any]:
    """Keep only the five supported channel slots and safe public fields."""
    raw = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    for slot in range(1, MAX_CHANNELS + 1):
        key = f"channel{slot}"
        row = raw.get(key)
        if not isinstance(row, dict):
            continue
        try:
            name = clean_channel_name(str(row.get("name") or ""))
            iframe_url = extract_public_iframe_url(str(row.get("iframeUrl") or row.get("embedCode") or ""))
        except ValueError:
            continue
        result[key] = {"name": name, "iframeUrl": iframe_url}
    updated_at = raw.get("updatedAt")
    if isinstance(updated_at, str) and len(updated_at) <= 40:
        result["updatedAt"] = updated_at
    return result


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        raise RuntimeError(
            "Ayar dosyası bulunamadı. pydroid_channel_sync_config.example.json dosyasını "
            "pydroid_channel_sync_config.json adıyla kopyalayıp yalnızca cihazınızda doldurun."
        )
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Bot ayar dosyası okunamadı veya JSON biçimi hatalı.") from exc
    if not isinstance(config, dict):
        raise RuntimeError("Bot ayar dosyasının kök biçimi geçersiz.")
    bot_token = str(config.get("telegram_bot_token") or "").strip()
    github_token = str(config.get("github_token") or "").strip()
    admin_raw = str(config.get("admin_telegram_user_id") or "").strip()
    if not bot_token or "BURAYA_" in bot_token or not github_token or "BURAYA_" in github_token:
        raise RuntimeError("Ayar dosyasında Telegram ve GitHub tokenları doldurulmalı.")
    if not admin_raw.isdigit() or int(admin_raw) <= 0:
        raise RuntimeError("admin_telegram_user_id sayısal Telegram kullanıcı ID'si olmalı.")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    return {"telegram_bot_token": bot_token, "github_token": github_token, "admin_telegram_user_id": int(admin_raw)}


class GitHubManifest:
    """Read/modify/write only output/custom_channels.json on the fixed Macweb repo."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.path_url = f"{GITHUB_API}/repos/{REPO}/contents/{MANIFEST_PATH}"

    def _request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if payload is not None else None
        request = Request(url, data=body, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Macweb-Pydroid-Channel-Sync",
            "Content-Type": "application/json",
        })
        try:
            with urlopen(request, timeout=25) as response:
                data = response.read()
                return int(response.status), json.loads(data.decode("utf-8")) if data else {}
        except HTTPError as exc:
            if exc.code == 404:
                return 404, {}
            if exc.code in {409, 422}:
                return exc.code, {}
            raise RuntimeError(f"GitHub yanıt vermedi (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise RuntimeError("GitHub bağlantısı kurulamadı; interneti ve token yetkisini kontrol edin.") from None

    def read(self) -> dict[str, Any]:
        status, data = self._request("GET", self.path_url + "?ref=" + BRANCH)
        if status == 404:
            return {}
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError("GitHub kanal dosyası okunamadı.")
        try:
            content = base64.b64decode(data.get("content", ""), validate=False).decode("utf-8")
            return normalize_manifest(json.loads(content))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("GitHub kanal dosyasının JSON biçimi geçersiz.") from None

    def update(self, change: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        for attempt in range(3):
            status, file_info = self._request("GET", self.path_url + "?ref=" + BRANCH)
            if status == 404:
                sha = None
                current: dict[str, Any] = {}
            elif status == 200 and isinstance(file_info, dict):
                sha = file_info.get("sha")
                try:
                    current_text = base64.b64decode(file_info.get("content", ""), validate=False).decode("utf-8")
                    current = normalize_manifest(json.loads(current_text))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    raise RuntimeError("GitHub kanal dosyasının JSON biçimi geçersiz.") from None
            else:
                raise RuntimeError("GitHub kanal dosyası okunamadı.")

            next_doc = normalize_manifest(change(dict(current)))
            next_doc["updatedAt"] = utc_timestamp()
            encoded = base64.b64encode((json.dumps(next_doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).decode("ascii")
            payload: dict[str, Any] = {
                "message": "Update Macweb custom TV channels via Telegram bot",
                "content": encoded,
                "branch": BRANCH,
            }
            if sha:
                payload["sha"] = sha
            put_status, _ = self._request("PUT", self.path_url, payload)
            if put_status in {200, 201}:
                return next_doc
            if put_status not in {409, 422} or attempt == 2:
                raise RuntimeError("GitHub dosyası kaydedilemedi. Fine-grained token için macweb deposunda Contents: Read and write iznini kontrol edin.")
            time.sleep(1 + attempt)
        raise RuntimeError("GitHub eşzamanlama tamamlanamadı; tekrar deneyin.")

    def set_channel(self, slot: int, name: str, iframe_url: str) -> dict[str, Any]:
        if slot < 1 or slot > MAX_CHANNELS:
            raise ValueError("Kanal yuvası geçersiz.")
        clean_name = clean_channel_name(name)
        safe_url = extract_public_iframe_url(iframe_url)
        def change(doc: dict[str, Any]) -> dict[str, Any]:
            doc[f"channel{slot}"] = {"name": clean_name, "iframeUrl": safe_url}
            return doc
        return self.update(change)

    def delete_channel(self, slot: int) -> dict[str, Any]:
        if slot < 1 or slot > MAX_CHANNELS:
            raise ValueError("Kanal yuvası geçersiz.")
        def change(doc: dict[str, Any]) -> dict[str, Any]:
            doc.pop(f"channel{slot}", None)
            return doc
        return self.update(change)


class ChannelSyncBot:
    def __init__(self, config: dict[str, Any]) -> None:
        self.token = config["telegram_bot_token"]
        self.admin_id = int(config["admin_telegram_user_id"])
        self.manifest = GitHubManifest(config["github_token"])
        self.pending: dict[int, dict[str, Any]] = {}
        self.offset: int | None = None

    def _telegram(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{TELEGRAM_API}/bot{self.token}/{method}"
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json", "User-Agent": "Macweb-Pydroid-Channel-Sync",
        })
        try:
            with urlopen(request, timeout=65 if method == "getUpdates" else 25) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise RuntimeError("Telegram bağlantısı geçici olarak başarısız oldu.") from None
        if not data.get("ok"):
            raise RuntimeError("Telegram API isteği başarısız oldu.")
        return data.get("result")

    def send(self, chat_id: int, text: str, keyboard: list[list[dict[str, str]]] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        self._telegram("sendMessage", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]})

    @staticmethod
    def menu() -> list[list[dict[str, str]]]:
        return [
            [{"text": "📺 Kanalları göster", "callback_data": "list"}],
            [{"text": "➕ Kanal ekle", "callback_data": "add"}, {"text": "✏️ Kanalı değiştir", "callback_data": "edit"}],
            [{"text": "🗑 Kanal sil", "callback_data": "delete"}],
        ]

    def require_private_admin(self, user: dict[str, Any] | None, chat: dict[str, Any] | None) -> bool:
        return bool(user and chat and int(user.get("id", 0)) == self.admin_id and chat.get("type") == "private")

    def channel_keyboard(self, action: str, doc: dict[str, Any]) -> list[list[dict[str, str]]]:
        rows = []
        for slot in range(1, MAX_CHANNELS + 1):
            channel = doc.get(f"channel{slot}")
            if channel:
                name = str(channel.get("name") or f"Kanal {slot}")
                rows.append([{"text": f"{slot}. {name[:38]}", "callback_data": f"{action}:{slot}"}])
        rows.append([{"text": "Menü", "callback_data": "menu"}])
        return rows

    def list_channels(self, chat_id: int) -> None:
        doc = self.manifest.read()
        rows = [f"{slot}. {doc[f'channel{slot}']['name']}" for slot in range(1, MAX_CHANNELS + 1) if f"channel{slot}" in doc]
        text = "\n".join(rows) if rows else "Henüz kanal eklenmedi. En fazla beş kanal ekleyebilirsiniz."
        self.send(chat_id, "Macweb yayın kanalları:\n" + text, self.menu())

    def start_add_or_edit(self, chat_id: int, slot: int, action: str) -> None:
        self.pending[self.admin_id] = {"action": action, "slot": slot, "step": "name"}
        existing = self.manifest.read().get(f"channel{slot}", {}) if action == "edit" else {}
        prompt = f"{slot}. kanal için yeni adı yazın (en fazla {MAX_NAME_LENGTH} karakter)."
        if existing.get("name"):
            prompt = f"{slot}. kanalın yeni adını yazın. Şu an: {existing['name']}"
        self.send(chat_id, prompt + "\nİptal için /cancel")

    def handle_callback(self, callback: dict[str, Any]) -> None:
        user = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        if not self.require_private_admin(user, chat):
            return
        callback_id = str(callback.get("id") or "")
        data = str(callback.get("data") or "")
        chat_id = int(chat["id"])
        try:
            if data == "menu":
                self.answer_callback(callback_id)
                self.send(chat_id, "Macweb kanal yönetimi · en fazla 5 iframe kanalı", self.menu())
            elif data == "list":
                self.answer_callback(callback_id)
                self.list_channels(chat_id)
            elif data == "add":
                doc = self.manifest.read()
                slot = next((i for i in range(1, MAX_CHANNELS + 1) if f"channel{i}" not in doc), None)
                self.answer_callback(callback_id)
                if slot is None:
                    self.send(chat_id, "Beş kanal yuvası dolu. Bir kanalı değiştirin veya silin.", self.menu())
                else:
                    self.start_add_or_edit(chat_id, slot, "add")
            elif data in {"edit", "delete"}:
                doc = self.manifest.read()
                self.answer_callback(callback_id)
                if not any(f"channel{i}" in doc for i in range(1, MAX_CHANNELS + 1)):
                    self.send(chat_id, "Henüz kayıtlı kanal yok.", self.menu())
                else:
                    label = "Değiştirmek" if data == "edit" else "Silmek"
                    self.send(chat_id, f"{label} istediğiniz kanalı seçin:", self.channel_keyboard(data, doc))
            elif re.fullmatch(r"edit:[1-5]", data):
                self.answer_callback(callback_id)
                self.start_add_or_edit(chat_id, int(data.split(":")[1]), "edit")
            elif re.fullmatch(r"delete:[1-5]", data):
                slot = int(data.split(":")[1])
                doc = self.manifest.delete_channel(slot)
                self.answer_callback(callback_id, "Silindi")
                self.send(chat_id, f"{slot}. kanal silindi. Macweb listesi Pages yayımlandıktan sonra güncellenecek.", self.menu())
            else:
                self.answer_callback(callback_id)
        except (RuntimeError, ValueError):
            self.answer_callback(callback_id, "İşlem başarısız")
            self.send(chat_id, "İşlem tamamlanamadı. GitHub token izinlerini ve internet bağlantısını kontrol edin.", self.menu())

    def handle_message(self, message: dict[str, Any]) -> None:
        user = message.get("from") or {}
        chat = message.get("chat") or {}
        if not self.require_private_admin(user, chat):
            return
        chat_id = int(chat["id"])
        user_id = int(user["id"])
        text = str(message.get("text") or "").strip()
        if text.startswith("/start"):
            self.pending.pop(user_id, None)
            self.send(chat_id, "Macweb kanal yönetimi · en fazla 5 iframe kanalı", self.menu())
            return
        if text.startswith("/cancel"):
            self.pending.pop(user_id, None)
            self.send(chat_id, "İşlem iptal edildi.", self.menu())
            return
        if text.startswith("/channels") or text.startswith("/list"):
            self.pending.pop(user_id, None)
            self.list_channels(chat_id)
            return
        if text.startswith("/add"):
            doc = self.manifest.read()
            slot = next((i for i in range(1, MAX_CHANNELS + 1) if f"channel{i}" not in doc), None)
            if slot is None:
                self.send(chat_id, "Beş kanal yuvası dolu. Önce bir kanalı değiştirin veya silin.", self.menu())
            else:
                self.start_add_or_edit(chat_id, slot, "add")
            return
        pending = self.pending.get(user_id)
        if not pending:
            self.send(chat_id, "Bir işlem seçin:", self.menu())
            return
        if pending["step"] == "name":
            try:
                name = clean_channel_name(text)
            except ValueError as exc:
                self.send(chat_id, str(exc) + " Tekrar deneyin veya /cancel yazın.")
                return
            pending["name"] = name
            pending["step"] = "iframe"
            self.send(chat_id, "Şimdi herkese açık HTTPS iframe adresini veya tek bir <iframe src=\"…\"></iframe> kodunu gönderin.\nÖnemli: Bu adres Macweb’in herkese açık GitHub deposuna yazılacaktır. Token/özel giriş içeren adres göndermeyin.\nİptal için /cancel")
            return
        try:
            iframe_url = extract_public_iframe_url(text)
        except ValueError as exc:
            self.send(chat_id, str(exc) + " Tekrar deneyin veya /cancel yazın.")
            return
        slot = int(pending["slot"])
        name = str(pending["name"])
        action = str(pending["action"])
        self.pending.pop(user_id, None)
        try:
            self.manifest.set_channel(slot, name, iframe_url)
        except (RuntimeError, ValueError):
            self.send(chat_id, "Kanal GitHub’a kaydedilemedi. Fine-grained tokenın inadinatv/macweb deposu için Contents: Read and write izni olduğundan emin olun.", self.menu())
            return
        verb = "eklendi" if action == "add" else "güncellendi"
        self.send(chat_id, f"{slot}. kanal ({name}) GitHub’a {verb}. Macweb’de görünmesi Pages dağıtımının tamamlanmasına bağlıdır.", self.menu())

    def run(self) -> None:
        print("Macweb kanal botu çalışıyor. Durdurmak için Ctrl+C kullanın.")
        while True:
            try:
                payload: dict[str, Any] = {"timeout": 50, "allowed_updates": ["message", "callback_query"]}
                if self.offset is not None:
                    payload["offset"] = self.offset
                updates = self._telegram("getUpdates", payload) or []
                for update in updates:
                    self.offset = int(update["update_id"]) + 1
                    try:
                        if "callback_query" in update:
                            self.handle_callback(update["callback_query"])
                        elif "message" in update:
                            self.handle_message(update["message"])
                    except (RuntimeError, ValueError, KeyError, TypeError):
                        # Avoid printing exception bodies, which may include user content or URLs.
                        print("Bir Telegram işlemi tamamlanamadı; bot çalışmayı sürdürüyor.")
            except KeyboardInterrupt:
                print("Bot durduruldu.")
                return
            except RuntimeError:
                print("Telegram/GitHub bağlantı hatası; 5 saniye sonra yeniden denenecek.")
                time.sleep(5)


def main() -> int:
    try:
        bot = ChannelSyncBot(load_config())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        bot.run()
    except KeyboardInterrupt:
        print("Bot durduruldu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
