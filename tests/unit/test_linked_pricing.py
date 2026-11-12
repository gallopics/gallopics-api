from types import SimpleNamespace

import pytest

from app.services.pricing import QUALITY_TIERS, photo_price


@pytest.mark.parametrize("quality", QUALITY_TIERS)
def test_photo_price_resolution_order(quality):
    tier = QUALITY_TIERS[quality]
    photographer = SimpleNamespace(**{f"default_price_{quality}":None})
    photo = SimpleNamespace(photographer=photographer, **{f"price_{quality}":None})
    assert photo_price(photo,tier) == tier.default_amount
    setattr(photographer,f"default_price_{quality}",7900)
    assert photo_price(photo,tier) == 7900
    setattr(photo,f"price_{quality}",9900)
    assert photo_price(photo,tier) == 9900
    setattr(photo,f"price_{quality}",None)
    assert photo_price(photo,tier) == 7900
