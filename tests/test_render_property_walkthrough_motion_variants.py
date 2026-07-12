import pytest

from scripts.render_property_walkthrough_motion_variants import motion_filter, parse_variant


def test_parse_variant_accepts_mobile_delivery_contract() -> None:
    variant = parse_variant("mobile:1280:720:20")

    assert variant.key == "mobile"
    assert variant.width == 1280
    assert variant.height == 720
    assert variant.crf == 20


def test_motion_filter_uses_real_bidirectional_motion_interpolation() -> None:
    variant = parse_variant("desktop:1920:1080:21")

    assert motion_filter(variant) == (
        "scale=1920:1080:flags=lanczos,"
        "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    )


def test_motion_filter_preserves_already_interpolated_60fps_source() -> None:
    variant = parse_variant("mobile:1280:720:20")

    assert motion_filter(variant, source_fps=60.0) == "scale=1280:720:flags=lanczos,fps=60"


@pytest.mark.parametrize(
    "value,error",
    [
        ("mobile:1279:720:20", "variant_dimensions_invalid"),
        ("mobile:1280:720:60", "variant_crf_invalid"),
        ("mobile:1280:720", "variant_must_be_key_width_height_crf"),
    ],
)
def test_parse_variant_rejects_invalid_delivery_contract(value: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_variant(value)
