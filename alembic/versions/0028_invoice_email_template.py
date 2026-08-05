"""seed `invoice_issued` email template (customer copy of the invoice)

Revision ID: 0028_invoice_email
Revises: 0027_bid_payment_invoice
Create Date: 2026-05-24 23:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0028_invoice_email"
down_revision: Union[str, Sequence[str], None] = "0027_bid_payment_invoice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CODE = "invoice_issued"
SUBJECT = "Invoice {invoice_no} for your stay at {property_name}"
BODY = (
    "<p>Hi {customer_name},</p>"
    "<p>Your invoice <strong>{invoice_no}</strong> for <strong>{property_name}</strong> is ready.</p>"
    "<div class=\"highlight-box\">"
    "<p><strong>Stay:</strong> {check_in} → {check_out} ({nights} night/s)</p>"
    "<p><strong>Rate:</strong> ₹{rate_per_night}/night</p>"
    "<p><strong>Total:</strong> ₹{amount_total}</p>"
    "<p><strong>Payment method:</strong> Cash on Delivery — collected at check-in.</p>"
    "</div>"
    "<p style=\"color:#5B5750;font-size:13px;\">"
    "<strong>Billed by:</strong> {manager_name}<br>"
    "{manager_business_location}<br>"
    "✉️ {manager_email} · ☎️ {manager_phone}"
    "</p>"
    "<p><a class=\"btn-link\" href=\"{link_url}\">View invoice &rarr;</a></p>"
    "<p style=\"color:#5B5750\">If anything looks off, reply to this email or call the property directly.</p>"
    "<p style=\"color:#5B5750\">— The B2C Tour Agent team</p>"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO email_templates "
            "(id, code, name, subject, body, is_active, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :code, :name, :subject, :body, true, now(), now()) "
            "ON CONFLICT (code) DO UPDATE SET "
            "subject = EXCLUDED.subject, body = EXCLUDED.body, updated_at = now()"
        ).bindparams(code=CODE, name="Invoice issued", subject=SUBJECT, body=BODY)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM email_templates WHERE code = :code").bindparams(
            code=CODE
        )
    )
