from __future__ import annotations

from pricing.schema import PriceTier


def tiered_cost(amount_gb: float, tiers: tuple[PriceTier, ...]) -> float:
    if amount_gb <= 0:
        return 0.0

    remaining = amount_gb
    previous_limit = 0.0
    total = 0.0

    for tier in tiers:
        if tier.up_to_gb is None:
            total += remaining * tier.price
            return total

        tier_size = tier.up_to_gb - previous_limit
        used = min(remaining, tier_size)
        total += used * tier.price
        remaining -= used
        previous_limit = tier.up_to_gb

        if remaining <= 0:
            return total

    if tiers:
        total += remaining * tiers[-1].price
    return total
