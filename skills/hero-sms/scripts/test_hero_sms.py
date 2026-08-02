#!/usr/bin/env python3
"""Regression tests for the dependency-free Hero SMS CLI."""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


MODULE_PATH = Path(__file__).with_name("hero_sms.py")


def load_module():
    spec = importlib.util.spec_from_file_location("hero_sms_under_test", str(MODULE_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load hero_sms.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class HeroSmsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hero = load_module()

    def test_request_sends_api_compatible_default_headers(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["headers"] = {key.lower(): value for key, value in req.header_items()}
            captured["timeout"] = timeout
            return FakeResponse(b"ACCESS_BALANCE:1.0")

        with patch.object(self.hero, "urlopen", fake_urlopen):
            self.hero.request("https://hero-sms.com/test", timeout=7)

        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["headers"]["user-agent"], "HeroSMS-Skill/1.0")
        self.assertIn("application/json", captured["headers"]["accept"])

    def test_mutation_guard_blocks_number_without_confirmation(self) -> None:
        args = self.hero.build_parser().parse_args(
            ["number", "--service", "tg", "--country", "2"]
        )

        with patch.object(self.hero, "legacy") as legacy:
            with self.assertRaisesRegex(self.hero.HeroSmsError, "rerun with --yes"):
                self.hero.run(args, "secret")

        legacy.assert_not_called()

    def test_empty_success_body_is_not_decoded_as_json(self) -> None:
        self.assertIsNone(self.hero.parse_payload(b"", "application/json"))

    def test_rest_auth_is_merged_with_default_headers(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["headers"] = {key.lower(): value for key, value in req.header_items()}
            captured["timeout"] = timeout
            return FakeResponse(b'{"data": {}}', "application/json")

        with patch.object(self.hero, "urlopen", fake_urlopen):
            result = self.hero.rest_get("activations/offers", "secret", 7, services="tg")

        self.assertEqual(result, {"data": {}})
        self.assertEqual(captured["headers"]["authorization"], "ApiKey secret")
        self.assertEqual(captured["headers"]["user-agent"], "HeroSMS-Skill/1.0")

    def test_http_error_preserves_status_and_json_payload(self) -> None:
        payload = {
            "title": "WRONG_MAX_PRICE",
            "details": "The maximum price is less than the permitted price",
            "info": {"min": 0.0165},
        }
        headers = Message()
        headers["Content-Type"] = "application/json"
        error = HTTPError(
            "https://hero-sms.com/test",
            400,
            "Bad Request",
            headers,
            io.BytesIO(json.dumps(payload).encode()),
        )

        with patch.object(self.hero, "urlopen", side_effect=error):
            with self.assertRaises(self.hero.HeroSmsError) as raised:
                self.hero.request("https://hero-sms.com/test")

        self.assertEqual(getattr(raised.exception, "status", None), 400)
        self.assertEqual(getattr(raised.exception, "payload", None), payload)

    def test_wrong_max_price_reports_no_purchase_and_current_minimum(self) -> None:
        error = self.hero.HeroSmsError("price rejected")
        error.status = 400
        error.payload = {
            "title": "WRONG_MAX_PRICE",
            "details": "The maximum price is less than the permitted price",
            "info": {"min": 0.0165},
        }
        args = self.hero.build_parser().parse_args(
            ["number", "--service", "ig", "--country", "10", "--max-price", "0.015", "--yes"]
        )

        with patch.object(self.hero, "legacy", side_effect=error):
            with self.assertRaises(self.hero.HeroSmsError) as raised:
                self.hero.run(args, "secret")

        message = str(raised.exception)
        self.assertIn("current minimum is 0.0165", message)
        self.assertIn("No activation was created", message)
        self.assertIn("refresh offers", message.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
