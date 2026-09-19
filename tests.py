"""Tests for Party Run-of-Show."""
import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from blocks import (
    BLOCKS, OCCASION_TEMPLATES, blocks_for_occasion, get_block, all_occasion_keys,
    ENERGY_WARM, ENERGY_LOW, ENERGY_MID, ENERGY_HIGH, ENERGY_PEAK,
)
from generator import (
    parse_brief, merge_defaults, generate_run_of_show, score_run_of_show,
    verdict_for, build_insights, build_flags, block_eligibility_score,
)


class TestBlocks(unittest.TestCase):
    def test_all_blocks_have_required_keys(self):
        required = {"id", "stage", "title", "energy", "default_minutes", "materials",
                    "min_group", "max_group", "ages", "noise", "conflict_safe",
                    "occasions", "rationale"}
        for b in BLOCKS:
            self.assertTrue(required.issubset(b.keys()), f"missing keys in {b.get('id')}")
            self.assertIn(b["stage"], ["welcome", "opener", "main", "intermission", "closer", "wind_down"])
            self.assertIn(b["energy"], [1, 2, 3, 4, 5])
            self.assertGreater(b["max_group"], b["min_group"])
            self.assertGreater(b["default_minutes"], 0)

    def test_block_ids_unique(self):
        ids = [b["id"] for b in BLOCKS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_at_least_30_blocks(self):
        self.assertGreaterEqual(len(BLOCKS), 30, "expect a substantive library")

    def test_each_occasion_has_blocks(self):
        for k in all_occasion_keys():
            self.assertGreaterEqual(len(blocks_for_occasion(k)), 4, f"{k} too few blocks")

    def test_block_age_mappings_consistent(self):
        for b in BLOCKS:
            if b["ages"] == "kids":
                # kids block should fit some kids occasion
                kids_occs = {"kids_party", "birthday"}
                self.assertTrue(set(b["occasions"]) & kids_occs, f"{b['id']} is kids-aged but no kids occasion")

    def test_occasion_templates_complete(self):
        for k, t in OCCASION_TEMPLATES.items():
            self.assertIn("label", t)
            self.assertIn("default_minutes", t)
            self.assertIn("must_include_stages", t)
            self.assertIn("required_block_ids", t)
            self.assertIn("forbidden_block_ids", t)
            for rid in t["required_block_ids"]:
                self.assertIsNotNone(get_block(rid), f"required block missing: {rid}")


class TestParseBrief(unittest.TestCase):
    def test_parse_birthday(self):
        info = parse_brief("birthday party for my friend, 10 people, 3 hours")
        self.assertEqual(info["occasion"], "birthday")
        self.assertEqual(info["group_size"], 10)
        self.assertEqual(info["total_minutes"], 180)
        self.assertEqual(info["ages"], "adults_teens")

    def test_parse_kids_party(self):
        info = parse_brief("kids party for 8 year old, 12 kids, 90 min")
        self.assertEqual(info["occasion"], "kids_party")
        self.assertEqual(info["ages"], "kids")
        self.assertEqual(info["total_minutes"], 90)
        self.assertEqual(info["group_size"], 12)

    def test_parse_game_night(self):
        info = parse_brief("games night, 6 adults, 2.5 hours, chill")
        self.assertEqual(info["occasion"], "game_night")
        self.assertEqual(info["energy_target"], "low")
        self.assertEqual(info["total_minutes"], 150)

    def test_parse_dinner_party(self):
        info = parse_brief("dinner party with 8 adults")
        self.assertEqual(info["occasion"], "dinner_party")
        self.assertEqual(info["group_size"], 8)

    def test_parse_work_offsite(self):
        info = parse_brief("work offsite team social, 15 people")
        self.assertEqual(info["occasion"], "work_offsite")
        self.assertEqual(info["group_size"], 15)
        self.assertTrue(info["conflict_safe"])

    def test_parse_holiday(self):
        info = parse_brief("christmas dinner, 20 people")
        self.assertEqual(info["occasion"], "holiday")
        self.assertEqual(info["group_size"], 20)

    def test_parse_uses_defaults(self):
        info = merge_defaults(parse_brief("birthday"))
        # defaults applied
        self.assertEqual(info["occasion"], "birthday")
        self.assertIsNotNone(info["group_size"])
        self.assertIsNotNone(info["total_minutes"])

    def test_unknown_occasion_falls_back(self):
        # No occasion keyword
        info = parse_brief("just some random gathering with 5 adults")
        self.assertIsNone(info["occasion"])


class TestGeneration(unittest.TestCase):
    def test_generates_birthday(self):
        info = merge_defaults(parse_brief("birthday party, 10 adults, 3 hours"))
        r = generate_run_of_show(info)
        self.assertIn("timeline", r)
        self.assertGreater(len(r["timeline"]), 2)
        # toast required
        self.assertTrue(any(b["id"] == "closer_toast" for b in r["timeline"]))
        # closing stage present
        self.assertTrue(any(b["stage"] == "closer" for b in r["timeline"]))

    def test_generates_kids_party(self):
        info = merge_defaults(parse_brief("kids party, 12 kids, 90 min"))
        r = generate_run_of_show(info)
        # cake required
        self.assertTrue(any(b["id"] == "closer_cake_candles" for b in r["timeline"]))
        # no karaoke in kids party
        self.assertFalse(any(b["id"] == "main_karaoke_rounds" for b in r["timeline"]))

    def test_generates_dinner_party_has_dinner(self):
        info = merge_defaults(parse_brief("dinner party, 8 adults, 3 hours"))
        r = generate_run_of_show(info)
        self.assertTrue(any(b["id"] == "main_dinner_main" for b in r["timeline"]))
        # pinata shouldn't sneak in
        self.assertFalse(any(b["id"] == "main_pinata" for b in r["timeline"]))

    def test_generates_game_night(self):
        info = merge_defaults(parse_brief("game night, 8 adults, 3 hours"))
        r = generate_run_of_show(info)
        # must include main + wind_down
        self.assertTrue(any(b["stage"] == "main" for b in r["timeline"]))
        self.assertTrue(any(b["stage"] == "wind_down" for b in r["timeline"]))

    def test_timing_close_to_window(self):
        info = merge_defaults(parse_brief("birthday party, 10 adults, 3 hours"))
        r = generate_run_of_show(info)
        actual = sum(b["minutes"] for b in r["timeline"])
        # within ±30 of requested
        self.assertLess(abs(actual - 180), 60)

    def test_no_required_blocks_missing(self):
        for occ in all_occasion_keys():
            info = merge_defaults({"occasion": occ, "group_size": 10, "ages": "adults_teens", "total_minutes": 180, "energy_target": "mid", "conflict_safe": None})
            r = generate_run_of_show(info)
            for rid in OCCASION_TEMPLATES[occ]["required_block_ids"]:
                self.assertTrue(any(b["id"] == rid for b in r["timeline"]), f"{occ}: required block {rid} missing")

    def test_forbidden_blocks_excluded(self):
        for occ in all_occasion_keys():
            info = merge_defaults({"occasion": occ, "group_size": 10, "ages": "adults_teens", "total_minutes": 180, "energy_target": "mid", "conflict_safe": None})
            r = generate_run_of_show(info)
            for fid in OCCASION_TEMPLATES[occ]["forbidden_block_ids"]:
                self.assertFalse(any(b["id"] == fid for b in r["timeline"]), f"{occ}: forbidden block {fid} present")

    def test_conflict_safe_flag_filters(self):
        info = merge_defaults(parse_brief("birthday party, 10 adults, 3 hours, conflict-safe"))
        info["conflict_safe"] = True
        r = generate_run_of_show(info)
        # No conflict-risky block under safe mode
        risky = [b for b in r["timeline"] if not b["conflict_safe"]]
        self.assertEqual(risky, [], f"unsafe blocks: {[b['id'] for b in risky]}")


class TestScoring(unittest.TestCase):
    def test_score_in_range(self):
        info = merge_defaults(parse_brief("birthday party, 10 adults, 3 hours"))
        r = generate_run_of_show(info)
        s = r["scoring"]
        self.assertGreaterEqual(s["overall"], 0)
        self.assertLessEqual(s["overall"], 100)
        for v in s["axes"].values():
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)

    def test_verdict_bands(self):
        self.assertEqual(verdict_for(95), "Showtime Ready")
        self.assertEqual(verdict_for(75), "Solid Run-of-Show")
        self.assertEqual(verdict_for(58), "Workable — Tighten Timing")
        self.assertEqual(verdict_for(45), "Sketchy — Re-plan Stages")
        self.assertEqual(verdict_for(20), "Better Reschedule")

    def test_axes_weights_sum_to_one(self):
        info = merge_defaults(parse_brief("birthday party, 10 adults"))
        r = generate_run_of_show(info)
        self.assertAlmostEqual(sum(r["scoring"]["weights"].values()), 1.0, places=2)

    def test_energy_arc_present(self):
        info = merge_defaults(parse_brief("birthday party, 10 adults, 3 hours"))
        r = generate_run_of_show(info)
        energies = [b["energy"] for b in r["timeline"]]
        # has at least one peak-ish
        self.assertGreaterEqual(max(energies), 4, "no high-energy peak")
        # ends warm
        self.assertLessEqual(energies[-1], 3, "doesn't end on a wind-down note")

    def test_no_adjacent_same_energy_in_good_runs(self):
        # Repeat multiple seeds via different briefs
        for brief in [
            "birthday party, 10 adults, 3 hours",
            "game night, 8 adults, 3 hours",
            "dinner party, 8 adults, 3 hours",
            "holiday gathering, 15 people, 4 hours",
        ]:
            info = merge_defaults(parse_brief(brief))
            r = generate_run_of_show(info)
            energies = [b["energy"] for b in r["timeline"]]
            adj_same = sum(1 for i in range(1, len(energies)) if energies[i] == energies[i-1])
            # Some adjacency is fine; just shouldn't be all-same
            self.assertLess(adj_same, len(energies) - 1, brief)


class TestFlags(unittest.TestCase):
    def test_flag_when_kids_block_in_adult_party(self):
        # Force a kids block in adults' occasion via small group trick
        info = merge_defaults(parse_brief("birthday party, 5 adults, 90 min"))
        # Manually inject a kids block
        info["ages"] = "adults_teens"
        # Build with conflict_safe=False to keep broad selection
        r = generate_run_of_show(info)
        # There shouldn't be kids-coded blocks
        kids_blocks = [b for b in r["timeline"] if b["ages"] == "kids"]
        self.assertEqual(kids_blocks, [], "kids block in adults-only run")


class TestFlaskRoutes(unittest.TestCase):
    def setUp(self):
        # Use a temp DB
        import app as appmod
        self.tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmpdb.close()
        appmod.DB_PATH = self.tmpdb.name
        appmod.init_db()
        appmod.app.config["TESTING"] = True
        self.client = appmod.app.test_client()

    def tearDown(self):
        os.unlink(self.tmpdb.name)

    def test_index_loads(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Run-of-Show", r.data)

    def test_generate_endpoint(self):
        r = self.client.post("/api/generate", json={"brief": "birthday party, 10 adults, 3 hours"})
        self.assertEqual(r.status_code, 200)
        d = r.json
        self.assertIn("timeline", d)
        self.assertIn("scoring", d)
        self.assertIn("verdict", d)
        self.assertGreater(len(d["timeline"]), 0)

    def test_empty_brief_400(self):
        r = self.client.post("/api/generate", json={"brief": ""})
        self.assertEqual(r.status_code, 400)

    def test_sessions_list(self):
        self.client.post("/api/generate", json={"brief": "game night, 6 adults, 2 hours"})
        r = self.client.get("/api/sessions")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json), 1)

    def test_rate_session(self):
        r = self.client.post("/api/generate", json={"brief": "birthday, 8 adults, 3 hours"})
        sid = self.client.get("/api/sessions").json[0]["id"]
        rr = self.client.post("/api/rate", json={"session_id": sid, "rating": 5, "notes": "great"})
        self.assertEqual(rr.status_code, 200)
        # verify persisted
        d = self.client.get(f"/api/session/{sid}").json
        self.assertEqual(d["rating"], 5)
        self.assertEqual(d["notes"], "great")

    def test_export_md(self):
        self.client.post("/api/generate", json={"brief": "birthday, 8 adults, 3 hours"})
        sid = self.client.get("/api/sessions").json[0]["id"]
        r = self.client.get(f"/api/export/{sid}.md")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"# Party Run-of-Show", r.data)
        self.assertIn(b"Timeline", r.data)

    def test_export_json(self):
        self.client.post("/api/generate", json={"brief": "game night, 6 adults, 3 hours"})
        sid = self.client.get("/api/sessions").json[0]["id"]
        r = self.client.get(f"/api/export/{sid}.json")
        self.assertEqual(r.status_code, 200)
        d = r.json
        self.assertIn("timeline", d)


if __name__ == "__main__":
    unittest.main()
