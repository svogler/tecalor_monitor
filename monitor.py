#!/usr/bin/env python3
"""Tecalor heat pump error list monitor.

Fetches the error list from the heat pump ISG interface, compares it
against the previously saved state, and sends an email for any new entries.
Designed to be run periodically via cron.
"""

import argparse
import configparser
import json
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

_DIR = Path(__file__).parent
CONFIG_FILE = _DIR / "config.ini"
STATE_FILE = _DIR / "state.json"


def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def fetch_error_list(url: str, timeout: int = 10) -> list[dict]:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="info")
    if table is None:
        raise ValueError("Error list table not found in page response.")
    errors = []
    for row in table.find("tbody").find_all("tr"):
        cells = row.find_all("td", class_="value")
        if len(cells) == 5:
            errors.append({
                "nr":         cells[0].get_text(strip=True),
                "error_code": cells[1].get_text(strip=True),
                "heatpump":   cells[2].get_text(strip=True),
                "date":       cells[3].get_text(strip=True),
                "time":       cells[4].get_text(strip=True),
            })
    return errors


def load_state() -> set[tuple] | None:
    """Return set of known (error_code, heatpump, date, time) tuples, or None on first run."""
    if not STATE_FILE.exists():
        return None
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {tuple(entry) for entry in data}


def save_state(errors: list[dict]) -> None:
    entries = [
        [e["error_code"], e["heatpump"], e["date"], e["time"]]
        for e in errors
    ]
    STATE_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def find_new_errors(current: list[dict], known: set[tuple]) -> list[dict]:
    new = []
    for e in current:
        key = (e["error_code"], e["heatpump"], e["date"], e["time"])
        if key not in known:
            new.append(e)
    return new


def send_email(config: configparser.ConfigParser, new_errors: list[dict]) -> None:
    smtp = config["smtp"]
    count = len(new_errors)
    subject = f"Wärmepumpe: {count} neue Meldung{'en' if count != 1 else ''}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp["from"]
    msg["To"] = smtp["to"]

    # Plain-text body
    header = f"{'Nr.':<6}  {'Fehlernr.':<12}  {'WP':<4}  {'Datum':<12}  Uhrzeit"
    separator = "-" * len(header)
    rows_txt = "\n".join(
        f"{e['nr']:<6}  {e['error_code']:<12}  {e['heatpump']:<4}  {e['date']:<12}  {e['time']}"
        for e in new_errors
    )
    plain = f"Neue Meldungen in der Meldungsliste:\n\n{header}\n{separator}\n{rows_txt}\n"
    msg.attach(MIMEText(plain, "plain", "utf-8"))

    # HTML body
    rows_html = "".join(
        f"<tr><td>{e['nr']}</td><td>{e['error_code']}</td>"
        f"<td>{e['heatpump']}</td><td>{e['date']}</td><td>{e['time']}</td></tr>"
        for e in new_errors
    )
    html = (
        "<html><body>"
        "<p>Neue Meldungen in der Meldungsliste:</p>"
        "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse:collapse'>"
        "<tr style='background:#eee'>"
        "<th>Nr.</th><th>Fehlernummer</th><th>WP</th><th>Datum</th><th>Uhrzeit</th>"
        "</tr>"
        f"{rows_html}"
        "</table></body></html>"
    )
    msg.attach(MIMEText(html, "html", "utf-8"))

    host = smtp["host"]
    port = int(smtp.get("port", 587))
    use_tls = smtp.getboolean("use_tls", True)
    user = smtp.get("user", "").strip()
    token = smtp.get("token", "").strip()

    with smtplib.SMTP(host, port) as server:
        if use_tls:
            server.starttls()
        if user and token:
            server.login(user, token)
        server.sendmail(smtp["from"], smtp["to"], msg.as_string())


def send_fetch_error_email(config: configparser.ConfigParser, exc: Exception) -> None:
    smtp = config["smtp"]
    subject = "Wärmepumpe: Meldungsliste konnte nicht abgerufen werden"
    plain = f"Fehler beim Abrufen der Meldungsliste:\n\n{exc}\n"
    html = (
        "<html><body>"
        "<p><strong>Fehler beim Abrufen der Meldungsliste:</strong></p>"
        f"<pre>{exc}</pre>"
        "</body></html>"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp["from"]
    msg["To"] = smtp["to"]
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    host = smtp["host"]
    port = int(smtp.get("port", 587))
    use_tls = smtp.getboolean("use_tls", True)
    user = smtp.get("user", "").strip()
    token = smtp.get("token", "").strip()

    with smtplib.SMTP(host, port) as server:
        if use_tls:
            server.starttls()
        if user and token:
            server.login(user, token)
        server.sendmail(smtp["from"], smtp["to"], msg.as_string())


def simulate_email(config: configparser.ConfigParser) -> None:
    fake_errors = [
        {"nr": "1", "error_code": "E001", "heatpump": "WP1", "date": "18.02.2026", "time": "12:00:00"},
    ]
    send_email(config, fake_errors)
    print("Simulation: email sent with fake error entry.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tecalor heat pump monitor")
    parser.add_argument("--simulate", action="store_true", help="Send a test email with a fake error (no heat pump fetch)")
    args = parser.parse_args()

    config = load_config()

    if args.simulate:
        try:
            simulate_email(config)
        except Exception as exc:
            print(f"ERROR: Could not send simulation email: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    url = config["monitor"]["url"]

    try:
        current = fetch_error_list(url)
    except Exception as exc:
        print(f"ERROR: Could not fetch error list: {exc}", file=sys.stderr)
        try:
            send_fetch_error_email(config, exc)
            print("Fetch error notification email sent.")
        except Exception as mail_exc:
            print(f"ERROR: Could not send fetch error email: {mail_exc}", file=sys.stderr)
        sys.exit(1)

    known = load_state()

    if known is None:
        save_state(current)
        print(f"First run: saved {len(current)} existing entries. No email sent.")
        return

    new_errors = find_new_errors(current, known)

    if not new_errors:
        print("No new errors.")
        return

    try:
        send_email(config, new_errors)
        print(f"Email sent: {len(new_errors)} new error(s).")
    except Exception as exc:
        print(f"ERROR: Could not send email: {exc}", file=sys.stderr)
        sys.exit(1)

    # Only update state after a successful email send
    save_state(current)


if __name__ == "__main__":
    main()
