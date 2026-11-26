"""Room Utilization - Offering Prioritization engine (v2).

Pipeline:
  1. Load Curriculum, Courses, Rooms, Enrolled Students (+ prerequisites, course history) from CSV.
  2. Run the SQL view v_course_room_priority -> one ranked row per course offering per campus.
  3. Timetable sections into day/time blocks, highest priority first:
       prime time (Mon-Fri 07:00-16:00) -> Online/Hybrid if the course allows it
       -> off-peak (weekday evenings, Saturday) -> Unmet.
     Rooms are never double-booked, must match room type, campus and capacity,
     and stay within their available hours per week.
  4. Write course_priority.csv, section_allocation.csv, room_timetable.csv, kpis.json, report.md.

Usage:
    python prioritize.py [--data DIR] [--config FILE] [--out DIR]
"""
import argparse
import csv
import json
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
TABLES = ["courses", "course_prerequisites", "curriculum", "rooms",
          "enrolled_students", "student_course_history"]

PHYSICAL, OFFPEAK, ONLINE, UNMET = "Physical room", "Physical room (off-peak)", "Online/Hybrid", "Unmet"


# ---------------------------------------------------------------- data + view
def load_config(path):
    cfg = json.loads(Path(path).read_text())
    total = round(sum(cfg["weights"].values()), 6)
    if total != 1:
        raise ValueError(f"weights must sum to 1.0, got {total}")
    return cfg


def build_db(data_dir, cfg):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((PROJECT / "sql" / "01_schema.sql").read_text())
    for t in TABLES:
        with open(Path(data_dir) / f"{t}.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            cols = list(rows[0])
            conn.executemany(
                f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in rows])

    params = {"next_term_no": int(cfg["next_term_no"]),
              "next_term": "'" + str(cfg["next_term"]).replace("'", "''") + "'",
              "section_size": int(cfg["section_size"])}
    params.update({f"w_{k}": float(v) for k, v in cfg["weights"].items()})
    sql = (PROJECT / "sql" / "02_v_course_room_priority.sql").read_text()
    for k in sorted(params, key=len, reverse=True):      # longest first: :next_term_no before :next_term
        sql = sql.replace(f":{k}", str(params[k]))
    conn.executescript(sql)
    return conn


# ---------------------------------------------------------------- timetabling
class Room:
    def __init__(self, row, slots, block_hours):
        self.id, self.campus, self.type = row["room_id"], row["campus"], row["room_type"]
        self.capacity = row["capacity"]
        self.max_blocks = row["available_hours_per_week"] // block_hours
        self.free = list(slots)          # ordered: prime first, then off-peak
        self.booked = {}                 # slot -> section id

    def pick(self, n_blocks, allowed):
        """Pick n free slots on different days from `allowed`, or None."""
        if len(self.booked) + n_blocks > self.max_blocks:
            return None
        chosen, days = [], set()
        for s in self.free:
            if s in allowed and s[0] not in days:
                chosen.append(s)
                days.add(s[0])
                if len(chosen) == n_blocks:
                    return chosen
        return None

    def book(self, slots, section_id):
        for s in slots:
            self.free.remove(s)
            self.booked[s] = section_id


def allocate(conn, cfg):
    bh = cfg["block_hours"]
    prime = [(d, b) for d in cfg["prime_days"] for b in cfg["prime_blocks"]]
    allslots = [(d, b) for d in cfg["days"] for b in cfg["blocks"]]
    offpeak = [s for s in allslots if s not in prime]
    prime_set, all_set = set(prime), set(allslots)

    rooms = [Room(r, prime + offpeak, bh)
             for r in conn.execute("SELECT * FROM rooms ORDER BY capacity, room_id")]
    offerings = [dict(r) for r in conn.execute(
        "SELECT * FROM v_course_room_priority ORDER BY priority_score DESC, course_code, campus")]

    sections = []
    for rank, o in enumerate(offerings, 1):
        o["rank"] = rank
        candidates = [r for r in rooms if r.type == o["required_room_type"] and r.campus == o["campus"]]
        max_cap = max((r.capacity for r in candidates), default=cfg["section_size"])
        n_sec = math.ceil(o["total_demand"] / min(cfg["section_size"], max_cap))
        base, extra = divmod(o["total_demand"], n_sec)
        n_blocks = math.ceil(o["weekly_hours"] / bh)

        for i in range(n_sec):
            size = base + (1 if i < extra else 0)
            sid = f"{o['course_code']}-{o['campus'][:3].upper()}{i + 1:02d}"
            fits = [r for r in candidates if r.capacity >= size]
            outcome, room, slots = None, None, None

            for allowed, label in ((prime_set, PHYSICAL), (all_set, OFFPEAK)):
                if label == OFFPEAK and o["can_be_online"] == "Y":
                    outcome = ONLINE           # online beats evenings/Saturdays for online-capable courses
                    break
                for r in fits:
                    slots = r.pick(n_blocks, allowed)
                    if slots:
                        room, outcome = r, label
                        break
                if room:
                    break
            if room:
                room.book(slots, sid)
            elif outcome is None:
                outcome = UNMET

            reason = ""
            if outcome == UNMET:
                reason = (f"No {o['required_room_type']} at {o['campus']}" if not candidates
                          else "All matching rooms full")
            sections.append({
                "rank": rank, "section": sid, "course_code": o["course_code"], "title": o["title"],
                "campus": o["campus"], "students": size, "room_type": o["required_room_type"],
                "priority_score": o["priority_score"], "outcome": outcome,
                "room_id": room.id if room else "",
                "schedule": "; ".join(f"{d} {b}" for d, b in slots) if room else "",
                "seat_fill_pct": round(100 * size / room.capacity, 1) if room else "",
                "note": reason,
            })
    return offerings, rooms, sections


# ---------------------------------------------------------------- KPIs + output
def kpis(cfg, offerings, rooms, sections):
    bh = cfg["block_hours"]
    prime_n = len(cfg["prime_days"]) * len(cfg["prime_blocks"])
    used = sum(len(r.booked) for r in rooms) * bh
    avail = sum(min(r.max_blocks, len(cfg["days"]) * len(cfg["blocks"])) for r in rooms) * bh
    prime_used = sum(1 for r in rooms for (d, b) in r.booked
                     if d in cfg["prime_days"] and b in cfg["prime_blocks"])
    placed = [s for s in sections if s["room_id"]]
    unmet = [s for s in sections if s["outcome"] == UNMET]
    grads_at_risk = 0
    for o in offerings:
        secs = [s for s in sections if s["rank"] == o["rank"]]
        unmet_students = sum(s["students"] for s in secs if s["outcome"] == UNMET)
        grads_at_risk += round(o["graduating"] * unmet_students / o["total_demand"])
    count = lambda label: sum(1 for s in sections if s["outcome"] == label)
    return {
        "offerings": len(offerings),
        "sections": len(sections),
        "sections_physical_prime": count(PHYSICAL),
        "sections_physical_offpeak": count(OFFPEAK),
        "sections_online_hybrid": count(ONLINE),
        "sections_unmet": len(unmet),
        "students_unmet": sum(s["students"] for s in unmet),
        "graduating_students_at_risk": grads_at_risk,
        "students_blocked_by_prereq": sum(o["prereq_blocked"] for o in offerings),
        "room_utilization_pct": round(100 * used / avail, 1) if avail else 0,
        "prime_time_utilization_pct": round(100 * prime_used / (prime_n * len(rooms)), 1) if rooms else 0,
        "avg_seat_fill_pct": round(sum(s["seat_fill_pct"] for s in placed) / len(placed), 1) if placed else 0,
    }


def outcome_summary(o, sections):
    secs = [s for s in sections if s["rank"] == o["rank"]]
    parts = []
    for label in (PHYSICAL, OFFPEAK, ONLINE, UNMET):
        n = sum(1 for s in secs if s["outcome"] == label)
        if n:
            parts.append(f"{n} {label}")
    note = next((s["note"] for s in secs if s["note"]), "")
    return ", ".join(parts) + (f" ({note})" if note else "")


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def report_md(cfg, offerings, rooms, sections, k):
    lines = [f"# Room Prioritization Report: Term {cfg['next_term']}", "",
             "## KPIs", "",
             "| KPI | Value |", "|---|---|"]
    labels = {
        "sections": "Sections planned", "sections_physical_prime": "Physical, prime time",
        "sections_physical_offpeak": "Physical, off-peak", "sections_online_hybrid": "Online/Hybrid",
        "sections_unmet": "Unmet sections", "students_unmet": "Students without a room",
        "graduating_students_at_risk": "Graduating students at risk",
        "students_blocked_by_prereq": "Students blocked by a failed prerequisite",
        "room_utilization_pct": "Room utilization (%)", "prime_time_utilization_pct": "Prime-time utilization (%)",
        "avg_seat_fill_pct": "Average seat fill (%)"}
    lines += [f"| {labels[key]} | {k[key]} |" for key in labels]
    lines += ["", "## Courses for room prioritization", "",
              "| Rank | Course | Campus | Room type | Demand | Grad | Blocked | Score | Outcome |",
              "|---|---|---|---|---|---|---|---|---|"]
    for o in offerings:
        lines.append(f"| {o['rank']} | {o['course_code']} | {o['campus']} | {o['required_room_type']} | "
                     f"{o['total_demand']} | {o['graduating']} | {o['prereq_blocked']} | "
                     f"{o['priority_score']} | {o['outcome']} |")
    return "\n".join(lines) + "\n"


def run(data_dir, config_path, out_dir):
    cfg = load_config(config_path)
    conn = build_db(data_dir, cfg)
    offerings, rooms, sections = allocate(conn, cfg)
    for o in offerings:
        o["outcome"] = outcome_summary(o, sections)
    k = kpis(cfg, offerings, rooms, sections)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "course_priority.csv", offerings)
    write_csv(out / "section_allocation.csv", sections)
    write_csv(out / "room_timetable.csv",
              [{"room_id": r.id, "campus": r.campus, "day": d, "time": b, "section": sid}
               for r in rooms for (d, b), sid in sorted(r.booked.items())])
    (out / "kpis.json").write_text(json.dumps(k, indent=2))
    (out / "report.md").write_text(report_md(cfg, offerings, rooms, sections, k))
    return cfg, offerings, rooms, sections, k


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", default=str(ROOT / "sample_data"))
    p.add_argument("--config", default=str(PROJECT / "config" / "settings.json"))
    p.add_argument("--out", default=str(ROOT / "output"))
    a = p.parse_args()
    cfg, offerings, rooms, sections, k = run(a.data, a.config, a.out)

    print(f"{'#':<3}{'Course':<9}{'Campus':<11}{'Room type':<13}{'Dem':>5}{'Grad':>5}{'Blk':>4}{'Score':>7}  Outcome")
    for o in offerings:
        print(f"{o['rank']:<3}{o['course_code']:<9}{o['campus']:<11}{o['required_room_type']:<13}"
              f"{o['total_demand']:>5}{o['graduating']:>5}{o['prereq_blocked']:>4}{o['priority_score']:>7}  {o['outcome']}")
    print("\nKPIs")
    for key, v in k.items():
        print(f"  {key:<30} {v}")
    print(f"\nOutputs written to {a.out}")


if __name__ == "__main__":
    main()
