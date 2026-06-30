from __future__ import annotations

import math
from typing import Literal


def zscore_series(
    values: list[float | None],
    *,
    min_samples: int = 5,
    require_finite: bool = False,
    on_insufficient: Literal["none", "passthrough"] = "passthrough",
    on_zero_std: Literal["unit", "passthrough"] = "passthrough",
) -> list[float | None]:
    if require_finite:
        paired = [float(v) for v in values if v is not None and math.isfinite(v)]
    else:
        paired = [float(v) for v in values if v is not None]

    if len(paired) < min_samples:
        if on_insufficient == "none":
            return [None] * len(values)
        return list(values)

    mean = sum(paired) / len(paired)
    var = sum((v - mean) ** 2 for v in paired) / (len(paired) - 1)
    std = math.sqrt(var) if var > 1e-12 else 0.0
    if std < 1e-9:
        if on_zero_std == "unit":
            std = 1.0
        else:
            return list(values)

    out: list[float | None] = []
    for value in values:
        if value is None or (require_finite and not math.isfinite(value)):
            out.append(None)
            continue
        out.append((float(value) - mean) / std)
    return out
