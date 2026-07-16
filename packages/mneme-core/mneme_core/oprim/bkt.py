"""mneme-core BKT — standard 4-parameter Bayesian Knowledge Tracing update.

Pure functions, no IO.  Returns NEW objects on every call.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from mneme_core.oprim.models import BktPosterior


@dataclass(frozen=True)
class BktParams:
    """Immutable BKT hyper-parameters."""

    p_init: float = 0.2
    p_learn: float = 0.15
    p_slip: float = 0.1
    p_guess: float = 0.2


def new_posterior(params: BktParams = BktParams()) -> BktPosterior:
    """Create an initial BKT posterior from prior hyper-parameters.

    sigma is computed via binomial approximation: sqrt(p*(1-p)/max(n,1)).
    At n_obs=0 the denominator defaults to 1.
    """
    p = params.p_init
    sigma = math.sqrt(p * (1.0 - p))  # n=0 → denominator 1
    return BktPosterior(p_learned=p, sigma=sigma, n_obs=0)


def update(
    post: BktPosterior,
    is_correct: bool,
    params: BktParams = BktParams(),
) -> BktPosterior:
    """One-observation Bayesian update.  Returns a NEW BktPosterior (immutable pattern).

    Steps:
        1. Compute P(L | observation) using Bayes' rule with slip/guess.
        2. Apply learning transition: P(L') = P(L|obs) + (1 - P(L|obs)) * p_learn.
        3. Increment n_obs.
        4. Recompute sigma via binomial approximation: sqrt(p*(1-p)/n).
    """
    p_l = post.p_learned
    p_slip = params.p_slip
    p_guess = params.p_guess
    p_learn = params.p_learn

    # --- Step 1: posterior given observation ---
    if is_correct:
        # P(L | correct) = P(L)*(1-slip) / [P(L)*(1-slip) + (1-P(L))*guess]
        numerator = p_l * (1.0 - p_slip)
        denominator = numerator + (1.0 - p_l) * p_guess
    else:
        # P(L | incorrect) = P(L)*slip / [P(L)*slip + (1-P(L))*(1-guess)]
        numerator = p_l * p_slip
        denominator = numerator + (1.0 - p_l) * (1.0 - p_guess)

    p_l_given_obs = numerator / denominator if denominator > 0.0 else p_l

    # --- Step 2: learning transition ---
    p_new = p_l_given_obs + (1.0 - p_l_given_obs) * p_learn

    # --- Step 3 & 4: new observation count and sigma ---
    n = post.n_obs + 1
    sigma = math.sqrt(p_new * (1.0 - p_new) / max(n, 1))

    return BktPosterior(p_learned=p_new, sigma=sigma, n_obs=n)
