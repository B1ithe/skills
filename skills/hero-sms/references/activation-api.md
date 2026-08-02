# Hero SMS activation API

Official sources: [API reference](https://hero-sms.com/cn/api) and [project rules](https://hero-sms.com/cn/rules). Verified against the rendered official documentation on 2026-08-02.

## Protocol and authentication

| Surface | Base URL | Authentication | Typical responses |
| --- | --- | --- | --- |
| SMS-Activate compatibility | `https://hero-sms.com/stubs/handler_api.php` | `api_key` query parameter | Plain text, JSON, or empty `204` |
| REST activation offers | `https://hero-sms.com/api/v1` | `Authorization: ApiKey <key>` | JSON |

The project rules currently state a default account limit of 40 requests per second. Exceeding it can produce HTTP `1020` or `400` and a 10-second block. Keep normal polling far below this ceiling and back off immediately when throttled.

Set `HERO_SMS_API_KEY` in the process environment. With curl, use `--data-urlencode` rather than constructing query strings manually so commas and other values are encoded safely.

Send an explicit `User-Agent` from non-browser HTTP clients. Live verification showed that Python's default `urllib` request signature can receive Cloudflare `403` with error code `1010`; `User-Agent: HeroSMS-Skill/1.0` was accepted. The bundled CLI sets this header and an `Accept` header automatically.

## Core activation actions

All actions below use the compatibility handler unless stated otherwise.

| Action | Method | Parameters | Successful result |
| --- | --- | --- | --- |
| `getBalance` | GET | none | `ACCESS_BALANCE:<amount>` |
| `getNumber` | GET | required `service`, `country`; optional `operator`, `maxPrice`, `fixedPrice`, `ref`, `phoneException` | `ACCESS_NUMBER:<activation_id>:<phone>` |
| `getNumberV2` | GET | same as `getNumber` | JSON activation object |
| `getStatus` | GET | required `id` | Text such as `STATUS_WAIT_CODE` or `STATUS_OK:<code>` |
| `getStatusV2` | GET | required `id` | JSON with `verificationType` and optional `sms`/`call` data |
| `setStatus` | GET | required `id`, `status` | Text status-change result |
| `getAllSms` | GET | required `id`; optional `size`, `page` | `{data: [...], meta: {...}}` |
| `finishActivation` | GET | required `id` | HTTP `204`, no body |
| `cancelActivation` | GET | required `id` | HTTP `204`, no body |
| `getActiveActivations` | GET | optional `start`, `limit` (maximum 100) | `{status, data}` |
| `getHistory` | GET | optional `start`, `end` Unix timestamps, `offset`, `size` (maximum 100) | JSON array |

`getNumberV2` fields shown in the official example include `activationId`, `phoneNumber`, `activationCost`, `currency`, `countryCode`, `countryPhoneCode`, `canGetAnotherSms`, `activationTime`, `activationEndTime`, and `activationOperator`.

### Number constraints

- `service` is a service code, normally 2–4 characters.
- `country` is Hero SMS's numeric country ID, not an ISO country code.
- `operator` is a comma-separated list without spaces.
- `maxPrice` caps the acquisition price. Pair `fixedPrice=true` with it to require that price constraint strictly.
- `ref` is the caller's reference identifier.
- `phoneException` is a comma-separated list of excluded phone prefixes, up to 20 prefixes.

### Lifecycle status values

The official `setStatus` description lists:

- `3`: request another SMS;
- `6`: complete the activation after the code is received and confirmed;
- `8`: cancel the activation and request return of funds when cancellation remains allowed.

The official page currently shows a curl example with `status=1` even though its own status description lists `3`, `6`, and `8`. Treat that example as inconsistent: do not emit status `1` unless Hero SMS support or a newer official schema explicitly documents the intended behavior.

Use the dedicated `finishActivation` and `cancelActivation` endpoints when a JSON/HTTP lifecycle style is easier to model. A `409` means the transition cannot be performed in the current state; reconcile state instead of retrying blindly.

## Catalog, availability, and price actions

| Action/endpoint | Parameters | Notes |
| --- | --- | --- |
| `getCountries` | none | Live compatibility responses are objects keyed by numeric country ID; each value contains localized country metadata. |
| `getServicesList` | optional `country`, `lang` | `lang` includes `cn`, `de`, `en`, `es`, `fr`; default is `en`. |
| `getOperators` | optional `country` | Returns operators grouped by country. |
| `getPrices` | optional `service`, `country` | Unfiltered live responses are objects keyed by country ID, with service prices and counts nested below. Filtered shapes can be narrower. |
| `GET /api/v1/activations/offers` | optional comma-separated `services`, `countries` | Preferred grouped offer endpoint. Uses the REST base and header authentication. |
| `getTopCountriesByService` | `service`, optional `freePrice` | Deprecated; use activation offers. |
| `getTopCountriesByServiceRank` | `service`, optional `freePrice` | Deprecated; use activation offers. |

The offers response groups `data` by service code and country ID. Each offer includes `prices` (`default`, `retail`, `min`), `counts` (`total`, `physical`, `defaultPrice`), and a price-to-availability `map`. Preserve `meta` because it contains ordering and filter information. Treat offers as snapshots: live verification observed a quoted minimum of `0.015` followed by `WRONG_MAX_PRICE` with a current minimum of `0.0165` during acquisition.

## Rental, prolongation, and reactivation

| Action | Method | Required parameters | Purpose |
| --- | --- | --- | --- |
| `serviceCountRent` | GET | `service` | Current rental price/count; optional `country`, `operator`, `currency`. An empty object is a successful response meaning no matching rental inventory. |
| `getRentServicesAndCountries` | GET | `country`, `duration` | Rental services, quantities, prices, and operators. |
| `getRentNumber` | GET | `service`, `country`, `duration` | Acquire a rental; optional `operator`, `currency`, `ref`. |
| `getAllSms` | GET | `id` | Read all messages for an activation or rental. |
| `prolongOptions` | GET | `id` | Get extension price/duration options. |
| `prolong` | POST | `id`, `duration` | Extend a rental session. |
| `prolongHistory` | GET | `id` | Return extension history. |
| `reactivateOptions` | GET | `id` | Get reactivation price/duration options. |
| `reactivate` | POST | `id` | Reacquire a successfully used number; optional `duration`. |

Currency examples in the official schema are ISO 4217 numeric codes: `643` RUB, `840` USD, `978` EUR, and `156` CNY. Do not assume the account currency; preserve the returned `currency` field.

## Response and error parsing

Inspect both the HTTP status and body.

- Plain-text successes use colon-delimited prefixes. Split only the documented number of times so message content or future fields do not corrupt parsing.
- JSON successes may be an object or array. Do not force every success into one envelope.
- Empty `204` is success for finish/cancel; do not attempt JSON decoding.
- Structured errors use an object resembling `{"title":"WRONG_MAX_PRICE","details":"...","info":{"min":0.1234}}`. Preserve all three fields and redact sensitive values.
- HTTP `400/422` indicate invalid input, `401` invalid API key, `402` insufficient funds, `403` denied/banned, `404` missing action/activation or no sellable number depending on the operation, `409` invalid lifecycle transition, `429` throttling, and `500` a server error.

Compatibility handlers may return a business token in an HTTP-success response. Accept only a documented success prefix/status for the current action; treat any other token as a typed failure rather than a successful opaque string.

### Price drift

When acquisition returns `WRONG_MAX_PRICE`:

1. Treat the failed request as not having created an activation.
2. Read the current minimum from `info.min` and refresh `activations/offers` or `getPrices`.
3. Compare the refreshed price with the user's original maximum-price ceiling.
4. Retry only when it remains within that ceiling. Never increase the ceiling automatically.
5. After an ambiguous transport timeout instead of a definite HTTP error, reconcile active activations before any retry.

## Safe polling loop

1. Store `activationId`, activation end time, and polling deadline.
2. Poll `getStatus` or `getStatusV2` every few seconds with jitter; do not approach 40 RPS.
3. Continue on a documented waiting state. Return the code on a documented success state.
4. Stop on terminal/error state, deadline, or activation end time.
5. After an ambiguous network failure, query the activation before buying or mutating again.
6. Complete or cancel only when the caller authorized that lifecycle result.
