from pathlib import Path
import socket
import tomllib
import unittest
from unittest.mock import patch

from scanner import scan_port, scan_target


class LocalhostRestrictionTests(unittest.TestCase):
    def test_both_entry_points_reject_targets_before_socket_creation(self):
        targets = (
            "example.com", "192.0.2.1", "192.168.1.1", "0.0.0.0",
            "127.0.0.2", "::1", "::ffff:127.0.0.1", "localhost.example.com",
            "LOCALHOST", " localhost", "localhost ", "127.1", "2130706433",
            "", None, 123, [],
        )
        with patch("scanner.socket.socket") as factory, patch("scanner.socket.getaddrinfo") as resolve:
            for target in targets:
                for entry_point in (scan_port, scan_target):
                    with self.subTest(target=target, entry_point=entry_point.__name__):
                        args = (target, 8080) if entry_point is scan_port else (target,)
                        with self.assertRaisesRegex(ValueError, "Localhost scanning only"):
                            entry_point(*args)
            factory.assert_not_called()
            resolve.assert_not_called()

    def test_target_rejected_even_with_empty_port_list(self):
        with patch("scanner.PORTS", []), self.assertRaises(ValueError):
            scan_target("example.com")

    def test_accepted_targets_use_ipv4_literal_without_resolution(self):
        for target in ("localhost", "127.0.0.1"):
            with self.subTest(target=target), patch("scanner.socket.socket") as factory, patch(
                "scanner.socket.getaddrinfo", side_effect=AssertionError("Must not resolve DNS")
            ):
                connection = factory.return_value.__enter__.return_value
                self.assertTrue(scan_port(target, 8080))
                factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
                connection.settimeout.assert_called_once_with(0.5)
                connection.connect.assert_called_once_with(("127.0.0.1", 8080))
                factory.return_value.__exit__.assert_called_once()

    def test_socket_failures_still_return_false_and_close_connection(self):
        for error in (TimeoutError("timed out"), ConnectionRefusedError("refused"), OSError("failed")):
            with self.subTest(error=error), patch("scanner.socket.socket") as factory:
                connection = factory.return_value.__enter__.return_value
                connection.connect.side_effect = error
                self.assertFalse(scan_port("localhost", 8080))
                factory.return_value.__exit__.assert_called_once()

    def test_real_local_listener_with_both_accepted_targets(self):
        for target in ("localhost", "127.0.0.1"):
            with self.subTest(target=target), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                port = listener.getsockname()[1]
                with patch("scanner.socket.getaddrinfo", side_effect=AssertionError("Must not resolve DNS")):
                    self.assertTrue(scan_port(target, port))

    def test_scan_target_report_with_real_listener(self):
        for target in ("localhost", "127.0.0.1"):
            with self.subTest(target=target), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                port = listener.getsockname()[1]
                with patch("scanner.PORTS", [port]), patch(
                    "scanner.socket.getaddrinfo", side_effect=AssertionError("Must not resolve DNS")
                ):
                    report = scan_target(target)
                self.assertEqual(report["target"], target)
                self.assertTrue({"target", "timestamp", "open_ports"} <= report.keys())
                self.assertEqual(report["open_ports"][0]["port"], port)
                self.assertIn("service", report["open_ports"][0])
                self.assertEqual(set(report["open_ports"][0]), {"port", "service"})

    def test_dashboard_configuration_binds_to_loopback(self):
        path = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"
        with path.open("rb") as config_file:
            config = tomllib.load(config_file)
        self.assertEqual(config["server"]["address"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
