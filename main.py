import os
import time

import requests

# Comma-separated list of wallets, e.g. "0xaaa...,0xbbb..."
WALLETS = [w.strip().lower() for w in os.environ["POLY_WALLET"].split(",") if w.strip()]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Filters
MAX_PRICE = float(os.environ.get("MAX_PRICE", "0.78"))   # skip worse than about -355
MIN_PRICE = float(os.environ.get("MIN_PRICE", "0.05"))   # skip extreme longshots
MIN_STAKE = float(os.environ.get("MIN_STAKE", "500"))    # skip promo-sized trades

POLL_SECONDS = 20
API = "https://data-api.polymarket.com/activity"
TG = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def fetch(wallet):
    r = requests.get(
        API,
        params={"user": wallet, "type": "TRADE", "limit": 100},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def send(a):
    side = str(a.get("side", "")).upper()
    size = float(a.get("size", 0))
    price = float(a.get("price", 0))
    stake = size * price
    title = a.get("title") or a.get("slug") or "Unknown market"
    slug = a.get("eventSlug") or a.get("slug") or ""
    who = a.get("pseudonym") or a.get("name") or "unknown"
    emoji = "\U0001f7e2" if side == "BUY" else "\U0001f534"

    # American odds
    if price >= 0.5:
        american = f"-{round(price * 100 / (1 - price))}"
    else:
        american = f"+{round(100 / price - 100)}"

    text = (
        f"{emoji} <b>{side} {a.get('outcome', '?')}</b>\n"
        f"{title}\n\n"
        f"Trader: {who}\n"
        f"Odds: {price * 100:.1f}c ({american})\n"
        f"Stake: ${stake:,.2f}\n"
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


def keep(a):
    price = float(a.get("price", 0))
    stake = float(a.get("size", 0)) * price
    if price > MAX_PRICE or price < MIN_PRICE:
        return False
    if stake < MIN_STAKE:
        return False
    return True


def main():
    now = int(time.time())
    last = {w: now for w in WALLETS}
    print(f"watcher started, tracking {len(WALLETS)} wallet(s)", flush=True)

    while True:
        for wallet in WALLETS:
            try:
                new = [a for a in fetch(wallet) if int(a.get("timestamp", 0)) > last[wallet]]
                for a in sorted(new, key=lambda x: int(x["timestamp"])):
                    if keep(a):
                        send(a)
                        time.sleep(0.5)
                    last[wallet] = int(a["timestamp"])
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] {wallet[:10]}: {exc}", flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
