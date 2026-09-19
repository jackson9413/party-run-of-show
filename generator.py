"""
Generator + scoring + insights for party run-of-show.
"""
from __future__ import annotations
import re
from typing import List, Dict, Optional

from blocks import (
    BLOCKS, OCCASION_TEMPLATES, blocks_for_occasion,
    get_block, ENERGY_WARM, ENERGY_LOW, ENERGY_MID, ENERGY_HIGH, ENERGY_PEAK,
)

ENERGY_LABEL = {1: "warm", 2: "low", 3: "mid", 4: "high", 5: "peak"}
STAGE_ORDER = ["welcome", "opener", "main", "intermission", "closer", "wind_down"]
STAGE_LABEL = {
    "welcome": "Welcome",
    "opener": "Opener",
    "main": "Main event",
    "intermission": "Intermission",
    "closer": "Closer",
    "wind_down": "Wind-down",
}


# ---------- PARSING ----------
def parse_brief(text: str) -> Dict:
    """
    Parse free-form brief to extract overrides. Returns dict with keys:
      occasion, group_size, ages, total_minutes, energy_target, conflict_safe, no_block_ids, required_block_ids
    """
    info = {
        "occasion": None,
        "group_size": None,
        "ages": None,
        "total_minutes": None,
        "energy_target": None,
        "conflict_safe": None,
        "no_block_ids": [],
        "required_block_ids": [],
    }
    t = text.lower()

    # occasion — order matters: more specific first
    occ_aliases = [
        ("kids party", "kids_party"), ("kid party", "kids_party"), ("kid's party", "kids_party"),
        ("children", "kids_party"), (" for kids", "kids_party"),
        ("game night", "game_night"), ("games night", "game_night"),
        ("dinner party", "dinner_party"),
        ("christmas", "holiday"), ("thanksgiving", "holiday"), ("easter", "holiday"), ("hanukkah", "holiday"),
        ("new year", "holiday"), ("fourth of july", "holiday"), ("4th of july", "holiday"),
        ("holiday", "holiday"),
        ("couples night", "couples_night"), ("date night", "couples_night"),
        ("work offsite", "work_offsite"), ("team offsite", "work_offsite"), ("team social", "work_offsite"),
        ("offsite", "work_offsite"),
        ("reunion", "reunion"),
        ("birthday", "birthday"), ("bday", "birthday"), ("b-day", "birthday"),
    ]
    for alias, key in occ_aliases:
        if alias in t:
            info["occasion"] = key
            break

    # group size
    m = re.search(r"(\d{1,3})\s*(?:people|guests|ppl|friends|adults|kids|people|persons?|of us)", t)
    if m:
        info["group_size"] = int(m.group(1))
    else:
        m2 = re.search(r"(?:group|party) of (\d{1,3})", t)
        if m2:
            info["group_size"] = int(m2.group(1))

    # ages
    if re.search(r"\b(kids?|children|child|6[-\s]year|8[-\s]year|10[-\s]year|12[-\s]year|tweens?)\b", t):
        info["ages"] = "kids"
    elif re.search(r"\b(teens?|teenagers?)\b", t) and not re.search(r"\b(kids?|children)\b", t):
        info["ages"] = "adults_teens"
    else:
        info["ages"] = "adults_teens"  # default

    # total minutes
    m = re.search(r"(\d{1,3})\s*(?:min(?:ute)?s?|m\b)", t)
    if m:
        info["total_minutes"] = int(m.group(1))
    else:
        # decimal hours like "2.5 hours"
        m2 = re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr|h\b)", t)
        if m2:
            info["total_minutes"] = int(float(m2.group(1)) * 60)
        else:
            m3 = re.search(r"(\d{1,2})\s*(?:pm)\s*[-–to]+\s*(\d{1,2})\s*(?:pm|am)", t)
            if m3:
                start = int(m3.group(1))
                end = int(m3.group(2))
                info["total_minutes"] = max(0, (end - start) % 12) * 60 or 180

    # energy target
    if re.search(r"\b(low[- ]?key|chill|calm|relaxed|intimate)\b", t):
        info["energy_target"] = "low"
    elif re.search(r"\b(wild|loud|high[- ]?energy|peak|chaotic|rave)\b", t):
        info["energy_target"] = "high"
    elif re.search(r"\b(mid|medium|balanced|normal)\b", t):
        info["energy_target"] = "mid"
    elif re.search(r"\b(warm|cozy|soft)\b", t):
        info["energy_target"] = "warm"

    # conflict-safe (overrides defaults)
    if re.search(r"\b(coworkers?|colleagues?|boss|client|work|in[- ]?laws|parents)\b", t):
        info["conflict_safe"] = True
    if re.search(r"\b(conflict|fight|safety[- ]?first|no[- ]?red[- ]?flags)\b", t):
        info["conflict_safe"] = True

    return info


def merge_defaults(parsed: Dict) -> Dict:
    """Apply occasion template defaults to parsed info."""
    occ = parsed.get("occasion") or "birthday"
    tmpl = OCCASION_TEMPLATES[occ]
    out = dict(parsed)
    out["occasion"] = occ
    if out.get("group_size") is None:
        out["group_size"] = tmpl["default_group_size"]
    if out.get("ages") is None:
        out["ages"] = tmpl["ages"]
    if out.get("total_minutes") is None:
        out["total_minutes"] = tmpl["default_minutes"]
    if out.get("energy_target") is None:
        out["energy_target"] = tmpl["default_energy_target"]
    return out


# ---------- SCORING (used for ranking eligible blocks) ----------
def block_eligibility_score(block: Dict, info: Dict) -> float:
    """Higher = better fit. Pure heuristic, no LLM."""
    occ = info["occasion"]
    tmpl = OCCASION_TEMPLATES[occ]
    score = 0.0

    # group size sweet spot: 1.0 if at center, drops to 0.4 if at edge
    gs = info["group_size"]
    if block["min_group"] <= gs <= block["max_group"]:
        mid = (block["min_group"] + block["max_group"]) / 2
        spread = (block["max_group"] - block["min_group"]) / 2 or 1
        dist = abs(gs - mid) / spread
        score += 1.0 - 0.6 * dist
    else:
        score -= 2.0

    # ages match
    if block["ages"] == "all":
        score += 0.4
    elif block["ages"] == info["ages"]:
        score += 1.0
    else:
        score -= 1.5  # kids-coded block in adults-only occasion, etc.

    # occasion match (already filtered, but bonus if explicit match)
    if occ in block["occasions"]:
        score += 0.5

    # conflict-safety
    if info.get("conflict_safe") and not block["conflict_safe"]:
        score -= 1.0

    # energy target alignment
    target = info["energy_target"]
    target_e = {"warm": ENERGY_WARM, "low": ENERGY_LOW, "mid": ENERGY_MID, "high": ENERGY_HIGH, "peak": ENERGY_PEAK}.get(target, ENERGY_MID)
    e_diff = abs(block["energy"] - target_e)
    score += max(0, 1.5 - e_diff * 0.5)

    return score


# ---------- GENERATION ----------
def generate_run_of_show(info: Dict) -> Dict:
    """Build a run-of-show fitting the user's window."""
    occ = info["occasion"]
    tmpl = OCCASION_TEMPLATES[occ]
    total_min = info["total_minutes"]
    group_size = info["group_size"]
    ages = info["ages"]

    # Eligibility list
    eligible = [b for b in blocks_for_occasion(occ)
                if b["min_group"] <= group_size <= b["max_group"]
                and (b["ages"] == "all" or b["ages"] == ages)
                and b["id"] not in tmpl["forbidden_block_ids"]
                and not (info.get("conflict_safe") and not b["conflict_safe"])]

    by_stage: Dict[str, List[Dict]] = {s: [] for s in STAGE_ORDER}
    for b in eligible:
        by_stage[b["stage"]].append(b)

    # Required blocks first
    chosen: List[Dict] = []
    chosen_ids = set()
    for rid in tmpl["required_block_ids"]:
        b = get_block(rid)
        if b and b["id"] not in chosen_ids and b in eligible:
            chosen.append(b)
            chosen_ids.add(b["id"])

    # Stage budget — proportional to stage importance
    n_stages = len(tmpl["must_include_stages"])
    minutes_left = total_min
    required_remaining = [b for b in chosen]
    minutes_consumed = sum(b["default_minutes"] for b in required_remaining)
    minutes_left -= minutes_consumed

    # Allocate roughly: opener 12%, main 50%, intermission 13%, closer 10%, wind-down 10%, welcome 5%
    stage_budget_share = {
        "welcome": 0.05,
        "opener": 0.12,
        "main": 0.50,
        "intermission": 0.13,
        "closer": 0.10,
        "wind_down": 0.10,
    }
    stage_budgets = {s: max(0, int(minutes_left * stage_budget_share.get(s, 0.10))) for s in tmpl["must_include_stages"]}
    # Give any unallocated time to main (most flexible stage)
    total_alloc = sum(stage_budgets.values())
    if total_alloc < minutes_left - 5:
        stage_budgets["main"] = stage_budgets.get("main", 0) + (minutes_left - total_alloc)

    # For each required stage, pick blocks greedily until stage budget met or 3 blocks max
    chosen_energy_arc = [b["energy"] for b in chosen]

    for stage in tmpl["must_include_stages"]:
        if stage == "welcome" and any(b["stage"] == stage for b in chosen):
            # already filled by required
            continue
        budget = stage_budgets.get(stage, max(10, int(minutes_left / max(1, len(tmpl["must_include_stages"])))))
        ranked = sorted(by_stage[stage], key=lambda b: -block_eligibility_score(b, info))
        stage_minutes = 0
        picked_any = False
        for idx, b in enumerate(ranked):
            if b["id"] in chosen_ids:
                continue
            if stage_minutes + b["default_minutes"] > budget + 15 and picked_any:
                # budget met; stop adding
                break
            # Avoid same-energy as last chosen block unless we're stuck
            if chosen_energy_arc and b["energy"] == chosen_energy_arc[-1] and stage_minutes < budget * 0.8:
                # try to swap with a different-energy block from the rest
                swapped = False
                for alt in ranked[idx + 1:]:
                    if alt["id"] in chosen_ids:
                        continue
                    if alt["energy"] != chosen_energy_arc[-1]:
                        b = alt
                        swapped = True
                        break
                if not swapped and len(ranked) <= idx + 1:
                    # no alternative available — accept the same-energy block
                    pass
            chosen.append(b)
            chosen_ids.add(b["id"])
            chosen_energy_arc.append(b["energy"])
            stage_minutes += b["default_minutes"]
            picked_any = True
            # Stop only when we hit 1.5x the budget (allows filling if more blocks exist)
            if stage_minutes >= budget * 1.5:
                break
            # Stop earlier only if we've well-exceeded
            if stage_minutes >= budget and idx >= len(ranked) - 1:
                break

    # Sort chosen by STAGE_ORDER
    chosen.sort(key=lambda b: (STAGE_ORDER.index(b["stage"]), -b["energy"]))

    # If we still have leftover time, add an extra main block from any unused main candidate
    minutes_used = sum(b["default_minutes"] for b in chosen)
    if minutes_used < total_min - 30:
        for b in sorted(blocks_for_occasion(occ), key=lambda b: -block_eligibility_score(b, info)):
            if b["id"] in chosen_ids:
                continue
            if not (b["min_group"] <= group_size <= b["max_group"]):
                continue
            if b["ages"] != "all" and b["ages"] != ages:
                continue
            idx = next((i for i, x in enumerate(chosen) if x["stage"] == "main"), None)
            if idx is not None:
                chosen.insert(idx + 1, b)
                chosen_ids.add(b["id"])
                break

    # Compute timing
    start_offset = 0
    timeline = []
    for b in chosen:
        timeline.append({
            "id": b["id"],
            "stage": b["stage"],
            "stage_label": STAGE_LABEL[b["stage"]],
            "title": b["title"],
            "energy": b["energy"],
            "energy_label": ENERGY_LABEL[b["energy"]],
            "minutes": b["default_minutes"],
            "materials": b["materials"],
            "rationale": b["rationale"],
            "noise": b["noise"],
            "conflict_safe": b["conflict_safe"],
            "min_group": b["min_group"],
            "max_group": b["max_group"],
            "ages": b["ages"],
            "occasions": b["occasions"],
            "start_offset": start_offset,
            "end_offset": start_offset + b["default_minutes"],
        })
        start_offset += b["default_minutes"]

    # Compute total minutes actually used
    actual_minutes = sum(b["minutes"] for b in timeline)

    # Trim or pad: if over total_min by >15min, drop the last wind_down block
    while actual_minutes > total_min + 15 and len(timeline) > 2:
        last = timeline.pop()
        if last["stage"] == "wind_down":
            actual_minutes -= last["minutes"]
            if actual_minutes <= total_min + 5:
                break
        else:
            actual_minutes -= last["minutes"]
            if actual_minutes <= total_min:
                break

    # Score
    scoring = score_run_of_show(info, timeline)

    # Insights & flags
    insights = build_insights(info, timeline, scoring)
    flags = build_flags(info, timeline, scoring)

    return {
        "input": info,
        "template": tmpl["label"],
        "requested_minutes": total_min,
        "actual_minutes": actual_minutes,
        "block_count": len(timeline),
        "timeline": timeline,
        "scoring": scoring,
        "verdict": verdict_for(scoring["overall"]),
        "insights": insights,
        "flags": flags,
    }


def score_run_of_show(info: Dict, timeline: List[Dict]) -> Dict:
    """0-100 across 5 axes."""
    occ = info["occasion"]
    tmpl = OCCASION_TEMPLATES[occ]
    axes = {}

    # 1. Occasion Fit — required blocks present, no forbidden blocks
    required_present = sum(1 for rid in tmpl["required_block_ids"] if any(b["id"] == rid for b in timeline))
    required_total = len(tmpl["required_block_ids"])
    required_score = 100 if required_total == 0 else 100 * required_present / required_total

    stages_present = {b["stage"] for b in timeline}
    stages_needed = set(tmpl["must_include_stages"])
    stage_coverage = 100 * len(stages_present & stages_needed) / max(1, len(stages_needed))
    axes["occasion_fit"] = round(min(100, 0.5 * required_score + 0.5 * stage_coverage), 1)

    # 2. Energy Arc — checks for monotonic rise-then-fall, no two adjacent same-energy
    energies = [b["energy"] for b in timeline]
    if not energies:
        arc_score = 0
    else:
        # find peak position
        peak_idx = energies.index(max(energies))
        n = len(energies)
        # ideal: rising then falling, peak near 60-75% through
        ideal_peak_pct = 0.65
        actual_peak_pct = peak_idx / max(1, n - 1)
        peak_dist = abs(actual_peak_pct - ideal_peak_pct)
        peak_score = max(0, 100 - peak_dist * 100)

        # penalty for two adjacent same-energy blocks
        adj_penalty = 0
        for i in range(1, n):
            if energies[i] == energies[i - 1]:
                adj_penalty += 15
        adj_penalty = min(60, adj_penalty)

        # check monotonic-ish: variance of prefix (rising) + suffix (falling) decline
        if peak_idx > 0:
            prefix = energies[: peak_idx + 1]
            rises = sum(1 for i in range(1, len(prefix)) if prefix[i] >= prefix[i - 1])
            rise_pct = rises / max(1, len(prefix) - 1)
        else:
            rise_pct = 1.0
        if peak_idx < n - 1:
            suffix = energies[peak_idx:]
            falls = sum(1 for i in range(1, len(suffix)) if suffix[i] <= suffix[i - 1])
            fall_pct = falls / max(1, len(suffix) - 1)
        else:
            fall_pct = 1.0
        shape_score = 100 * 0.5 * (rise_pct + fall_pct)

        arc_score = 0.4 * peak_score + 0.4 * shape_score + 0.2 * max(0, 100 - adj_penalty)
    axes["energy_arc"] = round(min(100, max(0, arc_score)), 1)

    # 3. Timing Fit — actual vs requested
    actual = sum(b["minutes"] for b in timeline)
    requested = info["total_minutes"]
    if requested == 0:
        timing_score = 50
    else:
        diff_pct = abs(actual - requested) / requested
        timing_score = max(0, 100 - diff_pct * 100)
    axes["timing_fit"] = round(timing_score, 1)

    # 4. Group Fit — block group sizes cover the actual group size
    gs = info["group_size"]
    fits = [b for b in timeline if b["min_group"] <= gs <= b["max_group"]]
    axes["group_fit"] = round(min(100, 100 * len(fits) / max(1, len(timeline))), 1)

    # 5. Conflict Safety — proportion of conflict-safe blocks
    if info.get("conflict_safe"):
        safe_count = sum(1 for b in timeline if b["conflict_safe"])
        axes["conflict_safety"] = round(min(100, 100 * safe_count / max(1, len(timeline))), 1)
    else:
        axes["conflict_safety"] = 100  # not relevant

    # Weighted composite
    weights = {
        "occasion_fit": 0.30,
        "energy_arc": 0.25,
        "timing_fit": 0.20,
        "group_fit": 0.15,
        "conflict_safety": 0.10,
    }
    overall = sum(axes[k] * weights[k] for k in weights)
    return {
        "axes": axes,
        "weights": weights,
        "overall": round(min(100, max(0, overall)), 1),
    }


def verdict_for(score: float) -> str:
    if score >= 85:
        return "Showtime Ready"
    if score >= 70:
        return "Solid Run-of-Show"
    if score >= 55:
        return "Workable — Tighten Timing"
    if score >= 40:
        return "Sketchy — Re-plan Stages"
    return "Better Reschedule"


# ---------- INSIGHTS & FLAGS ----------
def build_insights(info: Dict, timeline: List[Dict], scoring: Dict) -> List[str]:
    out = []
    actual = sum(b["minutes"] for b in timeline)
    requested = info["total_minutes"]
    if actual > requested + 5:
        out.append(f"Run-of-show is {actual - requested} min over your {requested}-min window — consider trimming wind-down or splitting into two nights.")
    elif actual < requested - 30:
        out.append(f"Run-of-show is {requested - actual} min under your {requested}-min window — add a wind-down cluster or a board-game backup block.")
    else:
        out.append(f"Timing fits your {requested}-min window cleanly ({actual} min total).")

    energies = [b["energy"] for b in timeline]
    if energies:
        peak_idx = energies.index(max(energies))
        peak_block = timeline[peak_idx]
        if peak_idx / max(1, len(timeline) - 1) < 0.4:
            out.append(f"Peak ({peak_block['title']}) is too early — guests peak before they've warmed up. Move a high-energy block to 60–70% through.")
        elif peak_idx / max(1, len(timeline) - 1) > 0.8:
            out.append(f"Peak ({peak_block['title']}) lands at the very end — leaves no wind-down runway. Move it 15 min earlier.")
        else:
            out.append(f"Energy peak ({peak_block['title']}) lands at {int(peak_idx / max(1, len(timeline) - 1) * 100)}% — solid arc placement.")

    occ = info["occasion"]
    tmpl = OCCASION_TEMPLATES[occ]
    if tmpl["required_block_ids"]:
        for rid in tmpl["required_block_ids"]:
            if not any(b["id"] == rid for b in timeline):
                out.append(f"Missing required block for {tmpl['label']}: '{get_block(rid)['title']}'.")

    n_kids = sum(1 for b in timeline if b["ages"] == "kids")
    if info["ages"] != "kids" and n_kids > 0:
        out.append(f"{n_kids} kid-coded block(s) included — confirm kids are welcome; otherwise swap for adults_teens blocks.")

    return out


def build_flags(info: Dict, timeline: List[Dict], scoring: Dict) -> List[str]:
    flags = []
    occ = info["occasion"]
    tmpl = OCCASION_TEMPLATES[occ]
    # forbidden blocks present
    for fid in tmpl["forbidden_block_ids"]:
        if any(b["id"] == fid for b in timeline):
            flags.append(f"'{get_block(fid)['title']}' is unusual for {tmpl['label']} — confirm it's intentional.")

    # kids-coded in adults occasion
    if info["ages"] != "kids":
        for b in timeline:
            if b["ages"] == "kids":
                flags.append(f"Block '{b['title']}' is kids-only — swap for an adults_teens alternative.")

    # adjacent same-energy
    for i in range(1, len(timeline)):
        if timeline[i]["energy"] == timeline[i - 1]["energy"]:
            flags.append(f"Two adjacent blocks share the same energy level: '{timeline[i-1]['title']}' → '{timeline[i]['title']}'. Mix it up.")

    # conflict safety override
    if info.get("conflict_safe"):
        unsafe = [b for b in timeline if not b["conflict_safe"]]
        if unsafe:
            flags.append(f"{len(unsafe)} block(s) flagged conflict-risky under your safe-only setting — review: " + ", ".join(b["title"] for b in unsafe[:3]))

    # group over/under block sweet spot
    gs = info["group_size"]
    out_of_range = [b for b in timeline if not (b["min_group"] <= gs <= b["max_group"])]
    if out_of_range:
        flags.append(f"{len(out_of_range)} block(s) sized for a different group range — review.")

    # no required closer stage
    if "closer" in tmpl["must_include_stages"] and not any(b["stage"] == "closer" for b in timeline):
        flags.append("No closer block scheduled — guests won't have a clear 'peak moment' to anchor the night.")

    return flags
