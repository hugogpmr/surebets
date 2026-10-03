from engine.market_filter import is_excluded_market


def test_odd_even_and_first_last_goal_or_corner_are_excluded():
    excluded = ["OE", "OE_HT", "OE_HOME_HT", "OE_Q1", "OE_SET1", "CORNERS_OE_HT", "CARDS_OE",
                "FIRST_GOAL", "FIRST_GOAL_2H", "FIRST_GOAL_P1", "LAST_GOAL", "CORNERS_FIRST", "CORNERS_LAST_HT"]
    kept = ["OU_2.5", "1X2", "AH_-0.5", "BTTS", "DC", "FIRST_SHOT_ON_TARGET", "FIRST_OFFSIDE", "FIRST_FOUL",
            "CORNERS_OU_9.5", "CARDS_OU_4.5", "OU_HOME_1.5", "DNB"]
    assert all(is_excluded_market(t) for t in excluded)
    assert not any(is_excluded_market(t) for t in kept)
