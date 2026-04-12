from __future__ import annotations

import logging
from html import escape

import httpx

from car_deal_bot.config_loader import AppConfig
from car_deal_bot.models import VehicleListing
from car_deal_bot.settings import get_env

logger = logging.getLogger(__name__)


def _deal_badge(score: float | None) -> str:
    """Return a text badge for the deal score."""
    if score is None:
        return ""
    if score >= 25:
        return "GREAT DEAL"
    if score >= 15:
        return "GOOD DEAL"
    if score >= 5:
        return "FAIR DEAL"
    return ""


def _deal_badge_html(score: float | None) -> str:
    badge = _deal_badge(score)
    if not badge:
        return ""
    if score is not None and score >= 25:
        return f" <b>[{badge} -{score:.0f}%]</b>"
    return f" [{badge} -{score:.0f}%]"


def format_message_html(listings: list[VehicleListing]) -> str:
    if not listings:
        return "No great deals matched your criteria today."

    lines: list[str] = []
    for i, v in enumerate(listings, start=1):
        price = f"{v.price_eur:,.0f} EUR" if v.price_eur is not None else "—"
        km = f"{v.mileage_km:,} km".replace(",", ".") if v.mileage_km else "—"
        yr = str(v.year) if v.year else "—"
        loc = f" | {escape(v.location)}" if v.location else ""
        deal = _deal_badge_html(v.deal_score)
        lines.append(
            f"{i}. <b>{escape(v.title)}</b>{deal}\n"
            f"   {price} | {yr} | {km}{loc}\n"
            f'   <a href="{escape(v.url)}">View on {escape(v.source)}</a>'
        )
    header = f"<b>Top {len(listings)} car deals today:</b>\n"
    return header + "\n\n".join(lines)


def format_message_plain(listings: list[VehicleListing]) -> str:
    if not listings:
        return "No great deals matched your criteria today."

    lines: list[str] = []
    for i, v in enumerate(listings, start=1):
        price = f"{v.price_eur:,.0f} EUR" if v.price_eur is not None else "—"
        km = f"{v.mileage_km:,} km".replace(",", ".") if v.mileage_km else "—"
        yr = str(v.year) if v.year else "—"
        loc = f" | {v.location}" if v.location else ""
        badge = _deal_badge(v.deal_score)
        deal_str = f" [{badge} -{v.deal_score:.0f}%]" if badge else ""
        lines.append(
            f"{i}. {v.title}{deal_str}\n"
            f"   {price} | {yr} | {km}{loc}\n"
            f"   {v.url}"
        )
    header = f"--- Top {len(listings)} car deals today ---\n\n"
    return header + "\n\n".join(lines)


def _split_message(text: str, limit: int = 4096) -> list[str]:
    """Split long messages at paragraph boundaries to stay within Telegram's limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def send_telegram(html_message: str) -> bool:
    env = get_env()
    token, chat_id = env.telegram_bot_token, env.telegram_chat_id
    if not token or not chat_id:
        logger.warning(
            "Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing; "
            "printing to console instead."
        )
        return False

    chunks = _split_message(html_message)
    with httpx.Client(timeout=30.0) as client:
        for chunk in chunks:
            r = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
            )
            if r.status_code != 200:
                body = r.text[:300]
                logger.error("Telegram API error %s: %s", r.status_code, body)
                return False

    logger.info("Telegram notification sent (%s message(s)).", len(chunks))
    return True


def notify(listings: list[VehicleListing], app: AppConfig) -> None:
    if app.notification.telegram.enabled:
        ok = send_telegram(format_message_html(listings))
        if not ok:
            print(format_message_plain(listings))
    else:
        print(format_message_plain(listings))
