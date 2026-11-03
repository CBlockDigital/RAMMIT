import pathlib
import unittest

# The headless UI test must poll (WaitFor) for these checks, not sleep a fixed time, or it flakes on a busy PC.
POLLED_CHECKS = [
    'selection persisted by username',
    'settings saved',
    'settings fold away',
    'Light theme loads',
    'Light uses its own stylesheet',
]

UI_TEST = pathlib.Path(__file__).with_name('TestUi.mjs')


class TestUiWaits(unittest.TestCase):
    def test_polled_checks_use_waitfor_without_fixed_sleep(self):
        lines = UI_TEST.read_text(encoding='utf-8').splitlines()
        for label in POLLED_CHECKS:
            with self.subTest(check=label):
                start = f"Check('{label}'"
                matches = [index for index, line in enumerate(lines) if start in line]
                self.assertEqual(len(matches), 1, f"expected one line for {label}")
                index = matches[0]
                self.assertIn('WaitFor(', lines[index], f"Check '{label}' does not poll with WaitFor")
                # The steps since the previous Check must not sleep a fixed time before this one looks.
                for before in reversed(lines[:index]):
                    if 'Check(' in before:
                        break
                    self.assertNotIn('Wait(', before, f"Check '{label}' still has a fixed Wait() before it")


if __name__ == '__main__':
    unittest.main()
