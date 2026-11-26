"""Checks the hard rules of the allocation and the demand logic on the sample data."""
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "prototype"))
import prioritize as p  # noqa: E402

DATA = PROJECT / "prototype" / "sample_data"
CONFIG = PROJECT / "config" / "settings.json"


class TestPrioritization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg, cls.offerings, cls.rooms, cls.sections, cls.k = p.run(DATA, CONFIG, cls.tmp.name)
        cls.room_by_id = {r.id: r for r in cls.rooms}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_room_is_double_booked(self):
        bookings = Counter((s["room_id"], slot) for s in self.sections if s["room_id"]
                           for slot in s["schedule"].split("; "))
        self.assertEqual([b for b, n in bookings.items() if n > 1], [])

    def test_room_matches_type_campus_and_capacity(self):
        for s in self.sections:
            if s["room_id"]:
                r = self.room_by_id[s["room_id"]]
                self.assertEqual(r.type, s["room_type"], s["section"])
                self.assertEqual(r.campus, s["campus"], s["section"])
                self.assertLessEqual(s["students"], r.capacity, s["section"])

    def test_rooms_stay_within_available_hours(self):
        for r in self.rooms:
            self.assertLessEqual(len(r.booked), r.max_blocks, r.id)

    def test_every_student_is_in_a_section(self):
        for o in self.offerings:
            placed = sum(s["students"] for s in self.sections if s["rank"] == o["rank"])
            self.assertEqual(placed, o["total_demand"], o["course_code"])

    def test_online_only_for_online_capable_courses(self):
        offline = {o["course_code"] for o in self.offerings if o["can_be_online"] == "N"}
        for s in self.sections:
            if s["outcome"] == p.ONLINE:
                self.assertNotIn(s["course_code"], offline)

    def test_graduating_course_ranks_first(self):
        self.assertEqual(self.offerings[0]["course_code"], "CE199")

    def test_failed_prerequisite_blocks_demand(self):
        ce199 = next(o for o in self.offerings if o["course_code"] == "CE199")
        self.assertGreater(ce199["prereq_blocked"], 0)   # failed MATH142 -> can't take thesis

    def test_missing_room_type_at_campus_is_flagged(self):
        mkt_chem = [s for s in self.sections if s["course_code"] == "CHM101L" and s["campus"] == "Makati"]
        self.assertTrue(mkt_chem)
        self.assertTrue(all(s["outcome"] == p.UNMET for s in mkt_chem))

    def test_weights_must_sum_to_one(self):
        bad = json.loads(CONFIG.read_text())
        bad["weights"]["graduating"] = 0.9
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
        with self.assertRaises(ValueError):
            p.load_config(f.name)
        Path(f.name).unlink()


if __name__ == "__main__":
    unittest.main()
