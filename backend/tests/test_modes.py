import unittest
from shark_runtime.modes import MODES, classify, compose


class ModeTests(unittest.TestCase):
    def test_compose_wraps_goal_with_mode_and_skills(self):
        text = compose("Fix it", "debugger", ["caveman"], ["Always mention Big-O"])
        self.assertTrue(text.startswith("MODE: DEBUGGER"))
        self.assertIn("caveman", text)
        self.assertIn("Always mention Big-O", text)
        self.assertTrue(text.endswith("TASK:\nFix it"))
        self.assertTrue(MODES["review"]["read_only"] and not MODES["builder"]["read_only"])

    def test_error_categories(self):
        self.assertEqual(classify("Error 429: Too Many Requests"), "rate_limit")
        self.assertEqual(classify("You have hit your usage limit"), "quota")
        self.assertEqual(classify("prompt is too long: 210000 tokens"), "context")
        self.assertEqual(classify("Invalid API key"), "auth")
        self.assertEqual(classify("something odd"), "other")


if __name__ == "__main__":
    unittest.main()
