"""Subscribe a tiny local receiver, create a payment and verify the signed delivery Relay sends.

The receiver is standard library only. Relay posts from its own container, so the URL it is given must name a host
on its allowlist (WEBHOOK_ALLOWED_HOSTS): the default `host.docker.internal` is not on it, so start the stack with
that name added, for example

    WEBHOOK_ALLOWED_HOSTS=webhook-sink,localhost,127.0.0.1,host.docker.internal docker compose up -d --wait

and run this script on the host (RELAY_API_URL defaults to http://127.0.0.1:8000). Environment:
RELAY_API_KEY (required), RELAY_API_URL, WEBHOOK_RECEIVER_HOST (how Relay reaches this machine, default
host.docker.internal), WEBHOOK_RECEIVER_PORT (default 9009), WEBHOOK_RECEIVER_BIND (default 127.0.0.1; use 0.0.0.0
when the container cannot reach a loopback-only listener).
"""

import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from relay_sdk import RelayClient, RelayError, SignatureVerificationError, parse_event, verify_signature

Message = tuple[str, bytes]


def make_receiver(inbox: "queue.Queue[Message]") -> type[BaseHTTPRequestHandler]:
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - the http.server naming
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            inbox.put((self.headers.get("Relay-Signature", ""), body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return None

    return Receiver


def main() -> int:
    api_key = os.environ.get("RELAY_API_KEY")
    if not api_key:
        print("Set RELAY_API_KEY to the key the stack runs with.", file=sys.stderr)
        return 2
    url = os.environ.get("RELAY_API_URL", "http://127.0.0.1:8000")
    host = os.environ.get("WEBHOOK_RECEIVER_HOST", "host.docker.internal")
    port = int(os.environ.get("WEBHOOK_RECEIVER_PORT", "9009"))
    bind = os.environ.get("WEBHOOK_RECEIVER_BIND", "127.0.0.1")

    inbox: queue.Queue[Message] = queue.Queue()
    server = HTTPServer((bind, port), make_receiver(inbox))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with RelayClient(url, api_key) as client:
        subscription = None
        try:
            subscription = client.create_subscription(f"http://{host}:{port}/hook", ["payment.final"])
            print(f"subscribed {subscription.id} to {subscription.url}")
            created = client.create_payment(2500, "EUR", reference="sdk-webhook-example")
            print(f"created payment {created.payment.id}; waiting for its payment.final delivery")
            while True:
                try:
                    signature, body = inbox.get(timeout=30)
                except queue.Empty:
                    print("No delivery within 30 seconds: check the allowlist and that Relay can reach this host.")
                    return 1
                try:
                    verify_signature(subscription.secret, signature, body)
                except SignatureVerificationError as error:
                    print(f"REJECTED: {error.reason}")
                    return 1
                event = parse_event(body)
                print(f"verified event {event.id} {event.type}: {event.data}")
                if event.data.get("payment_id") == created.payment.id:
                    print("VERIFIED the signed delivery for our payment")
                    return 0
        except RelayError as error:
            print(f"Relay answered with an error: {error}", file=sys.stderr)
            return 1
        finally:
            if subscription is not None:
                client.delete_subscription(subscription.id)
            server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
