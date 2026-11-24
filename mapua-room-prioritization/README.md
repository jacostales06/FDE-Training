# Room Utilization: Offering Prioritization

A system design and working prototype for managing **limited physical rooms across Mapúa University campuses**. It ranks next term's course offerings so the ones that most need a physical room get one first.

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

## 3. Step 1: Forecast demand per course

- **Regular demand:** students whose curriculum places the course in that year level and term.
- **Backlog demand:** students who failed or dropped the course and need to retake it.
- **Sections needed** = CEILING(demand ÷ section size). The section size is capped at the largest room of the required type.

## 4. Step 2: Priority score

Each course offering gets a weighted score from 0 to 100. The weights are policy choices that the Registrar or Academic Affairs can adjust.

| Factor | Why it matters | Weight |
|---|---|---|
| Graduating students' share | Graduating students can't be delayed | 25% |
| Bottleneck / prerequisite chain | How many later courses this one unlocks | 20% |
| Needs a physical room | Labs and drafting can't go online, lecture-only courses can | 20% |
| Demand size | More students affected | 15% |
| Required vs. elective | Required courses come first | 10% |
| Room-type scarcity | Demand-hours ÷ supply-hours for that room type | 10% |

```
Priority Score = 100 × Σ (weight × normalized factor in 0–1)
```

This is implemented as the SQL view [`sql/02_v_course_room_priority.sql`](sql/02_v_course_room_priority.sql).

## 5. Step 3: Allocate rooms

1. Sort offerings by Priority Score, highest first.
2. For each section, assign the **smallest room of the right type that fits the class and still has weekly hours left**.
3. Subtract the room-hours used.
4. When room-hours run out, label the remaining sections by fallback:
   - `can_be_online = Y` → **Online/Hybrid**
   - otherwise → **Alternate slot / Rotating face-to-face** (evening or Saturday slots, or Group A/B alternating weeks)

## 6. Output: courses for room prioritization

Output of the prototype on the included sample data:

```
Rank Course    Room type      Demand  Sect  Grad  Score  Recommendation
1    CE199     Lecture            70     2    70   68.5  Physical room
2    MATH141   Lecture           302     8     7   47.6  Physical room
3    CHM101L   Chem Lab          183     7    15   45.0  Physical room
4    CS102     Computer Lab      130     4     0   39.2  Physical room
5    PHY101L   Physics Lab        90     3     0   36.3  Physical room
6    ARC110    Drafting           60     2     0   35.8  Physical room
7    ETHICS    Lecture           220     6     0   30.9  4/6 physical, rest Online/Hybrid
8    MATH142   Lecture            90     3     0   28.5  0/3 physical, rest Online/Hybrid
```

The thesis course, where every student is graduating, is ranked first. Labs keep their rooms. When lecture rooms run out, the lecture courses that can go online move to Online/Hybrid.

Suggested filters for a dashboard: campus, program, term, room type, and recommendation.

## 7. KPIs

| KPI | Formula | Target |
|---|---|---|
| Room utilization rate | scheduled hours ÷ available hours | 75–85% |
| Seat fill rate | enrolled ÷ room capacity per section | at least 80% |
| Unmet physical demand | high-priority sections left without a room | 0 |
| Graduating students delayed | graduating students affected by non-offering | 0 |

## 8. Running the prototype

Requires Python 3.8+ and no other dependencies. It uses the built-in `sqlite3` module.

```bash
python prototype/prioritize.py
```

Options: `--data <folder of CSVs>`, `--next-term-no 2`, `--next-term 2026-2`, `--section-size 40`, `--out <folder>`.

It writes `output/course_priority.csv` (the ranked view) and `output/section_allocation.csv` (the room or fallback for each section). To use real data, export your tables to CSVs with the same columns as `prototype/sample_data/`.

**Note:** The sample data is synthetic. Student numbers, enrollment counts and room IDs are made up for demonstration.

**SQL dialect:** The view uses SQLite syntax. For PostgreSQL or MySQL, replace the two-argument `MIN(x, 1)` with `LEAST(x, 1)`. For SQL Server, use a `CASE` expression instead.

## 9. Limitations and next steps

- Allocation counts weekly room-hours but doesn't build a timetable yet. The next step is adding day and time slots, faculty availability, and conflict checks, for example with an integer-programming solver such as OR-Tools.
- Campus matching (which campus students attend) isn't applied in allocation yet.
- Demand from irregular students could be improved by checking whether they have met the prerequisites, and by using historical enrollment rates.

## 10. Suggested rollout

1. Clean and link the four data sources: student information system, curriculum, and room inventory.
2. Build the demand forecast and the priority view.
3. Run it on last term's data and compare against the actual schedule.
4. Have the Registrar and department chairs agree on the weights.
5. Add timetabling and a dashboard for the scheduling office.
