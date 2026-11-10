"""The event types a subscriber may choose (ADR-0015, item 6): the payment lifecycle only, never internal events."""

WEBHOOK_EVENT_TYPES = (
    "payment.received",
    "payment.authorized",
    "payment.captured",
    "payment.declined",
    "payment.failed",
    "payment.final",
)
DELIVERY_STATUSES = ("pending", "delivered", "failed")
MAX_ATTEMPTS = 8  # ADR-0015: at most 8 attempts, then `failed`
