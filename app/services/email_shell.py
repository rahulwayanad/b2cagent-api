"""Wraps a per-template HTML body in the shared B2C Tour Agent email shell.

Templates store just the *inner* HTML (paragraphs, highlight boxes, buttons).
At send time we paste it inside `wrap_email_html()` so the brand header,
subject treatment, and footer stay consistent across every mail."""
from __future__ import annotations

import html


BRAND = "B2C Tour Agent"
FOOTER_HTML = (
    f"&copy; 2026 {BRAND}. All rights reserved."
    "&nbsp;&middot;&nbsp;<a href=\"#\">Unsubscribe</a>"
    "&nbsp;&middot;&nbsp;<a href=\"#\">Privacy Policy</a>"
)


SHELL_STYLE = """
  body { margin:0; padding:0; background:#F6F4EF; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; color:#15201B; }
  .app { max-width:640px; margin:0 auto; padding:24px 16px; }
  .email-viewer { border:1px solid #EFEAE0; border-radius:14px; overflow:hidden; background:#fff; box-shadow:0 2px 8px rgba(20,30,25,0.06); }
  .brand-bar { background:#FCF5EE; padding:18px 28px; border-bottom:1px solid #EFEAE0; display:flex; align-items:center; gap:10px; }
  .brand-mark { width:28px; height:28px; border-radius:8px; background:#1F3A2E; color:#F6F4EF; display:inline-flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; letter-spacing:-0.02em; }
  .brand-name { font-size:14px; font-weight:600; color:#15201B; letter-spacing:-0.005em; }
  .brand-eyebrow { margin-left:auto; font-size:10.5px; font-weight:600; letter-spacing:0.14em; text-transform:uppercase; color:#8A847B; }
  .email-body { background:#fff; padding:28px; font-size:14px; line-height:1.75; color:#15201B; }
  .email-body p { margin:0 0 14px 0; }
  .btn-link { display:inline-block; padding:10px 22px; border-radius:8px; background:#1F3A2E; color:#fff !important; font-weight:500; font-size:13px; text-decoration:none; margin:6px 0 16px; }
  .btn-outline { display:inline-block; padding:8px 18px; border-radius:8px; background:#fff; color:#15201B !important; font-weight:500; font-size:13px; text-decoration:none; margin:4px 0; border:1px solid #E5DFD2; }
  .section-divider { border:none; border-top:1px solid #EFEAE0; margin:20px 0; }
  .highlight-box { background:#FAF8F3; border-left:3px solid #C9A875; padding:12px 16px; margin:14px 0; font-size:13px; color:#5B5750; line-height:1.7; border-radius:0 6px 6px 0; }
  table.order-table { width:100%; border-collapse:collapse; font-size:13px; margin:14px 0; }
  table.order-table th { background:#FAF8F3; text-align:left; padding:8px 12px; color:#5B5750; font-weight:600; border-bottom:1px solid #EFEAE0; }
  table.order-table td { padding:8px 12px; border-bottom:1px solid #EFEAE0; }
  table.order-table .total-row td { font-weight:600; background:#FAF8F3; }
  .coupon-box { text-align:center; border:1.5px dashed #E5DFD2; border-radius:12px; padding:22px 16px; margin:16px 0; background:#FAF8F3; }
  .coupon-label { font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:#8A847B; margin-bottom:8px; }
  .coupon-code { font-size:28px; font-weight:700; letter-spacing:0.14em; font-family:'Courier New',monospace; color:#15201B; }
  ul.checklist { padding-left:18px; margin:0 0 14px 0; color:#5B5750; font-size:13px; line-height:2.0; }
  .email-footer { background:#F6F4EF; border-top:1px solid #EFEAE0; padding:14px 28px; font-size:11px; color:#8A847B; line-height:1.7; text-align:center; }
  .email-footer a { color:#8A847B; }
"""


def wrap_email_html(
    *,
    subject: str,
    body_html: str,
    to: str,
    badge_label: str = "",
    badge_cls: str = "",
) -> str:
    """Build a full HTML document around the template's body fragment.

    `to`, `badge_label`, `badge_cls` are accepted for backwards compat with
    callers but no longer rendered — the new shell skips the fake email-client
    chrome (From/To/badge) because Gmail's own UI already shows that info.
    """
    del to, badge_label, badge_cls  # intentionally unused in the new shell
    safe_subject = html.escape(subject)
    safe_brand = html.escape(BRAND)
    initial = html.escape(BRAND[:1])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_subject}</title>
<style>{SHELL_STYLE}</style>
</head><body>
<div class="app">
  <div class="email-viewer">
    <div class="brand-bar">
      <span class="brand-mark">{initial}</span>
      <span class="brand-name">{safe_brand}</span>
    </div>
    <div class="email-body">{body_html}</div>
    <div class="email-footer">{FOOTER_HTML}</div>
  </div>
</div>
</body></html>"""
