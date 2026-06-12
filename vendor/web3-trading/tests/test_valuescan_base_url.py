# -*- coding: utf-8 -*-
"""Unit tests for ValueScan API base URL normalization."""

from libs.valuescan.client import normalize_valuescan_api_root


def test_normalize_strips_open_v1_suffix():
    assert (
        normalize_valuescan_api_root("https://api.valuescan.io/api/open/v1")
        == "https://api.valuescan.io/api"
    )


def test_normalize_keeps_api_root():
    assert normalize_valuescan_api_root("https://api-beta.valuescan.io/api") == (
        "https://api-beta.valuescan.io/api"
    )


def test_normalize_empty_uses_default():
    assert normalize_valuescan_api_root("") == "https://api.valuescan.io/api"
