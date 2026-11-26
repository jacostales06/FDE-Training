-- View: Courses for Room Prioritization (v2)
-- One row per course offering per campus, ranked by how much it needs a physical room.
--
-- v2 changes vs. Session 1:
--   * Demand is split by campus (students are matched to rooms on their own campus).
--   * Backlog students are only counted when they have PASSED every prerequisite.
--   * Regular students who failed a prerequisite are excluded and reported as prereq_blocked.
--   * Weights are parameters (:w_*) loaded from config/settings.json instead of hard-coded.
--
-- Parameters: :next_term_no, :next_term, :section_size,
--             :w_graduating, :w_bottleneck, :w_needs_physical, :w_demand, :w_required, :w_scarcity
-- Dialect: SQLite. For PostgreSQL/MySQL replace two-argument MIN(x, 1) with LEAST(x, 1).

CREATE VIEW v_course_room_priority AS
WITH due AS (                      -- students the curriculum schedules for the course next term
    SELECT c.course_code, s.campus, s.student_no, s.expected_grad_term,
           CASE WHEN EXISTS (
                SELECT 1 FROM course_prerequisites p
                JOIN student_course_history h
                  ON h.course_code = p.prereq_code AND h.student_no = s.student_no
                 AND h.status IN ('FAILED', 'DROPPED')
                WHERE p.course_code = c.course_code) THEN 1 ELSE 0 END AS blocked
    FROM curriculum c
    JOIN enrolled_students s
      ON s.program = c.program AND s.curriculum_year = c.curriculum_year
     AND s.year_level = c.year_level
    WHERE c.term = :next_term_no
      AND NOT EXISTS (SELECT 1 FROM student_course_history h
                      WHERE h.student_no = s.student_no AND h.course_code = c.course_code
                        AND h.status = 'PASSED')
),
backlog AS (                       -- failed/dropped earlier, eligible only if all prereqs PASSED
    SELECT h.course_code, s.campus, s.student_no, s.expected_grad_term,
           CASE WHEN EXISTS (
                SELECT 1 FROM course_prerequisites p
                WHERE p.course_code = h.course_code
                  AND NOT EXISTS (SELECT 1 FROM student_course_history h2
                                  WHERE h2.student_no = h.student_no
                                    AND h2.course_code = p.prereq_code
                                    AND h2.status = 'PASSED')) THEN 1 ELSE 0 END AS blocked
    FROM student_course_history h
    JOIN enrolled_students s ON s.student_no = h.student_no
    WHERE h.status IN ('FAILED', 'DROPPED')
),
all_demand AS (SELECT * FROM due UNION SELECT * FROM backlog),
demand AS (
    SELECT course_code, campus,
           COUNT(DISTINCT CASE WHEN blocked = 0 THEN student_no END)                AS total_demand,
           COUNT(DISTINCT CASE WHEN blocked = 0 AND expected_grad_term = :next_term
                               THEN student_no END)                                 AS graduating,
           COUNT(DISTINCT CASE WHEN blocked = 1 THEN student_no END)                AS prereq_blocked
    FROM all_demand
    GROUP BY course_code, campus
    HAVING COUNT(DISTINCT CASE WHEN blocked = 0 THEN student_no END) > 0
),
unlocks AS (
    SELECT prereq_code AS course_code, COUNT(*) AS courses_unlocked
    FROM course_prerequisites GROUP BY prereq_code
),
supply AS (
    SELECT campus, room_type, SUM(capacity * available_hours_per_week) AS seat_hours
    FROM rooms GROUP BY campus, room_type
),
scarcity AS (                      -- demand seat-hours / supply seat-hours, per campus and room type
    SELECT d.campus, co.required_room_type,
           1.0 * SUM(d.total_demand * (co.lec_hours + co.lab_hours)) / NULLIF(MAX(sp.seat_hours), 0) AS ratio
    FROM demand d
    JOIN courses co ON co.course_code = d.course_code
    LEFT JOIN supply sp ON sp.campus = d.campus AND sp.room_type = co.required_room_type
    GROUP BY d.campus, co.required_room_type
),
is_req AS (
    SELECT course_code, MAX(CASE WHEN is_required = 'Y' THEN 1 ELSE 0 END) AS required
    FROM curriculum GROUP BY course_code
)
SELECT co.course_code,
       co.title,
       d.campus,
       co.required_room_type,
       co.can_be_online,
       co.lec_hours + co.lab_hours                    AS weekly_hours,
       d.total_demand,
       d.graduating,
       d.prereq_blocked,
       COALESCE(u.courses_unlocked, 0)                AS courses_unlocked,
       ROUND(100 * (
             :w_graduating     * (1.0 * d.graduating / d.total_demand)
           + :w_bottleneck     * MIN(COALESCE(u.courses_unlocked, 0) / 5.0, 1)
           + :w_needs_physical * (CASE WHEN co.can_be_online = 'N' THEN 1 ELSE 0 END)
           + :w_demand         * (1.0 * d.total_demand / (SELECT MAX(total_demand) FROM demand))
           + :w_required       * COALESCE(r.required, 0)
           + :w_scarcity       * MIN(COALESCE(sc.ratio, 1), 1)   -- no supply at campus = max scarcity
       ), 1)                                          AS priority_score
FROM demand d
JOIN courses co        ON co.course_code = d.course_code
LEFT JOIN unlocks u    ON u.course_code = d.course_code
LEFT JOIN scarcity sc  ON sc.campus = d.campus AND sc.required_room_type = co.required_room_type
LEFT JOIN is_req r     ON r.course_code = d.course_code;

-- Usage: SELECT * FROM v_course_room_priority ORDER BY priority_score DESC;
