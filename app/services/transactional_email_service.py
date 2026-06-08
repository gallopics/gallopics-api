# ruff: noqa: E501

import html
from typing import Sequence

import httpx

from app.config import Settings


class TransactionalEmailService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def send_purchase_receipt(
        self,
        *,
        recipient_email: str | None,
        order_id: str,
        amount: int,
        currency: str,
        line_items: Sequence[dict],
    ) -> dict:
        if not recipient_email:
            return {"status": "skipped", "reason": "missing_recipient"}
        if not self._is_configured:
            return {"status": "skipped", "reason": "email_not_configured"}

        payload = {
            "from": self.settings.transactional_email_from,
            "to": [recipient_email],
            "subject": "Your Gallopics photos are ready",
            "text": self._build_text_receipt(order_id, amount, currency, line_items),
            "html": self._build_html_receipt(order_id, amount, currency, line_items),
            "tags": [
                {"name": "type", "value": "purchase_receipt"},
                {"name": "order_id", "value": order_id},
            ],
        }
        if self.settings.transactional_email_reply_to:
            payload["reply_to"] = [self.settings.transactional_email_reply_to]

        async with httpx.AsyncClient(
            base_url=self.settings.resend_api_url,
            timeout=20.0,
            headers={
                "Authorization": f"Bearer {self.settings.resend_api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": f"purchase-receipt-{order_id}",
            },
        ) as client:
            response = await client.post("/emails", json=payload)
            response.raise_for_status()
            body = response.json()

        return {
            "status": "sent",
            "provider": "resend",
            "provider_message_id": body.get("id"),
            "recipient": recipient_email,
        }

    @property
    def _is_configured(self) -> bool:
        return bool(
            self.settings.transactional_email_enabled
            and self.settings.resend_api_url
            and self.settings.resend_api_key
            and self.settings.transactional_email_from
        )

    def _build_text_receipt(
        self,
        order_id: str,
        amount: int,
        currency: str,
        line_items: Sequence[dict],
    ) -> str:
        rows = [self._build_text_item_row(item, currency) for item in line_items] or [
            "- Digital photo purchase"
        ]

        return "\n".join(
            [
                "Thank you for your Gallopics purchase.",
                "",
                f"Order: {order_id}",
                "",
                "Items:",
                *rows,
                "",
                f"Total: {self._format_amount(amount, currency)}",
                "",
                "Your purchased photos are available from the download links in this email and after checkout.",
            ]
        )

    def _build_html_receipt(
        self,
        order_id: str,
        amount: int,
        currency: str,
        line_items: Sequence[dict],
    ) -> str:
        photo_count = sum(int(item.get("quantity") or 1) for item in line_items) or 1
        photo_label = "photo" if photo_count == 1 else "photos"
        download_cards = self._build_html_download_cards(line_items, currency)

        return f"""\
<!doctype html>
<html lang="en">
  <body style="margin: 0; padding: 0; background: #eceef2; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; color: #040136;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: #eceef2; padding: 48px 20px 80px;">
      <tr>
        <td align="center">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width: 600px; max-width: 100%; margin: 0 auto; border-radius: 12px; overflow: hidden; background: #ffffff;">
            <tr>
              <td style="background: #ffffff; padding: 32px 48px; text-align: center;">
                <div style="font-size: 28px; line-height: 30px; font-weight: 800; color: #1b3aec; letter-spacing: 0;">Gallopics</div>
              </td>
            </tr>
            <tr>
              <td style="background: #f9fafb; padding: 48px 52px 40px; text-align: center;">
                <h1 style="margin: 0 0 12px; font-size: 30px; font-weight: 700; color: #040136; line-height: 1.2;">Your photos are ready</h1>
                <p style="margin: 0 auto 28px; font-size: 15px; line-height: 1.65; color: #666666; max-width: 360px;">Your purchase is confirmed.</p>
                <span style="display: inline-block; background: #eceef6; border: 1px solid #d0d6f0; border-radius: 7px; padding: 8px 20px; font-size: 13px; color: #666666;">
                  Order <strong style="color: #040136;">{html.escape(order_id)}</strong>
                  &nbsp;&middot;&nbsp;
                  <strong style="color: #040136;">{photo_count}</strong> {photo_label}
                </span>
              </td>
            </tr>
            <tr>
              <td style="background: #f9fafb; padding: 40px 52px; border-bottom: 1px solid #e5e7eb;">
                <h2 style="margin: 0 0 14px; font-size: 20px; font-weight: 700; color: #040136;">Hi,</h2>
                <p style="margin: 0 0 14px; font-size: 15px; line-height: 1.7; color: #444444;">Thank you for your purchase. Your photos are now available from the links below.</p>
                <p style="margin: 0; font-size: 15px; line-height: 1.7; color: #444444;">Keep this email so you can return to your purchased photos later.</p>
              </td>
            </tr>
            <tr>
              <td style="background: #ffffff; padding: 32px 52px 16px;">
                <p style="margin: 0; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: #aaaaaa; font-weight: 700;">Your Downloads</p>
              </td>
            </tr>
            <tr>
              <td style="background: #ffffff; padding: 0 52px 40px;">
                {download_cards}
                <table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%; margin-top: 22px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 10px;">
                  <tr>
                    <td style="padding: 16px; font-size: 13px; color: #666666;">Total paid</td>
                    <td align="right" style="padding: 16px; font-size: 16px; font-weight: 700; color: #040136;">{self._format_amount(amount, currency)}</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="background: #1a1a1a; padding: 36px 40px 28px;">
                <div style="font-size: 24px; line-height: 26px; font-weight: 800; color: #ffffff; margin-bottom: 12px;">Gallopics</div>
                <p style="margin: 0 0 24px; font-size: 13px; line-height: 1.7; color: rgba(255,255,255,0.55); max-width: 360px;">We capture horse competitions across Sweden. Search your event, spot your photos, and purchase your favorites.</p>
                <p style="margin: 0 0 24px; font-size: 13px; color: rgba(255,255,255,0.55);">Need help? <a href="mailto:hellogallopics@gmail.com" style="color: #ffffff; text-decoration: none; font-weight: 600;">hellogallopics@gmail.com</a></p>
                <div style="height: 1px; background: rgba(255,255,255,0.08); margin-bottom: 20px;"></div>
                <table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%;">
                  <tr>
                    <td style="font-size: 12px; color: rgba(255,255,255,0.35);">&copy; 2026 Gallopics</td>
                    <td align="right">
                      <a href="https://gallopics.com/terms" style="font-size: 12px; color: rgba(255,255,255,0.35); text-decoration: none; margin-left: 18px;">Terms</a>
                      <a href="https://gallopics.com/privacy" style="font-size: 12px; color: rgba(255,255,255,0.35); text-decoration: none; margin-left: 18px;">Privacy</a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    def _build_text_item_row(self, item: dict, currency: str) -> str:
        row = (
            f"- {item.get('name', 'Photo')} x {item.get('quantity', 1)}: "
            f"{self._format_amount(int(item.get('total_amount') or 0), currency)}"
        )
        download_url = item.get("download_url")
        if download_url:
            row = f"{row}\n  Download: {download_url}"
        return row

    def _build_html_download_cards(self, line_items: Sequence[dict], currency: str) -> str:
        if not line_items:
            return (
                '<table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%; border-radius: 10px; overflow: hidden; border: 1px solid #e5e7eb;">'
                '<tr><td style="background: #f9fafb; padding: 18px 20px; font-size: 14px; color: #333333;">Digital photo purchase</td></tr>'
                "</table>"
            )

        return "\n".join(
            self._build_html_download_card(item, index, currency)
            for index, item in enumerate(line_items, start=1)
        )

    def _build_html_download_card(self, item: dict, index: int, currency: str) -> str:
        item_name = html.escape(str(item.get("name") or "Photo"))
        reference = html.escape(str(item.get("reference") or f"Photo #{index}"))
        quality = html.escape(str(item.get("quality") or "Full resolution"))
        amount = self._format_amount(int(item.get("total_amount") or 0), currency)
        thumbnail_url = item.get("thumbnail_url")
        thumbnail = '<div style="width: 52px; height: 52px; border-radius: 14px; background: #c8cdd8; color: #ffffff; display: inline-block; line-height: 52px; font-size: 24px;">&#8595;</div>'
        if thumbnail_url:
            safe_thumbnail_url = html.escape(str(thumbnail_url), quote=True)
            thumbnail = (
                f'<img src="{safe_thumbnail_url}" alt="{item_name}" width="100%" '
                'style="display: block; width: 100%; height: 220px; object-fit: cover; border: 0;" />'
            )
        download_url = item.get("download_url")
        action = '<span style="display: block; background: #9ca3af; color: #ffffff; text-align: center; padding: 11px; border-radius: 7px; font-size: 13px; font-weight: 700;">Photo link unavailable</span>'
        if download_url:
            safe_url = html.escape(str(download_url), quote=True)
            action = (
                f'<a href="{safe_url}" style="display: block; background: #1b3aec; color: #ffffff; text-decoration: none; '
                'text-align: center; padding: 11px; border-radius: 7px; font-size: 13px; font-weight: 700;">Download Photo</a>'
            )

        return f"""\
<table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%; border-radius: 10px; overflow: hidden; border: 1px solid #e5e7eb; margin-bottom: 16px;">
  <tr>
    <td style="height: 220px; background: #e8eaed; text-align: center; vertical-align: middle;">
      {thumbnail}
    </td>
  </tr>
  <tr>
    <td style="background: #f9fafb; padding: 15px 16px 16px; border-top: 1px solid #eeeeee;">
      <p style="margin: 0 0 10px; font-size: 14px; line-height: 20px; font-weight: 700; color: #111111;">{item_name}</p>
      <table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%;">
        <tr>
          <td style="font-size: 12px; color: #aaaaaa; padding: 3px 0;">Reference</td>
          <td align="right" style="font-size: 12px; color: #333333; padding: 3px 0; font-weight: 700;">{reference}</td>
        </tr>
        <tr>
          <td style="font-size: 12px; color: #aaaaaa; padding: 3px 0;">Quality</td>
          <td align="right" style="font-size: 12px; color: #333333; padding: 3px 0;">{quality}</td>
        </tr>
        <tr>
          <td style="font-size: 12px; color: #aaaaaa; padding: 3px 0;">Amount</td>
          <td align="right" style="font-size: 12px; color: #333333; padding: 3px 0;">{amount}</td>
        </tr>
      </table>
      <div style="margin-top: 14px;">{action}</div>
    </td>
  </tr>
</table>
"""

    def _format_amount(self, amount: int, currency: str) -> str:
        return f"{amount / 100:.2f} {currency.upper()}"
