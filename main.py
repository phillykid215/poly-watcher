import os
import time
from datetime import datetime, timezone, timedelta

import requests

WALLETS = [w.strip().lower() for w in os.environ["POLY_WALLET"].split(",") if w.strip()]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Alert filters
MAX_PRICE = float(os.environ.get("MAX_PRICE", "0.78"))
MIN_PRICE = float(os.environ.get("MIN_PRICE", "0.05"))
MIN_STAKE = float(os.environ.get("MIN_STAKE", "500"))

# Wallets whose alerts get the MAX PLAY tag (comma-separated addresses)
MAX_WALLETS = {w.strip().lower() for w in os.environ.get("MAX_WALLETS", "").split(",") if w.strip()}

# Hour (0-23) in US Eastern to post the daily recap
RECAP_HOUR = int(os.environ.get("RECAP_HOUR", "10"))

POLL_SECONDS = 20
ACTIVITY = "https://data-api.polymarket.com/activity"
POSITIONS = "https://data-api.polymarket.com/positions"
TG = f"https://api.telegram.org/bot{TOKEN}"

# conditionId -> {wallet, outcome, price, size, title}  (bets we alerted on)
pending = {}


def eastern_now():
    # Close enough for scheduling; no tz database needed.
    return datetime.now(timezone.utc) - timedelta(hours=4)


def american(price):
    if price >= 0.5:
        return f"-{round(price * 100 / (1 - price))}"
    return f"+{round(100 / price - 100)}"


def tg(method, payload):
    r = requests.post(f"{TG}/{method}", json=payload, timeout=20)
    if r.status_code == 429:
        time.sleep(float(r.json().get("retry_after", 2)))
        r = requests.post(f"{TG}/{method}", json=payload, timeout=20)
    return r


def fetch_activity(wallet):
    r = requests.get(
        ACTIVITY,
        params={"user": wallet, "type": "TRADE", "limit": 100},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def fetch_closed(wallet):
    r = requests.get(
        POSITIONS,
        params={"user": wallet, "closed": "true", "limit": 200},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def keep(a):
    price = float(a.get("price", 0))
    stake = float(a.get("size", 0)) * price
    return MIN_PRICE <= price <= MAX_PRICE and stake >= MIN_STAKE


def send_alert(a, wallet):
    side = str(a.get("side", "")).upper()
    size = float(a.get("size", 0))
    price = float(a.get("price", 0))
    title = a.get("title") or a.get("slug") or "Unknown market"
    slug = a.get("eventSlug") or a.get("slug") or ""
    who = a.get("pseudonym") or a.get("name") or wallet[:8]
    emoji = "\U0001f7e2" if side == "BUY" else "\U0001f534"

    header = "\U0001f525 <b>MAX PLAY</b>\n" if wallet in MAX_WALLETS else ""

    text = (
        f"{header}"
        f"{emoji} <b>{side} {a.get('outcome', '?')}</b>\n"
        f"{title}\n\n"
        f"Trader: {who}\n"
        f"Odds: {price * 100:.1f}c ({american(price)})\n"
        f"Stake: ${size * price:,.2f}\n"
        f"Shares: {size:,.0f}"
    )
    if slug:
        text += f"\n\nhttps://polymarket.com/event/{slug}"

    tg("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })

    cid = a.get("conditionId")
    asset = a.get("asset")
    if cid and side == "BUY":
        pending[f"{wallet}:{asset}"] = {
            "wallet": wallet,
            "who": who,
            "asset": asset,
            "outcome": a.get("outcome", "?"),
            "price": price,
            "title": title,
        }


def post_recap():
    """Check every pending bet for settlement; report the ones that resolved."""
    lines_by_trader = {}

    for wallet in WALLETS:
        try:
            closed = fetch_closed(wallet)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] recap {wallet[:10]}: {exc}", flush=True)
            continue

        by_asset = {p.get("asset"): p for p in closed}

        for key in list(pending.keys()):
            bet = pending[key]
            if bet["wallet"] != wallet:
                continue
            pos = by_asset.get(bet["asset"])
            if not pos:
                continue

            cur = float(pos.get("curPrice", -1))
            if cur < 0:
                continue
            # Settled markets price at 1 (won) or 0 (lost).
            if 0.01 < cur < 0.99:
                continue

            size = float(pos.get("size", 0))
            cost = size * float(pos.get("avgPrice", bet["price"]))
            payout = size if cur >= 0.99 else 0.0
            pnl = payout - cost
            mark = "\u2705" if payout else "\u274c"

            lines_by_trader.setdefault(bet["who"], []).append(
                f"{mark} {bet['outcome']} {bet['price'] * 100:.0f}c "
                f"\u2192 {'+' if pnl >= 0 else '-'}${abs(pnl):,.0f}\n"
                f"    <i>{bet['title'][:60]}</i>"
            )
            del pending[key]

    if not lines_by_trader:
        return

    blocks = []
    for who, lines in lines_by_trader.items():
        blocks.append(f"<b>{who}</b>\n" + "\n".join(lines))

    tg("sendMessage", {
        "chat_id": CHAT_ID,
        "text": "\U0001f4ca <b>Settled</b>\n\n" + "\n\n".join(blocks),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def main():
    now = int(time.time())
    last = {w: now for w in WALLETS}
    last_recap_day = eastern_now().date()
    print(f"watcher started, tracking {len(WALLETS)} wallet(s)", flush=True)

    while True:
        for wallet in WALLETS:
            try:
                new = [a for a in fetch_activity(wallet)
                       if int(a.get("timestamp", 0)) > last[wallet]]
                for a in sorted(new, key=lambda x: int(x["timestamp"])):
                    if keep(a):
                        send_alert(a, wallet)
                        time.sleep(0.5)
                    last[wallet] = int(a["timestamp"])
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] {wallet[:10]}: {exc}", flush=True)

        et = eastern_now()
        if et.date() != last_recap_day and et.hour >= RECAP_HOUR:
            try:
                post_recap()
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] recap: {exc}", flush=True)
            last_recap_day = et.date()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
