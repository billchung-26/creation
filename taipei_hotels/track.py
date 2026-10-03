#!/usr/bin/env python3
"""Track nightly prices of Taipei Amex FHR / THC hotels and email a change summary.

Hotel list: Open Hotel Data (kevchentw/open-hotel-data, public/data/hotels.json).
Prices: Xotelo (TripAdvisor rates), the same provider Open Hotel Data uses,
queried for every 1-night stay in the configured window.

Only the Python standard library is used. Configuration via env vars:
  WINDOW_START   first check-in date            (default 2026-11-20)
  WINDOW_END     last check-out date            (default 2027-01-18)
  CITY           city to match                  (default Taipei)
  CURRENCY       Xotelo currency                (default USD)
  CHANGE_PCT     min % change to report a night (default 5)
  GMAIL_USER / GMAIL_APP_PASSWORD / MAIL_TO      email settings (optional)
  DRY_RUN=1      do not send email or write the snapshot
"""

import datetime as dt
import json
import os
import smtplib
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

HOTELS_URL = "https://raw.githubusercontent.com/kevchentw/open-hotel-data/main/public/data/hotels.json"
XOTELO_URL = "https://data.xotelo.com/api/rates"
AMEX_PLANS = {"amex_fhr": "FHR", "amex_thc": "THC"}

WINDOW_START = dt.date.fromisoformat(os.environ.get("WINDOW_START", "2026-11-20"))
WINDOW_END = dt.date.fromisoformat(os.environ.get("WINDOW_END", "2027-01-18"))
CITY = os.environ.get("CITY", "Taipei")
CURRENCY = os.environ.get("CURRENCY", "USD").upper()
CHANGE_PCT = float(os.environ.get("CHANGE_PCT", "5"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"

SNAPSHOT_PATH = Path(__file__).parent / "data" / "latest.json"


def http_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "taipei-hotel-tracker"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as exc:  # network errors, HTTP errors, bad JSON
            if attempt == retries - 1:
                raise
            print(f"retry {url}: {exc}", file=sys.stderr)
            time.sleep(2 ** (attempt + 1))


def load_hotels(payload):
    """Return Taipei hotels that are in FHR or THC, keyed by Open Hotel Data id."""
    city = CITY.lower()
    hotels = {}
    for h in payload.get("hotels", []):
        programs = [AMEX_PLANS[p] for p in h.get("plans", []) if p in AMEX_PLANS]
        if not programs:
            continue
        place = " ".join(str(h.get(k) or "") for k in ("city", "formatted_address", "amex_url")).lower()
        if city not in place:
            continue
        hotels[h["id"]] = {
            "name": h.get("name") or h["id"],
            "programs": programs,
            "tripadvisor_id": h.get("tripadvisor_id") or "",
            "amex_url": h.get("amex_url") or "",
        }
    return hotels


def stay_dates(today):
    day = max(WINDOW_START, today)
    while day < WINDOW_END:
        yield day
        day += dt.timedelta(days=1)


def fetch_price(tripadvisor_id, check_in):
    query = urllib.parse.urlencode({
        "hotel_key": tripadvisor_id,
        "chk_in": check_in.isoformat(),
        "chk_out": (check_in + dt.timedelta(days=1)).isoformat(),
        "currency": CURRENCY,
    })
    try:
        payload = http_json(f"{XOTELO_URL}?{query}")
    except Exception as exc:
        print(f"xotelo failed {tripadvisor_id} {check_in}: {exc}", file=sys.stderr)
        return None
    best = None
    for rate in (payload.get("result") or {}).get("rates") or []:
        try:
            total = float(rate.get("rate")) + float(rate.get("tax") or 0)
        except (TypeError, ValueError):
            continue
        if best is None or total < best["price"]:
            best = {"price": round(total, 2), "provider": rate.get("name") or rate.get("code") or ""}
    return best


def collect_prices(hotels, today):
    jobs = [(hid, h["tripadvisor_id"], d) for hid, h in hotels.items() if h["tripadvisor_id"] for d in stay_dates(today)]

    def run(job):
        hid, ta_id, day = job
        time.sleep(0.2)  # be gentle with the free API
        return hid, day.isoformat(), fetch_price(ta_id, day)

    prices = {hid: {} for hid in hotels}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for hid, day, best in pool.map(run, jobs):
            if best:
                prices[hid][day] = best
    return prices


def cheapest(nights):
    if not nights:
        return None
    day = min(nights, key=lambda d: (nights[d]["price"], d))
    return day, nights[day]["price"]


def money(value):
    return f"{CURRENCY} {value:,.0f}"


def diff(prev, curr):
    """Build the human-readable summary comparing two snapshots."""
    prev_hotels = (prev or {}).get("hotels", {})
    lines, rows = [], []

    added = [h for h in curr["hotels"] if h not in prev_hotels] if prev else []
    removed = [h for h in prev_hotels if h not in curr["hotels"]]
    for hid in added:
        lines.append(f"🆕 New in list: {curr['hotels'][hid]['name']}")
    for hid in removed:
        lines.append(f"❌ Removed from list: {prev_hotels[hid]['name']}")

    for hid, hotel in sorted(curr["hotels"].items(), key=lambda kv: kv[1]["name"]):
        nights = curr["prices"].get(hid, {})
        old_nights = (prev or {}).get("prices", {}).get(hid, {})
        low = cheapest(nights)
        old_low = cheapest({d: v for d, v in old_nights.items() if d in nights}) or cheapest(old_nights)
        changes = []
        for day, info in sorted(nights.items()):
            before = old_nights.get(day)
            if not before:
                continue
            delta = info["price"] - before["price"]
            if before["price"] and abs(delta) / before["price"] * 100 >= CHANGE_PCT:
                changes.append((day, before["price"], info["price"], delta))
        rows.append({
            "name": hotel["name"],
            "programs": "/".join(hotel["programs"]),
            "url": hotel["amex_url"],
            "nights": len(nights),
            "low": low,
            "old_low": old_low,
            "drops": sum(1 for c in changes if c[3] < 0),
            "rises": sum(1 for c in changes if c[3] > 0),
            "changes": changes,
        })
    return lines, rows


def render(curr, prev, lines, rows):
    window = f"{WINDOW_START:%m/%d} – {WINDOW_END:%m/%d}"
    subject_bits = []
    drops = sum(r["drops"] for r in rows)
    if drops:
        subject_bits.append(f"{drops} nights cheaper")
    if lines:
        subject_bits.append("list changed")
    subject = f"[Taipei FHR/THC] {window} " + (", ".join(subject_bits) if subject_bits else "daily summary")

    text = [f"Taipei Amex FHR/THC prices, stays {window} (1 night, lowest rate incl. tax, via Xotelo)",
            f"Fetched {curr['generated_at']}" + (f", compared with {prev['generated_at']}" if prev else " (first run, no comparison yet)"), ""]
    text += lines + ([""] if lines else [])
    html = [f"<h2>Taipei Amex FHR/THC — stays {escape(window)}</h2>",
            f"<p>1-night lowest rate incl. tax via Xotelo. Fetched {escape(curr['generated_at'])}"
            + (f", compared with {escape(prev['generated_at'])}" if prev else " (first run)") + ".</p>"]
    if lines:
        html.append("<ul>" + "".join(f"<li>{escape(l)}</li>" for l in lines) + "</ul>")
    html.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>"
                "<tr><th>Hotel</th><th>Program</th><th>Cheapest night</th><th>Previous cheapest</th>"
                f"<th>Nights ↓ / ↑ ≥{CHANGE_PCT:g}%</th><th>Nights priced</th></tr>")

    for r in rows:
        low = f"{money(r['low'][1])} ({r['low'][0]})" if r["low"] else "no price"
        old = f"{money(r['old_low'][1])} ({r['old_low'][0]})" if r["old_low"] else "—"
        text.append(f"■ {r['name']} [{r['programs']}]  cheapest {low}  | before {old}  | ↓{r['drops']} ↑{r['rises']}")
        for day, before, after, delta in r["changes"][:15]:
            arrow = "↓" if delta < 0 else "↑"
            text.append(f"    {day}: {money(before)} → {money(after)} {arrow}{abs(delta):,.0f}")
        if len(r["changes"]) > 15:
            text.append(f"    … {len(r['changes']) - 15} more")
        name = f"<a href='{escape(r['url'])}'>{escape(r['name'])}</a>" if r["url"] else escape(r["name"])
        html.append(f"<tr><td>{name}</td><td>{escape(r['programs'])}</td><td>{escape(low)}</td><td>{escape(old)}</td>"
                    f"<td>{r['drops']} / {r['rises']}</td><td>{r['nights']}</td></tr>")
    html.append("</table>")

    changed = [r for r in rows if r["changes"]]
    if changed:
        html.append(f"<h3>Nights that moved ≥{CHANGE_PCT:g}%</h3>")
        for r in changed:
            items = "".join(
                f"<li>{d}: {money(b)} → {money(a)} <b style='color:{'#0a7d32' if x < 0 else '#b3261e'}'>"
                f"{'↓' if x < 0 else '↑'}{abs(x):,.0f}</b></li>" for d, b, a, x in r["changes"])
            html.append(f"<p><b>{escape(r['name'])}</b></p><ul>{items}</ul>")
    html.append(f"<p style='color:#666'>Hotel list: Open Hotel Data ({escape(curr['hotel_list_generated_at'])}). "
                "Prices are public OTA rates, not the Amex Travel FHR rate.</p>")
    return subject, "\n".join(text), "\n".join(html)


def send_email(subject, text, html):
    user, password = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and password):
        print("GMAIL_USER / GMAIL_APP_PASSWORD not set; skipping email.")
        return
    to = os.environ.get("MAIL_TO") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    print(f"Email sent to {to}")


def main():
    today = dt.date.today()
    if today >= WINDOW_END:
        print("Tracking window is over; nothing to do.")
        return

    source = http_json(HOTELS_URL)
    hotels = load_hotels(source)
    print(f"{len(hotels)} {CITY} FHR/THC hotels: {', '.join(h['name'] for h in hotels.values())}")
    curr = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "hotel_list_generated_at": (source.get("metadata") or {}).get("generated_at", ""),
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "currency": CURRENCY,
        "hotels": hotels,
        "prices": collect_prices(hotels, today),
    }
    priced = sum(len(v) for v in curr["prices"].values())
    print(f"Fetched {priced} night prices")

    prev = json.loads(SNAPSHOT_PATH.read_text()) if SNAPSHOT_PATH.exists() else None
    if prev and prev.get("currency") != CURRENCY:
        prev = None
    subject, text, html = render(curr, prev, *diff(prev, curr))
    print(subject)
    print(text)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(html + "\n")

    if DRY_RUN:
        return
    if priced == 0 and hotels:
        # Don't overwrite a good snapshot with an empty one when the API is down.
        sys.exit("No prices fetched; keeping previous snapshot.")
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(curr, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    send_email(subject, text, html)


if __name__ == "__main__":
    main()
