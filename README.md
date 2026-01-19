# PLC Alarm Watcher (IES Amparo Sanz)

A small Python service that logs into a Trend IQ4 (or compatible) PLC web interface, scrapes the **Alarms** page, and sends **Telegram notifications** whenever a **new alarm occurs**.  
Designed for monitoring the **pellet boiler installation** at **IES Amparo Sanz**.

---

## Features

- ✅ Scrapes PLC alarms webpage (`alarms.htm`)
- ✅ Detects new alarm entries and avoids duplicates
- ✅ Telegram notifications (mobile alerts)
- ✅ Persistent alarm history log to CSV (`alarms_log.csv`)
- ✅ Runs as a `systemd` service (auto-start + auto-restart)
- ✅ Uses `.env` file for configuration (secrets not committed)

---

## Requirements

- Raspberry Pi OS / Debian-based Linux
- Python 3
- Packages:
  - `requests`
  - `beautifulsoup4`
  - `python-dotenv`

---

## Install inside the venv:

```bash
python -m pip install requests beautifulsoup4 python-dotenv

---

## Installation

### Clone repository

git clone git@github.com:jorgeroden/plc-alarm-watcher.git
cd plc-alarm-watcher

### Create virtual environment

python3 -m venv venv
source venv/bin/activate
python -m pip install requests beautifulsoup4 python-dotenv

### Create .env

cp .env.example .env

### Edit .env and set your values:

PLC_BASE_URL
PLC_USERNAME
PLC_PASSWORD
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID

### Running manually

source venv/bin/activate
python watcher.py

### Running as a systemd service

sudo nano /etc/systemd/system/plc-watcher.service

[Unit]
Description=PLC Alarm Watcher (Pellet Boiler) - IES Amparo Sanz
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jorgeroden
WorkingDirectory=/home/jorgeroden/plc-alarm-watcher
Environment="PYTHONUNBUFFERED=1"
ExecStart=/home/jorgeroden/plc-alarm-watcher/venv/bin/python /home/jorgeroden/plc-alarm-watcher/watcher.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target


### Enable and start the service:

sudo systemctl daemon-reload
sudo systemctl enable plc-watcher.service
sudo systemctl restart plc-watcher.service

### Check logs:

journalctl -u plc-watcher.service -f

### Alarm History Log

A CSV file is automatically created and appended when a new alarm is detected:

alarms_log.csv

Example:

tail -n 20 alarms_log.csv