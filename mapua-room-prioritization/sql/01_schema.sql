-- Room Utilization: Offering Prioritization - core schema
-- Inputs: Curriculum, Courses, Rooms, Enrolled Students

CREATE TABLE courses (
    course_code         VARCHAR(20) PRIMARY KEY,
    title               VARCHAR(150) NOT NULL,
    units               INT NOT NULL,
    lec_hours           INT NOT NULL DEFAULT 0,   -- weekly contact hours
    lab_hours           INT NOT NULL DEFAULT 0,
    required_room_type  VARCHAR(30) NOT NULL,     -- Lecture, Lab, Drafting, Computer Lab, ...
    can_be_online       CHAR(1) NOT NULL DEFAULT 'Y'  -- 'Y' if hybrid/online delivery is acceptable
);

CREATE TABLE course_prerequisites (
    course_code  VARCHAR(20) REFERENCES courses(course_code),
    prereq_code  VARCHAR(20) REFERENCES courses(course_code),
    PRIMARY KEY (course_code, prereq_code)
);

CREATE TABLE curriculum (
    program          VARCHAR(20),
    curriculum_year  INT,
    year_level       INT,
    term             INT,               -- 1, 2, 3 (quarter/term number)
    course_code      VARCHAR(20) REFERENCES courses(course_code),
    is_required      CHAR(1) NOT NULL DEFAULT 'Y',
    PRIMARY KEY (program, curriculum_year, course_code)
);

CREATE TABLE rooms (
    room_id                  VARCHAR(20) PRIMARY KEY,
    campus                   VARCHAR(30) NOT NULL,
    room_type                VARCHAR(30) NOT NULL,
    capacity                 INT NOT NULL,
    available_hours_per_week INT NOT NULL
);

CREATE TABLE enrolled_students (
    student_no          VARCHAR(20) PRIMARY KEY,
    program             VARCHAR(20) NOT NULL,
    curriculum_year     INT NOT NULL,
    year_level          INT NOT NULL,
    campus              VARCHAR(30) NOT NULL,
    expected_grad_term  VARCHAR(10)             -- e.g. '2026-3'
);

-- Course history, used to find backlog / irregular demand
CREATE TABLE student_course_history (
    student_no   VARCHAR(20) REFERENCES enrolled_students(student_no),
    course_code  VARCHAR(20) REFERENCES courses(course_code),
    status       VARCHAR(10) NOT NULL,          -- PASSED, FAILED, DROPPED
    PRIMARY KEY (student_no, course_code)
);
