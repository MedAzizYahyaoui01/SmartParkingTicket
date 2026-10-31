"""Public holidays, for the `is_holiday` feature (and the synthetic generator).

Only the fixed-date Tunisian holidays: the religious ones (Eid, Mouled, Ras el Am el Hijri)
follow the lunar calendar and move every year, so they are not listed.
"""

from datetime import date

# (month, day)
TN_FIXED_HOLIDAYS = {
    (1, 1),  # New Year
    (3, 20),  # Independence Day
    (4, 9),  # Martyrs' Day
    (5, 1),  # Labour Day
    (7, 25),  # Republic Day
    (8, 13),  # Women's Day
    (10, 15),  # Evacuation Day
    (12, 17),  # Revolution Day
}


def is_holiday(day: date) -> bool:
    return (day.month, day.day) in TN_FIXED_HOLIDAYS
