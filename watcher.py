#!/usr/bin/env python3
# ------------------------------------------------------------
# IES Amparo Sanz - Pellet Boiler
# PLC Alarm Watcher (alarm scraper)
#
# This script scrapes the PLC alarm webpage for the pellet boiler and
# sends notifications (Telegram) whenever a new alarm entry is detected.
#
# Copyright (C) 2026 Jorge Muñoz Rodenas
#
# License: GNU General Public License v3.0 (GPL-3.0)
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see: https://www.gnu.org/licenses/
# ------------------------------------------------------------


import json
import os
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import csv

load_dotenv()

ALARM_LOG_CSV = os.getenv("ALARM_LOG_CSV", "alarms_log.csv")

# -------- CONFIG FROM .env --------
PLC_BASE_URL = os.getenv("PLC_BASE_URL")          # e.g. http://192.168.1.50
PLC_USERNAME = os.getenv("PLC_USERNAME")
PLC_PASSWORD = os.getenv("PLC_PASSWORD")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "[Caldera Pellet]")
ONLY_OCCURRED = os.getenv("ONLY_OCCURRED", "true").lower() in ("1", "true", "yes", "y")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))

STATE_FILE = os.getenv("STATE_FILE", "alarm_state.json")


def require_env():
    missing = []
    for k in ["PLC_BASE_URL", "PLC_USERNAME", "PLC_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
        if not os.getenv(k):
            missing.append(k)
    if missing:
        raise RuntimeError(f"Faltan variables en .env: {', '.join(missing)}")


def log(msg: str):
    print(f"{datetime.now().isoformat(timespec='seconds')}  {msg}", flush=True)


def load_last_id():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("last_alarm_id")
    except Exception:
        return None


def save_last_id(alarm_id: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"last_alarm_id": alarm_id, "saved_at": datetime.now().isoformat()},
            f,
            ensure_ascii=False,
            indent=2,
        )


def append_alarm_to_csv(alarm: dict):
    file_exists = os.path.exists(ALARM_LOG_CSV)

    with open(ALARM_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow([
                "saved_at_local",
                "ref",
                "label",
                "type",
                "value",
                "plc_time",
                "transition",
                "current_state",
                "alarms_url",
                "alarm_id",
            ])

        w.writerow([
            datetime.now().isoformat(timespec="seconds"),
            alarm.get("ref", ""),
            alarm.get("etiqueta", ""),
            alarm.get("tipo", ""),
            alarm.get("valor", ""),
            alarm.get("hora", ""),
            alarm.get("transicion", ""),
            alarm.get("estado", ""),
            alarm.get("url", ""),
            alarm.get("id", ""),
        ])


def parse_hidden_inputs(form):
    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        data[name] = inp.get("value", "")
    return data


def login_and_get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    r = s.get(f"{PLC_BASE_URL}/login.htm", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"name": "beginsession"})
    if not form:
        raise RuntimeError("No beginsession form found in login.htm")

    action = form.get("action", "/beginsession")
    post_url = action if action.startswith("http") else f"{PLC_BASE_URL}{action}"

    payload = parse_hidden_inputs(form)
    payload["param1"] = PLC_USERNAME
    payload["param2"] = PLC_PASSWORD

    r2 = s.post(post_url, data=payload, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    r2.raise_for_status()

    import re
    urls = [h.headers.get("Location", "") for h in r2.history] + [r2.url]
    param0 = None
    for u in urls:
        m = re.search(r"param0=([A-F0-9]+)", u)
        if m:
            param0 = m.group(1)
            break

    if not param0:
        soup2 = BeautifulSoup(r2.text, "html.parser")
        a = soup2.find("a", href=True)
        if a:
            m = re.search(r"param0=([A-F0-9]+)", a["href"])
            if m:
                param0 = m.group(1)

    if not param0:
        raise RuntimeError("Login succeeded but could not extract param0 session token")

    return s, param0


def fetch_alarms_page(session, param0):
    alarms_url = f"{PLC_BASE_URL}/alarms.htm?param0={param0}"
    r = session.get(alarms_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text, alarms_url


def parse_latest_alarm(alarms_html: str, alarms_url: str):
    soup = BeautifulSoup(alarms_html, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("No se encontró la tabla de alarmas")

    rows = table.find_all("tr")
    if len(rows) < 2:
        return None

    tds = rows[1].find_all("td")
    if len(tds) < 7:
        raise RuntimeError("Fila de alarma con formato inesperado")

    ref = tds[0].get_text(strip=True)
    etiqueta = tds[1].get_text(strip=True)
    tipo = tds[2].get_text(strip=True)
    valor = tds[3].get_text(strip=True)
    hora = tds[4].get_text(strip=True)
    transicion = tds[5].get_text(strip=True)
    estado = tds[6].get_text(strip=True)

    alarm_id = f"{ref}|{hora}|{transicion}|{valor}|{etiqueta}"

    return {
        "id": alarm_id,
        "ref": ref,
        "etiqueta": etiqueta,
        "tipo": tipo,
        "valor": valor,
        "hora": hora,
        "transicion": transicion,
        "estado": estado,
        "url": alarms_url,
    }


def send_telegram(alarm: dict):
    # Message text (simple, robust)
    text = (
        f"🚨 {SUBJECT_PREFIX} ALARMA\n"
        f"{alarm['ref']} - {alarm['etiqueta']}\n"
        f"🕒 {alarm['hora']}\n"
        f"🔁 {alarm['transicion']} | 📌 {alarm['estado']}\n"
        f"🌐 {alarm['url']}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram API error {r.status_code}: {r.text}")


def check_once():
    last_id = load_last_id()
    session, param0 = login_and_get_session()
    alarms_html, alarms_url = fetch_alarms_page(session, param0)
    alarm = parse_latest_alarm(alarms_html, alarms_url)

    if alarm is None:
        log("No hay alarmas en la tabla.")
        return

    if ONLY_OCCURRED and alarm["transicion"].strip().lower() != "ocurrido":
        log("Última alarma no es 'Ocurrido' (filtro activo).")
        return

    if alarm["id"] == last_id:
        log("Sin novedades.")
        return

    send_telegram(alarm)
    append_alarm_to_csv(alarm)
    save_last_id(alarm["id"])
    log(f"✅ Aviso Telegram enviado. Nueva alarma: {alarm['id']}")


def main():
    require_env()
    log("Watcher iniciado (Telegram only).")

    while True:
        try:
            check_once()
        except Exception as e:
            log(f"ERROR: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
