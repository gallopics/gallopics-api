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
            "subject": f"Your Gallopics purchase receipt {order_id}",
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
        rows = "\n".join(
            "<tr>"
            f"<td>{self._build_html_item_name(item)}</td>"
            f"<td align=\"center\">{int(item.get('quantity') or 1)}</td>"
            f"<td align=\"right\">{self._format_amount(int(item.get('total_amount') or 0), currency)}</td>"
            "</tr>"
            for item in line_items
        )
        if not rows:
            rows = '<tr><td>Digital photo purchase</td><td align="center">1</td><td align="right"></td></tr>'

        return f"""\
<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; color: #111827;">
    <h1 style="font-size: 20px;">Gallopics purchase receipt</h1>
    <p>Thank you for your purchase.</p>
    <p><strong>Order:</strong> {html.escape(order_id)}</p>
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
      <thead>
        <tr>
          <th align="left">Item</th>
          <th align="center">Qty</th>
          <th align="right">Amount</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
      <tfoot>
        <tr>
          <td colspan="2" align="right"><strong>Total</strong></td>
          <td align="right"><strong>{self._format_amount(amount, currency)}</strong></td>
        </tr>
      </tfoot>
    </table>
    <p>Your purchased photos are available from the download links in this email and after checkout.</p>
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

    def _build_html_item_name(self, item: dict) -> str:
        item_name = html.escape(str(item.get("name") or "Photo"))
        download_url = item.get("download_url")
        if not download_url:
            return item_name

        safe_url = html.escape(str(download_url), quote=True)
        return (
            f"{item_name}<br>"
            f"<a href=\"{safe_url}\" style=\"color: #ea580c;\">Download photo</a>"
        )

    def _format_amount(self, amount: int, currency: str) -> str:
        return f"{amount / 100:.2f} {currency.upper()}"
