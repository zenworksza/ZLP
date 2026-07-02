"""SMTP email service for invoice delivery."""
import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "billing@yourdomain.com")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Zen License Platform")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "ZAR")


def _format_amount(amount_cents: int, currency: str) -> str:
    return f"{currency} {amount_cents / 100:,.2f}"


def _smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def send_key_provisioning_email(
    *,
    to_email: str,
    license_key: str,
    product_name: str,
    plan_name: str,
    seats: int,
    expires_at: Optional[datetime] = None,
    renewal_period_days: Optional[int] = None,
) -> bool:
    """Send a welcome / key delivery email when a new license key is created."""
    if not _smtp_configured():
        logger.warning("SMTP not configured — provisioning email not sent to %s", to_email)
        return False

    period_label = {30: "monthly", 90: "quarterly", 180: "semi-annually"}.get(renewal_period_days or 0, "")
    expiry_str = expires_at.strftime("%d %B %Y") if expires_at else "No expiry set"
    renewal_note = (
        f"<p>Your license renews {period_label}. You will receive an invoice before each renewal date.</p>"
        if period_label else ""
    )
    renewal_note_text = (
        f"Your license renews {period_label}. You will receive an invoice before each renewal date.\n"
        if period_label else ""
    )

    subject = f"Your {product_name} license key"

    html = f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #1a1a1a; margin: 0; padding: 0; background: #f5f5f5; }}
  .wrapper {{ max-width: 600px; margin: 40px auto; background: #ffffff; border: 1px solid #e0e0e0; border-radius: 6px; overflow: hidden; }}
  .header {{ background: #1d4ed8; padding: 24px 32px; }}
  .header h1 {{ margin: 0; color: #ffffff; font-size: 20px; font-weight: 600; }}
  .header p {{ margin: 4px 0 0; color: #bfdbfe; font-size: 13px; }}
  .body {{ padding: 32px; }}
  .key-box {{ background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; padding: 20px 24px; margin: 24px 0; text-align: center; }}
  .key-box .label {{ font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
  .key-box .key {{ font-family: monospace; font-size: 22px; font-weight: 700; color: #1d4ed8; letter-spacing: 0.1em; }}
  .meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 20px 0; }}
  .meta-item {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 4px; padding: 12px 14px; }}
  .meta-item .label {{ font-size: 11px; color: #9ca3af; text-transform: uppercase; }}
  .meta-item .value {{ font-size: 14px; font-weight: 600; color: #111827; margin-top: 2px; }}
  p {{ font-size: 14px; line-height: 1.6; color: #374151; }}
  .footer {{ padding: 20px 32px; background: #f9fafb; border-top: 1px solid #e5e7eb; font-size: 12px; color: #9ca3af; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Your License Key</h1>
    <p>{SMTP_FROM_NAME}</p>
  </div>
  <div class="body">
    <p>Thank you for your purchase. Your <strong>{product_name}</strong> license key is ready.</p>

    <div class="key-box">
      <div class="label">License Key</div>
      <div class="key">{license_key}</div>
    </div>

    <div class="meta">
      <div class="meta-item">
        <div class="label">Product</div>
        <div class="value">{product_name}</div>
      </div>
      <div class="meta-item">
        <div class="label">Plan</div>
        <div class="value">{plan_name}</div>
      </div>
      <div class="meta-item">
        <div class="label">Seats</div>
        <div class="value">{seats}</div>
      </div>
      <div class="meta-item">
        <div class="label">Valid until</div>
        <div class="value">{expiry_str}</div>
      </div>
    </div>

    {renewal_note}
    <p>Keep this key safe — you will need it during installation. Reply to this email if you need help.</p>
  </div>
  <div class="footer">
    <p>This email was sent by {SMTP_FROM_NAME}. Do not share your license key.</p>
  </div>
</div>
</body>
</html>"""

    text = (
        f"YOUR {product_name.upper()} LICENSE KEY\n"
        f"{'=' * 40}\n"
        f"License key: {license_key}\n"
        f"Product:     {product_name} ({plan_name} plan)\n"
        f"Seats:       {seats}\n"
        f"Valid until: {expiry_str}\n\n"
        f"{renewal_note_text}"
        f"Keep this key safe — you will need it during installation.\n"
        f"Reply to this email if you need help.\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        logger.info("Provisioning email sent to %s for key %s", to_email, license_key)
        return True
    except Exception as exc:
        logger.error("Failed to send provisioning email to %s: %s", to_email, exc)
        return False


def send_renewal_confirmation_email(
    *,
    to_email: str,
    invoice_number: str,
    license_key: str,
    product_name: str,
    plan_name: str,
    new_expires_at: datetime,
    amount_cents: int,
    currency: str,
) -> bool:
    """Send a payment confirmation / renewal email after an invoice is marked paid."""
    if not _smtp_configured():
        logger.warning("SMTP not configured — renewal confirmation not sent to %s", to_email)
        return False

    expiry_str = new_expires_at.strftime("%d %B %Y")
    amount_str = _format_amount(amount_cents, currency)
    subject = f"Payment received — {product_name} license renewed until {expiry_str}"

    html = f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #1a1a1a; margin: 0; padding: 0; background: #f5f5f5; }}
  .wrapper {{ max-width: 600px; margin: 40px auto; background: #ffffff; border: 1px solid #e0e0e0; border-radius: 6px; overflow: hidden; }}
  .header {{ background: #16a34a; padding: 24px 32px; }}
  .header h1 {{ margin: 0; color: #ffffff; font-size: 20px; font-weight: 600; }}
  .header p {{ margin: 4px 0 0; color: #bbf7d0; font-size: 13px; }}
  .body {{ padding: 32px; }}
  .confirm-box {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: 6px; padding: 20px 24px; margin: 24px 0; }}
  .confirm-box .label {{ font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
  .confirm-box .value {{ font-size: 18px; font-weight: 700; color: #15803d; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
  td {{ padding: 8px 0; font-size: 14px; border-bottom: 1px solid #f3f4f6; }}
  td:first-child {{ color: #6b7280; }}
  td:last-child {{ font-weight: 500; text-align: right; }}
  p {{ font-size: 14px; line-height: 1.6; color: #374151; }}
  .footer {{ padding: 20px 32px; background: #f9fafb; border-top: 1px solid #e5e7eb; font-size: 12px; color: #9ca3af; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Payment Received</h1>
    <p>{SMTP_FROM_NAME}</p>
  </div>
  <div class="body">
    <p>Thank you — your payment has been received and your <strong>{product_name}</strong> license has been renewed.</p>

    <div class="confirm-box">
      <div class="label">License active until</div>
      <div class="value">{expiry_str}</div>
    </div>

    <table>
      <tr><td>Invoice</td><td>{invoice_number}</td></tr>
      <tr><td>License key</td><td style="font-family:monospace">{license_key}</td></tr>
      <tr><td>Product</td><td>{product_name} — {plan_name}</td></tr>
      <tr><td>Amount paid</td><td>{amount_str}</td></tr>
    </table>

    <p>No action is required. Your license will continue to work without interruption. Reply to this email if you have any questions.</p>
  </div>
  <div class="footer">
    <p>This email was sent by {SMTP_FROM_NAME}.</p>
  </div>
</div>
</body>
</html>"""

    text = (
        f"PAYMENT RECEIVED — LICENSE RENEWED\n"
        f"{'=' * 40}\n"
        f"Invoice:       {invoice_number}\n"
        f"License key:   {license_key}\n"
        f"Product:       {product_name} ({plan_name} plan)\n"
        f"Amount paid:   {amount_str}\n"
        f"Active until:  {expiry_str}\n\n"
        f"No action required. Your license will continue to work.\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        logger.info("Renewal confirmation sent to %s for invoice %s", to_email, invoice_number)
        return True
    except Exception as exc:
        logger.error("Failed to send renewal confirmation to %s: %s", to_email, exc)
        return False


def send_invoice_email(
    *,
    to_email: str,
    invoice_number: str,
    license_key: str,
    product_name: str,
    plan_name: str,
    period_days: int,
    period_start: datetime,
    period_end: datetime,
    amount_cents: int,
    currency: str,
    due_date: datetime,
) -> bool:
    """Send an invoice email. Returns True if sent, False if SMTP not configured."""
    if not _smtp_configured():
        logger.warning("SMTP not configured — invoice %s not emailed to %s", invoice_number, to_email)
        return False

    period_label = {30: "Monthly", 90: "Quarterly", 180: "Semi-annual"}.get(period_days, f"{period_days}-day")
    amount_str = _format_amount(amount_cents, currency)
    due_str = due_date.strftime("%d %B %Y")
    start_str = period_start.strftime("%d %B %Y")
    end_str = period_end.strftime("%d %B %Y")

    subject = f"Invoice {invoice_number} — {product_name} license renewal"

    html = f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #1a1a1a; margin: 0; padding: 0; background: #f5f5f5; }}
  .wrapper {{ max-width: 600px; margin: 40px auto; background: #ffffff; border: 1px solid #e0e0e0; border-radius: 6px; overflow: hidden; }}
  .header {{ background: #1d4ed8; padding: 24px 32px; }}
  .header h1 {{ margin: 0; color: #ffffff; font-size: 20px; font-weight: 600; }}
  .header p {{ margin: 4px 0 0; color: #bfdbfe; font-size: 13px; }}
  .body {{ padding: 32px; }}
  .invoice-meta {{ display: flex; justify-content: space-between; margin-bottom: 28px; }}
  .meta-block p {{ margin: 2px 0; font-size: 13px; color: #6b7280; }}
  .meta-block strong {{ color: #111827; }}
  table {{ width: 100%; border-collapse: collapse; margin: 24px 0; }}
  th {{ background: #f9fafb; text-align: left; padding: 10px 12px; font-size: 12px; font-weight: 600; color: #6b7280; text-transform: uppercase; border-bottom: 1px solid #e5e7eb; }}
  td {{ padding: 12px; font-size: 14px; border-bottom: 1px solid #f3f4f6; }}
  .amount-row td {{ font-weight: 600; font-size: 16px; color: #111827; background: #f9fafb; }}
  .due-box {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 4px; padding: 14px 16px; margin-top: 20px; }}
  .due-box p {{ margin: 0; font-size: 14px; color: #1d4ed8; }}
  .due-box strong {{ font-size: 16px; }}
  .footer {{ padding: 20px 32px; background: #f9fafb; border-top: 1px solid #e5e7eb; font-size: 12px; color: #9ca3af; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Tax Invoice</h1>
    <p>{SMTP_FROM_NAME}</p>
  </div>
  <div class="body">
    <table style="margin-bottom:0">
      <tr>
        <td style="padding:0 0 4px; font-size:13px; color:#6b7280; border:none">Invoice number</td>
        <td style="padding:0 0 4px; font-size:13px; font-weight:600; border:none; text-align:right">{invoice_number}</td>
      </tr>
      <tr>
        <td style="padding:0 0 4px; font-size:13px; color:#6b7280; border:none">License key</td>
        <td style="padding:0 0 4px; font-size:13px; font-family:monospace; border:none; text-align:right">{license_key}</td>
      </tr>
      <tr>
        <td style="padding:0; font-size:13px; color:#6b7280; border:none">Billing period</td>
        <td style="padding:0; font-size:13px; border:none; text-align:right">{start_str} – {end_str}</td>
      </tr>
    </table>

    <table>
      <thead>
        <tr>
          <th>Description</th>
          <th style="text-align:right">Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <strong>{product_name}</strong> — {plan_name} plan<br>
            <span style="color:#6b7280; font-size:12px">{period_label} license renewal · {start_str} to {end_str}</span>
          </td>
          <td style="text-align:right">{amount_str}</td>
        </tr>
        <tr class="amount-row">
          <td>Total due</td>
          <td style="text-align:right">{amount_str}</td>
        </tr>
      </tbody>
    </table>

    <div class="due-box">
      <p>Payment due by <strong>{due_str}</strong></p>
      <p style="margin-top:6px; color:#374151; font-size:13px">
        Reply to this email or contact us to arrange payment. Late payment will result in your license being suspended.
      </p>
    </div>
  </div>
  <div class="footer">
    <p>This invoice was generated automatically by {SMTP_FROM_NAME}. If you have questions, reply to this email.</p>
  </div>
</div>
</body>
</html>"""

    text = (
        f"INVOICE {invoice_number}\n"
        f"{'=' * 40}\n"
        f"Product:        {product_name} ({plan_name} plan)\n"
        f"License key:    {license_key}\n"
        f"Period:         {start_str} – {end_str} ({period_label})\n"
        f"Amount due:     {amount_str}\n"
        f"Payment due by: {due_str}\n\n"
        f"Reply to this email or contact us to arrange payment.\n"
        f"Late payment will result in your license being suspended.\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
    msg["To"] = to_email
    msg["X-Invoice-Number"] = invoice_number
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        logger.info("Invoice %s sent to %s", invoice_number, to_email)
        return True
    except Exception as exc:
        logger.error("Failed to send invoice %s to %s: %s", invoice_number, to_email, exc)
        return False
