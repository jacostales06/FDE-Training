# Changelog

## v2 (Session 2): from ranking to a working timetable

Compare with Session 1: [`c2fbc0a...main`](https://github.com/jacostales06/FDE-Training/compare/c2fbc0a...main)

| Area | Session 1 (v1) | Session 2 (v2) |
|---|---|---|
| **Scheduling** | Counted weekly room-hours only. Two sections could use the same room at the same time. | Real Mon–Sat timetable of 3-hour blocks. Each section gets a room, days and times. A room is never double-booked. |
| **Campus** | Ignored. A Makati student could be "given" an Intramuros room. | Demand and rooms are matched by campus. Missing room types are flagged, for example *No Science Lab at Makati*. |
| **Prerequisites** | Every failed student was counted as backlog demand. | Backlog is counted only if all prerequisites were passed. Students blocked by a failed prerequisite are reported separately: 18 graduating CE students can't take thesis. |
| **Fallbacks** | Physical, or a text label. | Prime-time room → Online/Hybrid (if allowed) → off-peak room (evenings or Saturday) → Unmet with a reason. |
| **Policy weights** | Hard-coded in SQL. | `config/settings.json`, checked to add up to 1.0. The Registrar can change them without code. |
| **KPIs** | Described in the README. | Computed every run in `kpis.json`: utilization, prime-time use, seat fill, unmet, graduating students at risk, prerequisite-blocked. |
| **Outputs** | 2 CSVs. | Ranked view, section allocation with schedule, room timetable, KPIs, Markdown report. |
| **Reporting** | Terminal only. | Report published to Google Docs through MCP, for stakeholders who don't use GitHub. |
| **Quality** | Checked by hand. | 9 automated tests: no double-booking; room type, campus and capacity match; hours cap; every student placed; online only where allowed; prerequisite logic; weights validation. |
| **Bug fixed** | Sections could exceed lab capacity. In the first run, 37 students were put in 30-seat labs. | Section size is capped by the largest matching room on that campus. This is covered by a test. |

## v1 (Session 1)

- Schema for Curriculum, Courses, Rooms and Enrolled Students
- SQL view `v_course_room_priority` with a 6-factor weighted score
- Greedy room allocation prototype with sample data
