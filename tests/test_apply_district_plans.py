import unittest
from unittest.mock import Mock

from leadhunter.apply_district_plans import apply


def plans():
    return {f"{code:02d}": {
        "source_url": "https://example.invalid/summary.json",
        "source_sha256": "a" * 64,
        "work_item_ids": [f"relation/{code}"],
        "excluded_item_ids": [],
    } for code in range(1, 82)}


class ApplyDistrictPlansTests(unittest.TestCase):
    def test_adds_missing_plans_only_and_is_idempotent(self):
        connection = object()
        state = {"provinces": [{"code": code, "plan": None}
                               for code in plans()]}
        configured = []

        def read(_):
            return state

        def configure(_, code, **kwargs):
            configured.append((code, kwargs))
            for province in state["provinces"]:
                if province["code"] == code:
                    province["plan"] = {key: kwargs[key] for key in (
                        "source_url", "source_sha256", "work_item_ids", "excluded_item_ids")}
            return state

        result = apply(connection, plans(), "2026-11-27T00:00:00+00:00", read, configure)
        self.assertEqual(result, {"provinces":81,"districts":81,"created":81,
                                  "already_configured":0,"scans_started":0})
        second = apply(connection, plans(), "2026-11-28T00:00:00+00:00", read, configure)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["already_configured"], 81)
        self.assertEqual(len(configured), 81)

    def test_conflicting_existing_plan_is_never_replaced(self):
        desired = plans()
        state = {"provinces": [{"code": code, "plan": None}
                               for code in desired]}
        state["provinces"][1]["plan"] = {**desired["02"],
                                           "work_item_ids":["relation/999"]}
        configure = Mock()
        with self.assertRaisesRegex(RuntimeError, "differs"):
            apply(object(), desired, read_registry=lambda _: state,
                  configure=configure)
        configure.assert_not_called()
        self.assertIsNone(state["provinces"][0]["plan"])

    def test_rejects_incomplete_province_set(self):
        with self.assertRaisesRegex(ValueError, "81-province"):
            apply(object(), {"01":plans()["01"]},
                  read_registry=lambda _: {"provinces":[{"code":"01","plan":None}]})


if __name__ == "__main__":
    unittest.main()
