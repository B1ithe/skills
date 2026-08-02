---
name: hero-sms
description: Integrate and operate Hero SMS virtual-number, OTP activation, rental, email activation, and incoming-SMS webhook APIs. Use when an agent needs to write or debug a Hero SMS client, use its SMS-Activate-compatible protocol, inspect prices or availability, purchase and manage an activation, poll for a verification message, configure webhooks, or migrate an SMS-Activate integration to Hero SMS.
---

# Hero SMS

Use Hero SMS through its documented API surfaces while keeping credentials and paid activation state under explicit control.

## Route the request

- For OTP numbers, activation state, catalog data, rentals, or SMS-Activate compatibility, read [references/activation-api.md](references/activation-api.md).
- For email activation or incoming-SMS webhooks, read [references/email-webhooks.md](references/email-webhooks.md).
- For direct shell operation, resolve the skill directory and inspect `python3 <skill-directory>/scripts/hero_sms.py --help`, then use the relevant subcommand.
- For application integration, implement the protocol in the user's existing language and HTTP stack; do not force the bundled Python CLI into the application.

## Guard credentials and external effects

1. Read the API key from `HERO_SMS_API_KEY`. Do not place it in source code, command arguments, URLs shown to the user, logs, fixtures, or committed files.
2. Treat number acquisition, email acquisition, reactivation, prolonging, status changes, completion, and cancellation as external mutations. Execute them only when the user's request authorizes that specific effect.
3. Show the selected service, country, operator constraints, maximum price, and operation before a paid acquisition when any of them were inferred rather than supplied.
4. Use Hero SMS only for lawful verification flows that the user is authorized to perform. Do not help evade a platform's rules, create deceptive accounts, intercept another person's messages, or conduct spam, phishing, or fraud.

The bundled CLI requires `--yes` for every mutating command. Preserve an equivalent confirmation boundary in generated automation unless the user explicitly requests unattended execution.

## Choose the API surface

- Prefer the SMS-Activate-compatible handler for the activation lifecycle and for drop-in migrations: `https://hero-sms.com/stubs/handler_api.php`.
- Prefer `GET /api/v1/activations/offers` for current grouped availability and prices. The legacy top-country methods are deprecated.
- Use `https://hero-sms.com/api/v1` for email activation and offers. Authenticate these REST calls with `Authorization: ApiKey <key>`.
- Authenticate compatibility-handler calls with the `api_key` query parameter. Prevent HTTP clients and observability systems from logging complete query strings.

Do not silently mix response parsers: compatibility actions can return plain text or JSON, while REST endpoints return JSON or an empty `204` response.

## Run an OTP activation

1. Resolve current country IDs and service codes instead of guessing them. Check price and availability before acquisition when the user supplied a budget or when cost matters.
2. Acquire with `getNumberV2` when structured activation metadata is useful; use `getNumber` only when compatibility with its plain-text result is required. Retain the activation ID independently of the phone number.
3. Deliver the number only to the authorized verification flow. Never expose the API key with it.
4. Receive the message through a configured webhook or poll `getStatus`/`getStatusV2` at a bounded interval. Stay below the account's rate limit, apply backoff to throttling, and stop at the user's deadline or the activation end time.
5. Parse success by response shape and documented status value, not by HTTP `200` alone. A compatibility response may carry a business status in the body.
6. After the code is accepted, complete the activation. If no code arrives and cancellation is still allowed, cancel only when authorized. Do not abandon purchased activations without reporting their final known state.

The run is complete only when the activation ID, returned result or terminal status, and any authorized finalization are accounted for without leaking the key.

## Implement resilient clients

- Set a finite HTTP timeout. Retry only transient transport errors, `429`, and appropriate `5xx` responses with bounded exponential backoff and jitter.
- Do not retry purchase or lifecycle mutations blindly. Reconcile with `getActiveActivations`, `getStatus`, or history after an ambiguous timeout before issuing another mutation.
- Treat `401/403` as configuration or authorization failures, `402` as insufficient funds, `404` according to the operation, `409` as an invalid lifecycle transition, and `422` as invalid input.
- Preserve the structured error fields `title`, `details`, and `info` when present. Include the activation ID in operational logs, but redact phone numbers, message text, verification codes, and credentials by default.
- Make webhook consumers idempotent by activation ID and message identity. Return `200` promptly after durable acceptance, then process asynchronously.

## Verify deliverables

- For code changes, test parsers with representative plain-text, JSON, error-envelope, and empty-`204` fixtures.
- For live read-only checks, use balance, catalog, prices, offers, or status commands first.
- For live mutations, report the exact successful operation and resulting activation/email ID. On failure, report the HTTP status plus sanitized business error and leave the external state explicit.
- Recheck the [official API documentation](https://hero-sms.com/cn/api) before depending on an endpoint or field not covered by the bundled references.
