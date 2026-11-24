"""Room Utilization - Offering Prioritization prototype.

Loads Curriculum, Courses, Rooms and Enrolled Students (CSV) into SQLite,
runs the v_course_room_priority view, then assigns physical rooms to the
highest-priority sections first. Sections that don't get a room fall back
to Online/Hybrid (if the course allows it) or an Alternate slot.

Usage:
    python prioritize.py [--data sample_data] [--next-term-no 2] [--next-term 2026-2]
                         [--section-size 40] [--out output]
"""
import argparse
import csv
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SQL_DIR = ROOT.parent / "sql"
TABLES = ["courses", "course_prerequisites", "curriculum", "rooms",
          "enrolled_students", "student_course_history"]


def load(conn, data_dir):
    conn.executescript((SQL_DIR / "01_schema.sql").read_text())
    for t in TABLES:
        with open(data_dir / f"{t}.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            cols = list(rows[0])
            conn.executemany(
                f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in rows])


def create_view(conn, next_term_no, next_term):
    sql = (SQL_DIR / "02_v_course_room_priority.sql").read_text()
    sql = sql.replace(":next_term_no", str(int(next_term_no)))
    sql = sql.replace(":next_term", "'" + next_term.replace("'", "''") + "'")
    conn.executescript(sql)


def allocate(conn, section_size):
    conn.row_factory = sqlite3.Row
    courses = conn.execute(
        "SELECT v.*, c.lec_hours + c.lab_hours AS weekly_hours "
        "FROM v_course_room_priority v JOIN courses c USING (course_code) "
        "ORDER BY priority_score DESC").fetchall()
    rooms = [dict(r, hours_left=r["available_hours_per_week"])
             for r in conn.execute("SELECT * FROM rooms ORDER BY capacity")]

    sections = []
    for rank, c in enumerate(courses, 1):
        # a section can't be larger than the biggest room of the required type
        max_cap = max((r["capacity"] for r in rooms if r["room_type"] == c["required_room_type"]), default=section_size)
        n_sec = math.ceil(c["total_demand"] / min(section_size, max_cap))
        base, extra = divmod(c["total_demand"], n_sec)
        for i in range(n_sec):
            size = base + (1 if i < extra else 0)
            # smallest room of the right type that fits and still has hours
            room = next((r for r in rooms
                         if r["room_type"] == c["required_room_type"]
                         and r["capacity"] >= size
                         and r["hours_left"] >= c["weekly_hours"]), None)
            if room:
                room["hours_left"] -= c["weekly_hours"]
                rec, room_id = "Physical room", room["room_id"]
            else:
                rec = "Online/Hybrid" if c["can_be_online"] == "Y" else "Alternate slot / Rotating F2F"
                room_id = ""
            sections.append({
                "rank": rank, "course_code": c["course_code"], "title": c["title"],
                "section": f"{c['course_code']}-{i + 1:02d}", "students": size,
                "room_type": c["required_room_type"], "priority_score": c["priority_score"],
                "recommendation": rec, "room_id": room_id,
                "seat_fill_pct": round(100 * size / room["capacity"], 1) if room else "",
            })
    return courses, rooms, sections


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", default=str(ROOT / "sample_data"))
    p.add_argument("--next-term-no", type=int, default=2)
    p.add_argument("--next-term", default="2026-2")
    p.add_argument("--section-size", type=int, default=40)
    p.add_argument("--out", default=str(ROOT / "output"))
    a = p.parse_args()

    conn = sqlite3.connect(":memory:")
    load(conn, Path(a.data))
    create_view(conn, a.next_term_no, a.next_term)
    courses, rooms, sections = allocate(conn, a.section_size)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "course_priority.csv", [dict(c) for c in courses])
    write_csv(out / "section_allocation.csv", sections)

    print(f"{'Rank':<5}{'Course':<10}{'Room type':<14}{'Demand':>7}{'Sect':>6}{'Grad':>6}{'Score':>7}  Recommendation")
    for rank, c in enumerate(courses, 1):
        recs = [s["recommendation"] for s in sections if s["course_code"] == c["course_code"]]
        phys = recs.count("Physical room")
        summary = ("Physical room" if phys == len(recs) else
                   f"{phys}/{len(recs)} physical, rest {next(r for r in recs if r != 'Physical room')}")
        print(f"{rank:<5}{c['course_code']:<10}{c['required_room_type']:<14}{c['total_demand']:>7}"
              f"{len(recs):>6}{c['graduating']:>6}{c['priority_score']:>7}  {summary}")

    print("\nRoom utilization")
    for r in rooms:
        used = r["available_hours_per_week"] - r["hours_left"]
        print(f"  {r['room_id']:<10} {r['room_type']:<13} {used:>3}/{r['available_hours_per_week']} h "
              f"({100 * used / r['available_hours_per_week']:.0f}%)")
    print(f"\nWrote {out / 'course_priority.csv'} and {out / 'section_allocation.csv'}")


if __name__ == "__main__":
    main()
