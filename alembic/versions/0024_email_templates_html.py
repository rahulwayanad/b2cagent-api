"""switch seeded email templates to HTML bodies (B2CAgent brand shell)

Revision ID: 0024_email_html
Revises: 0023_email_templates
Create Date: 2026-05-24 01:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0024_email_html"
down_revision: Union[str, Sequence[str], None] = "0023_email_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Each entry overwrites the seeded body with an HTML fragment that goes inside
# the brand shell. Subjects keep {placeholders} as-is.
HTML_BODIES: dict[str, str] = {
    "otp": (
        "<p>Hi {name},</p>"
        "<p>Use this verification code to finish signing in. It expires in 5 minutes.</p>"
        "<div class=\"coupon-box\">"
        "<div class=\"coupon-label\">Your code</div>"
        "<div class=\"coupon-code\">{otp}</div>"
        "</div>"
        "<p style=\"font-size:12px;color:#888\">If you didn't request this, you can safely ignore this email.</p>"
        "<p style=\"color:#555\">— The B2CAgent team</p>"
    ),
    "welcome": (
        "<p>Hi {name},</p>"
        "<p>Welcome to <strong>B2CAgent</strong> — your account is now active as a <strong>{role}</strong>.</p>"
        "<p>Here's how to get going:</p>"
        "<ul class=\"checklist\">"
        "<li>Complete your profile and add a photo</li>"
        "<li>Start {role_action}</li>"
        "<li>Reach out to the team any time from your inbox</li>"
        "</ul>"
        "<a class=\"btn-link\" href=\"#\">Open my dashboard &rarr;</a>"
        "<hr class=\"section-divider\">"
        "<p style=\"color:#555\">Glad to have you on board,<br><strong>The B2CAgent team</strong></p>"
    ),
    "bid_placed_agent": (
        "<p>Hi {agent_name},</p>"
        "<p>Your bid has been recorded — we'll notify you the moment the property manager responds.</p>"
        "<div class=\"highlight-box\">"
        "<strong>Property:</strong> {property_name}<br>"
        "<strong>Stay:</strong> {check_in} → {check_out}<br>"
        "<strong>Bid:</strong> {amount}/night"
        "</div>"
        "<a class=\"btn-link\" href=\"#\">View your bids &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "bid_placed_manager": (
        "<p>Hi {manager_name},</p>"
        "<p>A new bid landed on one of your properties.</p>"
        "<div class=\"highlight-box\">"
        "<strong>Property:</strong> {property_name}<br>"
        "<strong>Agent:</strong> {agent_name}<br>"
        "<strong>Stay:</strong> {check_in} → {check_out}<br>"
        "<strong>Bid:</strong> {amount}/night"
        "</div>"
        "<a class=\"btn-link\" href=\"#\">Review the bid &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "bid_accepted": (
        "<p>Hi {agent_name},</p>"
        "<p>Great news — your bid was <strong>accepted</strong>. Collect payment from your customer to lock in the booking.</p>"
        "<div class=\"highlight-box\">"
        "<strong>Property:</strong> {property_name}<br>"
        "<strong>Stay:</strong> {check_in} → {check_out}<br>"
        "<strong>Bid:</strong> {amount}/night"
        "</div>"
        "<a class=\"btn-link\" href=\"#\">Open the bid &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "bid_rejected": (
        "<p>Hi {agent_name},</p>"
        "<p>Your bid for <strong>{property_name}</strong> ({check_in} → {check_out}) was declined. The customer is still active — try a different property.</p>"
        "<a class=\"btn-link\" href=\"#\">Browse properties &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "bid_held": (
        "<p>Hi {agent_name},</p>"
        "<p>Your bid on <strong>{property_name}</strong> is on hold — another overlapping bid was accepted. We'll reactivate yours automatically if that one falls through.</p>"
        "<a class=\"btn-link\" href=\"#\">See bid status &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "bid_withdrawn": (
        "<p>Hi {manager_name},</p>"
        "<p>{agent_name} withdrew their bid on <strong>{property_name}</strong> for {check_in} → {check_out}.</p>"
        "<a class=\"btn-link\" href=\"#\">Open the property &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "booking_confirmed": (
        "<p>Hi {agent_name},</p>"
        "<p>Payment is confirmed and the booking is <strong>locked in</strong>. The full details are in your dashboard.</p>"
        "<div class=\"highlight-box\">"
        "<strong>Property:</strong> {property_name}<br>"
        "<strong>Stay:</strong> {check_in} → {check_out}"
        "</div>"
        "<a class=\"btn-link\" href=\"#\">View booking &rarr;</a>"
        "<p style=\"color:#555\">Thanks for closing it with B2CAgent,<br><strong>— The B2CAgent team</strong></p>"
    ),
    "profile_updated": (
        "<p>Hi {name},</p>"
        "<p>Your profile was just updated. If this wasn't you, secure your account from the profile page.</p>"
        "<a class=\"btn-link\" href=\"#\">Review profile &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "subscription_limit_warning": (
        "<p>Hi {name},</p>"
        "<p>You've used <strong>{used}</strong> of <strong>{limit}</strong> {basis} this month on the <strong>{plan_name}</strong> plan. Upgrade now to keep things moving without interruption.</p>"
        "<a class=\"btn-link\" href=\"#\">Upgrade plan &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
    "subscription_upgraded": (
        "<p>Hi {name},</p>"
        "<p>Your subscription is now <strong>{plan_name}</strong>. You're set with {bid_limit} bids/month and {property_limit} properties.</p>"
        "<a class=\"btn-link\" href=\"#\">Open dashboard &rarr;</a>"
        "<p style=\"color:#555\">— B2CAgent</p>"
    ),
}


def upgrade() -> None:
    for code, body in HTML_BODIES.items():
        op.execute(
            sa.text(
                "UPDATE email_templates SET body = :body, updated_at = now() "
                "WHERE code = :code"
            ).bindparams(code=code, body=body)
        )


def downgrade() -> None:
    # No reversal — earlier seed bodies are still in version control (0023).
    pass
