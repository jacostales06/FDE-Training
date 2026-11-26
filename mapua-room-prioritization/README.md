# Room Utilization: Offering Prioritization

A system design and working prototype for managing **limited physical rooms across Mapúa University campuses**. It ranks next term's course offerings so the ones that most need a physical room get one first.

> **v2 (Session 2):** adds a day/time timetable with no double-booking, campus matching, prerequisite-aware demand, configurable weights, off-peak fallback, KPIs and automated tests. See [CHANGELOG.md](CHANGELOG.md).

| | |
|---|---|
| **Stakeholders** | Students, Faculty |
| **Problem** | Limited physical rooms across campuses |
| **Input / Database** | Curriculum, Courses, Rooms, Enrolled Students |
| **Solution** | Offering Prioritization |
| **Output** | View of courses for room prioritization |

## 1. Problem framing

There are more sections to offer than physical room-hours to hold them. So the question changes from *"where do we put every class?"* to **"which course offerings deserve a physical room first?"** The rest can go to hybrid or online delivery, rotating face-to-face schedules, or off-peak slots.

**Approach:** Forecast demand → score each course offering → give rooms to the highest-priority offerings first → show the ranked results.

## 2. Data model

| Table | Key fields |
|---|---|
| **Curriculum** | program, curriculum_year, year_level, term, course_code, is_required |
| **Courses** | course_code, title, units, lec_hours, lab_hours, required_room_type, can_be_online |
| **Course prerequisites** | course_code, prereq_code |
| **Rooms** | room_id, campus, room_type, capacity, available_hours_per_week |
| **Enrolled Students** | student_no, program, curriculum_year, year_level, campus, expected_grad_term |
| **Student course history** | student_no, course_code, status (PASSED / FAILED / DROPPED) |

The full DDL is in [`sql/01_schema.sql`](sql/01_schema.sql).

## 3. Step 1: Forecast demand per course and campus

- **Regular demand:** students whose curriculum places the course in that year level and term, on their own campus.
- **Backlog demand:** students who failed or dropped the course, **counted only if they have passed every prerequisite**.
- **Blocked by prerequisite:** students who would be due for the course but failed a prerequisite. They are reported separately and don't use a seat.
- **Sections** = CEILING(demand ÷ section size). The section size is capped at the largest room of the required type on that campus.

## 4. Step 2: Priority score

Each course offering on each campus gets a weighted score from 0 to 100. The weights live in [`config/settings.json`](config/settings.json), so the Registrar can change policy without touching code. The weights must add up to 1.0.

| Factor | Why it matters | Weight |
|---|---|---|
| Graduating students' share | Graduating students can't be delayed | 25% |
| Bottleneck / prerequisite chain | How many later courses this one unlocks | 20% |
| Needs a physical room | Labs and drafting can't go online, lecture-only courses can | 20% |
| Demand size | More students affected | 15% |
| Required vs. elective | Required courses come first | 10% |
| Room-type scarcity | Demand seat-hours ÷ supply seat-hours on that campus | 10% |

This is implemented as the SQL view [`sql/02_v_course_room_priority.sql`](sql/02_v_course_room_priority.sql).

## 5. Step 3: Timetable and allocate rooms

The week is a grid of 3-hour blocks, Monday to Saturday from 07:00 to 19:00. **Prime time** is Monday to Friday, 07:00 to 16:00. Offerings are processed from the highest priority score down. Each section tries these options in order:

1. **Physical room, prime time:** the smallest room of the right type, on the student's campus, that fits the class. Its blocks fall on different days, and the room stays within its available hours.
2. **Online/Hybrid,** if the course allows it. Online is better for students than evenings or Saturdays.
3. **Physical room, off-peak:** weekday 16:00 to 19:00 or Saturday, for courses that must be face-to-face.
4. **Unmet,** with the reason (for example *"No Science Lab at Makati"*) so the planning office can act on it.

A room is never double-booked. This is enforced in code and checked by the tests.

## 6. Output: courses for room prioritization

Output of the prototype on the included sample data:

```
#  Course   Campus     Room type      Dem Grad Blk  Score  Outcome
1  CE199    Intramuros Lecture         52   52  18   66.3  2 Physical room
2  CHM101L  Intramuros Science Lab    297    7   0   51.6  12 Physical room
3  MATH141  Intramuros Lecture        303    6   0   46.3  8 Physical room
4  CHM101L  Makati     Science Lab     80    0   0   44.0  2 Unmet (No Science Lab at Makati)
5  PHY101L  Intramuros Science Lab     83    0   7   40.4  3 Physical room, 1 Physical room (off-peak)
6  CS102    Intramuros Computer Lab   130    0   0   39.1  4 Physical room
7  CS102    Makati     Computer Lab    80    0   0   36.2  2 Physical room
8  ARC110   Intramuros Drafting        60    0   0   35.8  2 Physical room
9  MATH142  Intramuros Lecture         95   12  13   30.6  3 Physical room
10 ETHICS   Intramuros Lecture        220    0   0   29.6  4 Physical room, 2 Online/Hybrid
11 MATH141  Makati     Lecture         80    0   0   27.3  2 Physical room
```

What the output shows:
- **The thesis course ranks first** because every student in it is graduating. But 18 graduating CE students are *blocked* because they failed Calculus 2. This is why MATH142 has 12 graduating students in its backlog demand.
- **Makati has no Science Lab**, so 80 Makati students need a cross-campus lab schedule or a new lab. v1 couldn't see this.
- **Lecture rooms run out,** so 2 sections of Ethics, which can be taught online, move to Online/Hybrid. Labs keep their rooms, and the lowest-priority lab section moves to off-peak.

The engine writes these files to `prototype/output/`:

| File | Contents |
|---|---|
| `course_priority.csv` | The ranked view, plus the outcome summary for each offering |
| `section_allocation.csv` | Each section with its room, schedule (for example `Mon 07:00-10:00; Tue 07:00-10:00`), seat fill and reason if unmet |
| `room_timetable.csv` | Each room's bookings by day and time block |
| `kpis.json` | The KPIs below |
| `report.md` | A ready-to-share report, the same content that gets written to Google Docs |

## 7. KPIs

Computed automatically in `kpis.json`. Values shown are for the sample data.

| KPI | Formula | Target | Sample |
|---|---|---|---|
| Room utilization rate | booked hours ÷ available hours | 75–85% | 50.5% |
| Prime-time utilization | prime blocks booked ÷ prime blocks | 75–85% | 49.5% |
| Average seat fill | students ÷ room capacity per section | at least 80% | 87.1% |
| Unmet sections and students | sections with no room and no allowed fallback | 0 | 2 sections, 80 students |
| Graduating students at risk | graduating students in unmet sections | 0 | 0 |
| Blocked by prerequisite | due students who failed a prerequisite | track | 38 |

Low utilization next to unmet demand means the **room mix**, not the number of rooms, is the problem. In the sample data, Makati has a lecture room and a computer lab but no science lab.

## 8. Running the prototype

Requires Python 3.8+ and no other dependencies. It uses the built-in `sqlite3` module.

```bash
python prototype/prioritize.py
```

```bash
python -m unittest discover -s tests -v
```

Options: `--data <folder of CSVs>`, `--config <settings.json>` and `--out <folder>`. The term, section size, weights and time grid are set in `config/settings.json`. To use real data, export your tables to CSVs with the same columns as `prototype/sample_data/`.

**Note:** The sample data is synthetic. Student numbers, enrollment counts and room IDs are made up for demonstration.

**SQL dialect:** The view uses SQLite syntax. For PostgreSQL or MySQL, replace the two-argument `MIN(x, 1)` with `LEAST(x, 1)`.

## 9. Limitations and next steps

- **Student timetable conflicts:** the engine prevents room double-booking but doesn't yet stop two required courses of the same block section from landing in the same time slot. The next step is block-section conflict constraints, for example with OR-Tools CP-SAT.
- **Faculty:** faculty loading and availability aren't modelled yet.
- **Historical rates:** demand forecasting could use pass and fail rates from past terms.

## 10. Suggested rollout

1. Clean and link the four data sources: student information system, curriculum, and room inventory.
2. Build the demand forecast and the priority view.
3. Run it on last term's data and compare against the actual schedule.
4. Have the Registrar and department chairs agree on the weights.
5. Add timetabling and a dashboard for the scheduling office.
