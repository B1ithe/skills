# Hero SMS email activation and webhooks

Official source: [Hero SMS API reference](https://hero-sms.com/cn/api). Verified against the rendered official documentation on 2026-08-02.

## REST authentication

Use base URL `https://hero-sms.com/api/v1` and header:

```http
Authorization: ApiKey <HERO_SMS_API_KEY>
```

Send JSON request bodies with `Content-Type: application/json`. Successful JSON responses use a top-level `data` field; deletion returns HTTP `204` with no body. Error responses can include `401`, `404`, `422`, and `500` depending on the operation.

## Email activation endpoints

| Method and path | Input | Successful result |
| --- | --- | --- |
| `GET /emails` | Optional `search`, `size`, `page`, `sort[id]`, `status[id]`, `from`, `to` | Active purchases in `data` |
| `POST /emails` | JSON: required `site`, `domain` | HTTP `201`, purchased activation in `data` |
| `POST /emails/batch` | JSON: required `site`, `domain`, `count`; optional `service` | HTTP `201`, purchases in `data` and summary in `meta` |
| `GET /emails/{emailId}` | Email activation ID | Current activation in `data` |
| `DELETE /emails/{emailId}` | Email activation ID | HTTP `204`, no body |
| `POST /emails/{emailId}/reorder` | Email activation ID | Replacement/reordered activation in `data` |
| `GET /emails/domains` | Required `site` | Available domains with `name`, `cost`, `count`; omitting `site` returns `422`. |

Batch `count` must be from 1 through 10. The optional batch `service` code is 2–4 characters.

An email activation object shown by the official schema contains `id`, `site`, `email`, `status`, `value`, `cost`, `currency`, `date`, and `message`. Treat `value` and `message` as sensitive verification content. List filters use ISO 8601 UTC timestamps for `from` and `to`. Documented status-filter IDs are `3`, `4`, `5`, `6`, and `7`; discover their current semantic mapping from returned objects or the current official schema rather than guessing labels.

Example acquisition body:

```json
{
  "site": "telegram.com",
  "domain": "gmail.com"
}
```

Check domains and cost before purchase when the domain or budget was not fixed by the caller.

## Incoming SMS webhook

Hero SMS sends `POST` requests with `Content-Type: application/json` to each webhook URL configured in the account profile. Up to three webhook URLs are supported.

Example payload:

```json
{
  "activationId": "123456",
  "service": "tg",
  "text": "Your code is 12345",
  "code": "12345",
  "country": 2,
  "receivedAt": "2025-12-16T10:30:00.000000Z"
}
```

Field contract:

- `activationId`: required string;
- `service`: required 2–4 character service code;
- `country`: required integer from 0 through 999;
- `receivedAt`: required ISO 8601 date-time;
- `text`: required but nullable string;
- `code`: optional nullable string.

Respond with HTTP `200` within three seconds after durable acceptance, even when the message was already processed. A non-`200` response is considered unsuccessful. The official documentation states at least seven retries, 20–30 seconds apart, over at least three minutes.

Build the receiver as an idempotent ingestion boundary:

1. Validate content type, body size, schema, and timestamp syntax.
2. Correlate `activationId` with a locally known active purchase; do not trust payload content by itself.
3. Deduplicate on a stable local message identity derived from activation ID plus received time/content.
4. Persist or enqueue before returning `200`; perform slow downstream work afterward.
5. Redact `text` and `code` from normal logs.

The official page currently lists webhook source IPs `84.32.223.53` and `185.138.88.87`. IP allowlisting is defense in depth, not proof of authenticity; account for proxies and obtain the client IP only from a trusted ingress. Recheck the official documentation before changing an allowlist because source ranges can change.
