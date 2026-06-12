# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
import hmac
import hashlib
import time
from typing import Dict, Optional
from urllib.parse import urlencode, urlparse, parse_qs

from agent.lead_trader.metadata import RiskTier


def _hmac(secret_key: str, payload: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class FollowDeeplink:
    trader_id: str
    strategy_version_id: str
    risk_tier: RiskTier = RiskTier.MODERATE
    source: str = ""
    signal_id: str = ""
    base_url: str = "https://trade.kucoin.com"
    pre_check_token: str = ""
    pre_check_expiry: int = 0
    signature: str = ""

    def _signature_payload(self) -> str:
        return "|".join([
            self.trader_id,
            self.strategy_version_id,
            self.risk_tier.value,
            self.source,
            self.signal_id,
            self.pre_check_token,
            str(self.pre_check_expiry),
        ])

    def generate_pre_check_token(self, secret_key: str, ttl_seconds: int = 3600) -> str:
        self.pre_check_expiry = int(time.time()) + int(ttl_seconds)
        token_payload = f"{self.trader_id}|{self.strategy_version_id}|{self.pre_check_expiry}"
        self.pre_check_token = _hmac(secret_key, token_payload)
        return self.pre_check_token

    def generate_signature(self, secret_key: str) -> str:
        self.signature = _hmac(secret_key, self._signature_payload())
        return self.signature

    def verify_signature(self, secret_key: str) -> bool:
        expected = _hmac(secret_key, self._signature_payload())
        return hmac.compare_digest(expected, self.signature or "")

    def is_expired(self) -> bool:
        if not self.pre_check_expiry:
            return False
        return int(time.time()) >= int(self.pre_check_expiry)

    def to_url(self) -> str:
        params = {
            "trader_id": self.trader_id,
            "strategy_version_id": self.strategy_version_id,
            "risk_tier": self.risk_tier.value,
        }
        if self.source:
            params["source"] = self.source
        if self.signal_id:
            params["signal_id"] = self.signal_id
        if self.pre_check_token:
            params["pre_check_token"] = self.pre_check_token
        if self.pre_check_expiry:
            params["pre_check_expiry"] = str(self.pre_check_expiry)
        if self.signature:
            params["signature"] = self.signature
        return f"{self.base_url.rstrip('/')}/follow?{urlencode(params)}"

    @classmethod
    def from_url(cls, url: str) -> "FollowDeeplink":
        parsed = urlparse(url)
        query = parse_qs(parsed.query or "")
        tier = (query.get("risk_tier", [RiskTier.MODERATE.value])[0] or RiskTier.MODERATE.value).lower()
        try:
            risk_tier = RiskTier(tier)
        except ValueError:
            risk_tier = RiskTier.MODERATE
        return cls(
            trader_id=query.get("trader_id", [""])[0],
            strategy_version_id=query.get("strategy_version_id", [""])[0],
            risk_tier=risk_tier,
            source=query.get("source", [""])[0],
            signal_id=query.get("signal_id", [""])[0],
            base_url=f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "",
            pre_check_token=query.get("pre_check_token", [""])[0],
            pre_check_expiry=int(query.get("pre_check_expiry", ["0"])[0] or 0),
            signature=query.get("signature", [""])[0],
        )


class DeeplinkFactory:
    def __init__(self, secret_key: str, base_url: str, token_ttl_seconds: int = 1800):
        self.secret_key = secret_key
        self.base_url = base_url
        self.token_ttl_seconds = token_ttl_seconds

    def create(
        self,
        trader_id: str,
        strategy_version_id: str,
        risk_tier: RiskTier = RiskTier.MODERATE,
        source: str = "",
        signal_id: str = "",
    ) -> FollowDeeplink:
        link = FollowDeeplink(
            trader_id=trader_id,
            strategy_version_id=strategy_version_id,
            risk_tier=risk_tier,
            source=source,
            signal_id=signal_id,
            base_url=self.base_url,
        )
        link.generate_pre_check_token(self.secret_key, self.token_ttl_seconds)
        link.generate_signature(self.secret_key)
        return link

    def verify(self, deeplink: FollowDeeplink) -> Dict[str, object]:
        errors = []
        if deeplink.is_expired():
            errors.append("链接已过期")
        if not deeplink.verify_signature(self.secret_key):
            errors.append("签名无效")
        return {"valid": len(errors) == 0, "errors": errors}
