#!/usr/bin/env python3
"""Small, dependency-free Hero SMS CLI with explicit mutation guards."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_HANDLER_URL = "https://hero-sms.com/stubs/handler_api.php"
DEFAULT_API_BASE_URL = "https://hero-sms.com/api/v1"
DEFAULT_HEADERS = {
    "User-Agent": "HeroSMS-Skill/1.0",
    "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
}
MUTATING_COMMANDS = {"number", "set-status", "finish", "cancel"}


class HeroSmsError(RuntimeError):
    """A sanitized Hero SMS transport or protocol failure."""

    def __init__(self, message: str, *, status: Optional[int] = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


def parse_payload(body: bytes, content_type: str = "") -> Any:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if "json" in content_type.lower() or text[:1] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def request(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 20.0,
) -> Any:
    request_headers = {**DEFAULT_HEADERS, **(headers or {})}
    req = Request(url, method=method, headers=request_headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            return parse_payload(response.read(), response.headers.get("Content-Type", ""))
    except HTTPError as exc:
        payload = parse_payload(exc.read(), exc.headers.get("Content-Type", ""))
        detail = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
        raise HeroSmsError(
            f"Hero SMS HTTP {exc.code}: {detail or exc.reason}",
            status=exc.code,
            payload=payload,
        ) from None
    except URLError as exc:
        raise HeroSmsError(f"Hero SMS transport error: {exc.reason}") from None


def add_query(url: str, params: Dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return f"{url}?{urlencode(clean)}" if clean else url


def legacy(action: str, api_key: str, timeout: float, method: str = "GET", **params: Any) -> Any:
    handler = os.environ.get("HERO_SMS_HANDLER_URL", DEFAULT_HANDLER_URL)
    url = add_query(handler, {"action": action, **params, "api_key": api_key})
    return request(url, method=method, timeout=timeout)


def rest_get(path: str, api_key: str, timeout: float, **params: Any) -> Any:
    base = os.environ.get("HERO_SMS_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
    url = add_query(f"{base}/{path.lstrip('/')}", params)
    return request(url, headers={"Authorization": f"ApiKey {api_key}"}, timeout=timeout)


def require_confirmation(args: argparse.Namespace) -> None:
    if args.command in MUTATING_COMMANDS and not args.yes:
        raise HeroSmsError(
            f"{args.command} changes paid activation state; review the request and rerun with --yes"
        )


def wrong_max_price_minimum(error: HeroSmsError) -> Any:
    payload = error.payload
    if error.status != 400 or not isinstance(payload, dict) or payload.get("title") != "WRONG_MAX_PRICE":
        return None
    info = payload.get("info")
    return info.get("min") if isinstance(info, dict) else None


def run(args: argparse.Namespace, api_key: str) -> Any:
    require_confirmation(args)
    timeout = args.timeout

    if args.command == "balance":
        return legacy("getBalance", api_key, timeout)
    if args.command == "countries":
        return legacy("getCountries", api_key, timeout)
    if args.command == "services":
        return legacy("getServicesList", api_key, timeout, country=args.country, lang=args.lang)
    if args.command == "operators":
        return legacy("getOperators", api_key, timeout, country=args.country)
    if args.command == "prices":
        return legacy("getPrices", api_key, timeout, service=args.service, country=args.country)
    if args.command == "offers":
        return rest_get("activations/offers", api_key, timeout, services=args.services, countries=args.countries)
    if args.command == "number":
        action = "getNumberV2" if args.v2 else "getNumber"
        try:
            return legacy(
                action,
                api_key,
                timeout,
                service=args.service,
                country=args.country,
                operator=args.operator,
                maxPrice=args.max_price,
                fixedPrice="true" if args.fixed_price else None,
                ref=args.ref,
                phoneException=args.phone_exception,
            )
        except HeroSmsError as exc:
            minimum = wrong_max_price_minimum(exc)
            if minimum is None:
                raise
            raise HeroSmsError(
                f"Hero SMS rejected --max-price; current minimum is {minimum}. "
                "No activation was created. Refresh offers and retry only within the user's approved ceiling.",
                status=exc.status,
                payload=exc.payload,
            ) from None
    if args.command == "status":
        return legacy("getStatusV2" if args.v2 else "getStatus", api_key, timeout, id=args.id)
    if args.command == "all-sms":
        return legacy("getAllSms", api_key, timeout, id=args.id, size=args.size, page=args.page)
    if args.command == "set-status":
        return legacy("setStatus", api_key, timeout, id=args.id, status=args.status)
    if args.command == "finish":
        return legacy("finishActivation", api_key, timeout, id=args.id)
    if args.command == "cancel":
        return legacy("cancelActivation", api_key, timeout, id=args.id)
    raise HeroSmsError(f"unsupported command: {args.command}")


def add_common_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", required=True, type=int, help="activation ID")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("balance", help="read account balance")
    subs.add_parser("countries", help="list Hero SMS country IDs")

    services = subs.add_parser("services", help="list service codes")
    services.add_argument("--country", type=int)
    services.add_argument("--lang", default="en", choices=("cn", "de", "en", "es", "fr"))

    operators = subs.add_parser("operators", help="list operators")
    operators.add_argument("--country", type=int)

    prices = subs.add_parser("prices", help="read current price and availability")
    prices.add_argument("--service")
    prices.add_argument("--country", type=int)

    offers = subs.add_parser("offers", help="read grouped REST activation offers")
    offers.add_argument("--services", help="comma-separated service codes")
    offers.add_argument("--countries", help="comma-separated numeric country IDs")

    number = subs.add_parser("number", help="purchase an OTP number")
    number.add_argument("--service", required=True)
    number.add_argument("--country", required=True, type=int)
    number.add_argument("--operator", help="comma-separated operators without spaces")
    number.add_argument("--max-price", type=float)
    number.add_argument("--fixed-price", action="store_true")
    number.add_argument("--ref")
    number.add_argument("--phone-exception", help="comma-separated excluded prefixes")
    number.add_argument("--v2", action="store_true", help="return structured getNumberV2 data")
    number.add_argument("--yes", action="store_true", help="confirm the paid acquisition")

    status = subs.add_parser("status", help="read activation status")
    add_common_id(status)
    status.add_argument("--v2", action="store_true", help="request structured status data")

    all_sms = subs.add_parser("all-sms", help="read all messages for an activation")
    add_common_id(all_sms)
    all_sms.add_argument("--size", type=int)
    all_sms.add_argument("--page", type=int)

    set_status = subs.add_parser("set-status", help="request another SMS, complete, or cancel")
    add_common_id(set_status)
    set_status.add_argument("--status", required=True, type=int, choices=(3, 6, 8))
    set_status.add_argument("--yes", action="store_true", help="confirm the lifecycle mutation")

    finish = subs.add_parser("finish", help="finish an activation")
    add_common_id(finish)
    finish.add_argument("--yes", action="store_true", help="confirm the lifecycle mutation")

    cancel = subs.add_parser("cancel", help="cancel an activation")
    add_common_id(cancel)
    cancel.add_argument("--yes", action="store_true", help="confirm the lifecycle mutation")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    api_key = os.environ.get("HERO_SMS_API_KEY")
    if not api_key:
        parser.error("set HERO_SMS_API_KEY in the environment")

    try:
        result = run(args, api_key)
    except HeroSmsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif result is not None:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
