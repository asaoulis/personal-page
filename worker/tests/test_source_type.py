"""Unit tests for the probabilistic source-type block (lune-box exclusion metric).

Offline; needs the seismo-sbi env only for the samples6 -> (gamma, delta) path.
"""
import numpy as np
import pytest

from fnet_monitor.source_type import (
    classify_outside_mass,
    prob_outside_dc_box,
    source_type_block,
)


def _dc_cloud(n=400, seed=0):
    """Tight cloud around a pure double-couple (unit-norm USE tensors)."""
    from fnet_monitor.inference import sdr_to_m6_use

    r = np.random.default_rng(seed)
    base = np.asarray(sdr_to_m6_use(200.0, 40.0, 80.0), float)
    return base + 0.02 * r.standard_normal((n, 6))


def _iso_cloud(n=400, sign=+1, seed=0):
    """Tight cloud around a (sign)ed isotropic source (delta -> +/-90)."""
    r = np.random.default_rng(seed)
    base = sign * np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
    return base + 0.05 * r.standard_normal((n, 6))


def test_pure_dc_cloud_p_near_zero():
    p = prob_outside_dc_box(_dc_cloud())
    assert p < 0.05
    block = source_type_block(_dc_cloud())
    assert block["label"] == "DC-consistent"
    assert block["p_outside_dc_box_10"] == p


def test_iso_cloud_p_near_one_and_signed_label():
    for sign, tag in ((+1, "+ISO"), (-1, "-ISO")):
        cloud = _iso_cloud(sign=sign)
        assert prob_outside_dc_box(cloud) > 0.99
        block = source_type_block(cloud)
        assert block["label"] == f"non-DC ({tag})"
        assert block["p_outside_dc_box_10"] >= 0.95


def test_clvd_classification_from_gamma_delta():
    # gamma-dominated outside mass -> CLVD, signed by the median gamma
    g = np.full(200, 25.0)
    d = np.zeros(200)
    assert classify_outside_mass(g, d) == "+CLVD"
    assert classify_outside_mass(-g, d) == "-CLVD"
    block = source_type_block(gamma=-g, delta=d)
    assert block["label"] == "non-DC (-CLVD)"


def test_threshold_labelling_is_conservative():
    # 90% of the mass outside the box: a big number, but NOT >= 0.95 -> DC-consistent
    g = np.concatenate([np.full(90, 20.0), np.zeros(10)])
    d = np.zeros(100)
    block = source_type_block(gamma=g, delta=d)
    assert block["p_outside_dc_box_10"] == pytest.approx(0.9)
    assert block["label"] == "DC-consistent"
    # 96% outside -> the non-DC claim is allowed
    g2 = np.concatenate([np.full(96, 20.0), np.zeros(4)])
    d2 = np.zeros(100)
    assert source_type_block(gamma=g2, delta=d2)["label"] == "non-DC (+CLVD)"


def test_boundary_samples_count_as_outside():
    # |gamma| == tau counts as outside (matches the stored p_outside_dc_box definition)
    g = np.full(10, 10.0)
    d = np.zeros(10)
    assert prob_outside_dc_box(gamma=g, delta=d) == 1.0


def test_needs_samples_or_gamma_delta():
    with pytest.raises(ValueError):
        prob_outside_dc_box()


def test_contract_rejects_overclaiming_label():
    from fnet_monitor import contract

    st = {"p_outside_dc_box_10": 0.5, "label": "non-DC (+ISO)"}
    with pytest.raises(AssertionError):
        contract._validate_source_type(st)
    contract._validate_source_type({"p_outside_dc_box_10": 0.5, "label": "DC-consistent"})
    contract._validate_source_type({"p_outside_dc_box_10": 0.99, "label": "non-DC (-ISO)"})
    with pytest.raises(AssertionError):
        contract._validate_source_type("double-couple")  # legacy string no longer valid
