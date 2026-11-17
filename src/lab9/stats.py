"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from math import comb

import numpy as np
from scipy import stats as scipy_stats

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    if len(human) != len(judge):
        raise ValueError("human and judge labels must have the same length")
    if any(x not in {"PASS", POS} for x in (*human, *judge)):
        raise ValueError("labels must be PASS or FAIL")
    return {
        "tp": sum(h == POS and j == POS for h, j in zip(human, judge)),
        "fp": sum(h != POS and j == POS for h, j in zip(human, judge)),
        "fn": sum(h == POS and j != POS for h, j in zip(human, judge)),
        "tn": sum(h != POS and j != POS for h, j in zip(human, judge)),
    }


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    cm = confusion(human, judge)
    precision = cm["tp"] / (cm["tp"] + cm["fp"]) if cm["tp"] + cm["fp"] else 0.0
    recall = cm["tp"] / (cm["tp"] + cm["fn"]) if cm["tp"] + cm["fn"] else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    if len(human) != len(judge):
        raise ValueError("human and judge labels must have the same length")
    if not human:
        raise ValueError("kappa is undefined for empty labels")
    cm = confusion(human, judge)
    n = len(human)
    observed = (cm["tp"] + cm["tn"]) / n
    human_fail = sum(x == POS for x in human)
    judge_fail = sum(x == POS for x in judge)
    expected = (human_fail * judge_fail + (n - human_fail) * (n - judge_fail)) / (n * n)
    if expected == 1:
        raise ValueError("kappa is undefined when expected agreement is 1")
    return (observed - expected) / (1 - expected)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    rates = (observed_rate, sensitivity, specificity)
    if any(not math.isfinite(x) or not 0 <= x <= 1 for x in rates):
        raise ValueError("observed_rate, sensitivity, and specificity must be in [0, 1]")
    denominator = sensitivity + specificity - 1
    if denominator == 0:
        raise ValueError("sensitivity and specificity do not identify the true rate")
    return min(1.0, max(0.0, (observed_rate + specificity - 1) / denominator))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if not a:
        raise ValueError("paired bootstrap requires at least one observation")
    if n_resamples < 1:
        raise ValueError("n_resamples must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    left, right = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
        raise ValueError("paired samples must be finite")
    difference = left - right
    estimate = float(np.mean(difference))
    if np.all(difference == 0):
        return 0.0, 0.0, 0.0

    result = scipy_stats.bootstrap(
        (left, right),
        lambda x, y, axis: np.mean(x - y, axis=axis),
        paired=True,
        vectorized=True,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="percentile",
        rng=np.random.default_rng(rng),
    )
    return estimate, float(result.confidence_interval.low), float(result.confidence_interval.high)


def _validate_pass_k(n: int, c: int, k: int) -> None:
    if any(not isinstance(x, int) or isinstance(x, bool) for x in (n, c, k)):
        raise ValueError("n, c, and k must be integers")
    if n < 1 or c < 0 or c > n or k < 1 or k > n:
        raise ValueError("require n >= 1, 0 <= c <= n, and 1 <= k <= n")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _validate_pass_k(n, c, k)
    if n - c < k:
        return 1.0
    return 1 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _validate_pass_k(n, c, k)
    if c < k:
        return 0.0
    return comb(c, k) / comb(n, k)
