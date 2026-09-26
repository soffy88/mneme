"""Compatibility adapter for the canonical vendored BKT implementation.

``mneme_core`` keeps the historical posterior-shaped API used by a few
planning/value-object tests. It contains no BKT equations: updates delegate
to ``oprim._cognitive`` so this package cannot become a second authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mneme_core.domain.oprim.models import BktPosterior
from obase.cognitive_types import KCState
from oprim._cognitive import bkt_update


@dataclass(frozen=True)
class BktParams:
    """Historical parameter container retained for compatibility."""

    p_init: float = 0.2
    p_learn: float = 0.15
    p_slip: float = 0.1
    p_guess: float = 0.2


def _state(post: BktPosterior, params: BktParams) -> KCState:
    return KCState(
        kc_id="mneme-core-compat",
        p_init=params.p_init,
        p_transit=params.p_learn,
        p_guess=params.p_guess,
        p_slip=params.p_slip,
        p_mastery=post.p_learned,
        n_attempts=post.n_obs,
    )


def new_posterior(params: BktParams = BktParams()) -> BktPosterior:
    p = params.p_init
    return BktPosterior(p_learned=p, sigma=math.sqrt(p * (1.0 - p)), n_obs=0)


def update(
    post: BktPosterior,
    is_correct: bool,
    params: BktParams = BktParams(),
) -> BktPosterior:
    updated = bkt_update(state=_state(post, params), is_correct=is_correct)
    p = updated.current()
    n = post.n_obs + 1
    return BktPosterior(
        p_learned=p,
        sigma=math.sqrt(p * (1.0 - p) / max(n, 1)),
        n_obs=n,
    )
