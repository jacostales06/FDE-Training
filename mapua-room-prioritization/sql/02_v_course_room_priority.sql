-- View: Courses for Room Prioritization
-- Ranks next-term course offerings by how much they need a physical room.
-- Parameters (replace before running, or wrap in a stored procedure):
--   :next_term_no   term number being planned, e.g. 2
--   :next_term      term code used in expected_grad_term, e.g. '2026-2'
-- Written in SQLite/PostgreSQL syntax. MySQL: use CEIL; SQL Server: CEILING.

CREATE VIEW v_course_room_priority AS
WITH regular_demand AS (          -- students the curriculum schedules for the course
    SELECT c.course_code, s.student_no, s.expected_grad_term
    FROM curriculum c
    JOIN enrolled_students s
      ON s.program = c.program
     AND s.curriculum_year = c.curriculum_year
     AND s.year_level = c.year_level
    WHERE c.term = :next_term_no
),
backlog_demand AS (               -- students who failed/dropped and must retake
    SELECT h.course_code, s.student_no, s.expected_grad_term
    FROM student_course_history h
    JOIN enrolled_students s ON s.student_no = h.student_no
    WHERE h.status IN ('FAILED', 'DROPPED')
),
demand AS (
    SELECT course_code,
           COUNT(DISTINCT student_no) AS total_demand,
           COUNT(DISTINCT CASE WHEN expected_grad_term = :next_term THEN student_no END) AS graduating
    FROM (SELECT * FROM regular_demand UNION SELECT * FROM backlog_demand) d
    GROUP BY course_code
),
unlocks AS (                      -- how many courses each course is a prerequisite for
    SELECT prereq_code AS course_code, COUNT(*) AS courses_unlocked
    FROM course_prerequisites
    GROUP BY prereq_code
),
room_scarcity AS (                -- demand-hours vs. supply-hours per room type
    SELECT co.required_room_type,
           1.0 * SUM(d.total_demand * (co.lec_hours + co.lab_hours))
             / NULLIF((SELECT SUM(r.capacity * r.available_hours_per_week)
                       FROM rooms r WHERE r.room_type = co.required_room_type), 0) AS ratio
    FROM courses co JOIN demand d ON d.course_code = co.course_code
    GROUP BY co.required_room_type
),
is_req AS (
    SELECT course_code, MAX(CASE WHEN is_required = 'Y' THEN 1 ELSE 0 END) AS required
    FROM curriculum GROUP BY course_code
)
SELECT co.course_code,
       co.title,
       co.required_room_type,
       co.can_be_online,
       d.total_demand,
       (d.total_demand + 39) / 40                     AS sections_needed,   -- 40 = target section size
       d.graduating,
       COALESCE(u.courses_unlocked, 0)                AS courses_unlocked,
       ROUND(100 * (
             0.25 * (1.0 * d.graduating / d.total_demand)
           + 0.20 * MIN(COALESCE(u.courses_unlocked, 0) / 5.0, 1)
           + 0.20 * (CASE WHEN co.can_be_online = 'N' THEN 1 ELSE 0 END)
           + 0.15 * (1.0 * d.total_demand / (SELECT MAX(total_demand) FROM demand))
           + 0.10 * COALESCE(r.required, 0)
           + 0.10 * MIN(COALESCE(rs.ratio, 1), 1)
       ), 1)                                          AS priority_score
FROM courses co
JOIN demand d             ON d.course_code = co.course_code
LEFT JOIN unlocks u       ON u.course_code = co.course_code
LEFT JOIN room_scarcity rs ON rs.required_room_type = co.required_room_type
LEFT JOIN is_req r        ON r.course_code = co.course_code;

-- Usage:
-- SELECT * FROM v_course_room_priority ORDER BY priority_score DESC;
