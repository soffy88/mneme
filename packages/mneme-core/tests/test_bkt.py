"""Tests for BKT posterior update."""
from mneme_core.oprim.bkt import update, new_posterior, BktParams

def test_posterior_monotonic():
    """Consecutive correct answers → P(L) monotonically increases."""
    post = new_posterior()
    prev_p = post.p_learned
    for _ in range(10):
        post = update(post, is_correct=True)
        assert post.p_learned > prev_p
        prev_p = post.p_learned

def test_incorrect_decreases():
    """Incorrect answer generally decreases P(L) (unless already very low)."""
    post = new_posterior(BktParams(p_init=0.5))
    post_after = update(post, is_correct=False)
    assert post_after.p_learned < post.p_learned

def test_n_obs_increments():
    """Each update increments n_obs."""
    post = new_posterior()
    assert post.n_obs == 0
    post = update(post, is_correct=True)
    assert post.n_obs == 1
    post = update(post, is_correct=False)
    assert post.n_obs == 2

def test_sigma_decreases_with_more_obs():
    """sigma should generally decrease as n_obs increases (more evidence)."""
    post = new_posterior()
    post = update(post, is_correct=True)
    sigma1 = post.sigma
    for _ in range(5):
        post = update(post, is_correct=True)
    assert post.sigma < sigma1
