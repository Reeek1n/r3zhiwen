from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from tools.create_windows_profiles import shortcut_script, wrapper_cmd
from tools.windows_manager import browser_launch_args


class WrapperCmdTest(unittest.TestCase):
    def test_quotes_executable_path_with_spaces(self) -> None:
        content = wrapper_cmd(
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Users\tester\AppData\Local\Profiles\profile-1"),
            [],
            [],
        )

        self.assertIn('start "" "%EXECUTABLE%" ^', content)

    def test_shortcut_script_binds_icon_path(self) -> None:
        script = shortcut_script(
            Path(r"C:\Profiles\profile-1\店铺.vbs"),
            Path(r"C:\Profiles\profile-1\店铺.lnk"),
            Path(r"C:\Profiles\profile-1\店铺.ico"),
            Path(r"C:\Profiles\profile-1"),
        )

        self.assertIn("$shortcut.IconLocation", script)
        self.assertIn(r"C:\\Profiles\\profile-1\\店铺.ico", script)

    def test_browser_launch_args_keep_executable_as_single_argument(self) -> None:
        profile = {
            "profile_path": r"C:\Users\tester\AppData\Local\Profiles\profile-1",
            "args": ["--lang=zh-CN"],
            "open_urls": ["example.com"],
        }

        args = browser_launch_args(
            profile,
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        )

        self.assertEqual(args[0], r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        self.assertIn("--lang=zh-CN", args)
        self.assertIn("https://example.com", args)


if __name__ == "__main__":
    unittest.main()
