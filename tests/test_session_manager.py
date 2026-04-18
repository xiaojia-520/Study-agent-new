import unittest

from web.backend.app.services.session_manager import SessionManager


class SessionManagerTests(unittest.TestCase):
    def test_create_session_keeps_explicit_course_and_lesson_ids(self) -> None:
        manager = SessionManager()

        session = manager.create_session(
            course_id="gaoshu_2026_spring",
            lesson_id="gaoshu_2026_spring_l12",
            subject="Higher Math",
        )

        self.assertEqual(session.course_id, "gaoshu_2026_spring")
        self.assertEqual(session.lesson_id, "gaoshu_2026_spring_l12")

    def test_create_session_generates_defaults_from_subject(self) -> None:
        manager = SessionManager()

        session = manager.create_session(subject="math debug")

        self.assertEqual(session.course_id, "math_debug")
        self.assertTrue(session.lesson_id.startswith("math_debug_"))
        self.assertIn(session.session_id[:8], session.lesson_id)


if __name__ == "__main__":
    unittest.main()
