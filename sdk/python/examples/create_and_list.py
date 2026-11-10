"""Create a payment, wait for its final state, then list the most recent payments.

Needs the local stack (`docker compose up -d --wait`). Reads RELAY_API_URL (default http://127.0.0.1:8000) and
RELAY_API_KEY from the environment.
"""

import os
import sys
import time

from relay_sdk import Payment, RelayClient, RelayError


def wait_until_final(client: RelayClient, payment_id: str, timeout_seconds: float = 60.0) -> Payment:
    deadline = time.monotonic() + timeout_seconds
    while True:
        payment = client.get_payment(payment_id)
        if payment.is_final or time.monotonic() > deadline:
            return payment
        time.sleep(1)


def main() -> int:
    url = os.environ.get("RELAY_API_URL", "http://127.0.0.1:8000")
    api_key = os.environ.get("RELAY_API_KEY")
    if not api_key:
        print("Set RELAY_API_KEY to the key the stack runs with.", file=sys.stderr)
        return 2
    with RelayClient(url, api_key) as client:
        try:
            created = client.create_payment(1999, "USD", description="SDK example", reference="sdk-example")
            print(f"created {created.payment.id} ({created.payment.display_status}), replayed={created.replayed}")
            payment = wait_until_final(client, created.payment.id)
            print(f"final state: {payment.display_status} on processor {payment.processor}")
            for event in payment.events:
                print(f"  {event.seq:>2} {event.type} {event.reason or ''}".rstrip())
            print("most recent payments:")
            page = client.list_payments(limit=5)
            for item in page.items:
                print(f"  {item.id} {item.amount_minor} {item.currency} {item.display_status}")
        except RelayError as error:
            print(f"Relay answered with an error: {error}", file=sys.stderr)
            return 1
    return 0 if payment.is_final else 1


if __name__ == "__main__":
    sys.exit(main())
