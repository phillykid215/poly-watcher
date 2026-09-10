import os
import time

import requests

WALLET = os.environ["POLY_WALLET"].lower()
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

POLL_SECONDS = 20
API = "https://data-api.polymarket.com/activity"
TG = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def fetch():
    r = requests.get(
        API,
        params={"user": WALLET, "type": "TRADE", "limit": 100},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def send(a):
    side = str(a.get("side", "")).upper()
    size = float(a.get("size", 0))
    price = float(a.get("price", 0))
    title = a.get("title") or a.get("slug") or "Unknown market"
    slug = a.get("eventSlug") or a.get("slug") or ""
    emoji = "\U0001f7e2" if side == "BUY" else "\U0001f534"

    text = (
        f"{emoji} <b>{side} {a.get('outcome', '?')}</b>\n"
        f"{title}\n\n"
        f"Odds: {price * 100:.1f}c\n"
        f"Stake: ${size * price:,.2f}\n"
        f"Shares: {size:,.0f}"
    )
    if slug:
        text += f"\n\nhttps://polymarket.com/event/{slug}"

    requests.post(
        TG,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )


def main():
    last = int(time.time())
    print("watcher started", flush=True)

    while True:
        try:
            new = [a for a in fetch() if int(a.get("timestamp", 0)) > last]
            for a in sorted(new, key=lambda x: int(x["timestamp"])):
                send(a)
                last = int(a["timestamp"])
                time.sleep(0.5)
        except Exception as exc:
            print(f"[warn] {exc}", flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

