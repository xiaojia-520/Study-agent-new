import sys
import types
import unittest
from unittest.mock import patch

from src.infrastructure.device import resolve_device


class ResolveDeviceTests(unittest.TestCase):
    def test_auto_prefers_cuda_when_available(self) -> None:
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True))
        with patch.dict(sys.modules, {"torch": fake_torch}):
            self.assertEqual(resolve_device("auto"), "cuda")

    def test_auto_falls_back_to_cpu_when_cuda_unavailable(self) -> None:
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
        with patch.dict(sys.modules, {"torch": fake_torch}):
            self.assertEqual(resolve_device("auto"), "cpu")

    def test_explicit_cuda_falls_back_to_cpu_when_cuda_unavailable(self) -> None:
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
        with patch.dict(sys.modules, {"torch": fake_torch}):
            self.assertEqual(resolve_device("cuda"), "cpu")
            self.assertEqual(resolve_device("cuda:0"), "cpu")

    def test_explicit_cpu_is_preserved(self) -> None:
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True))
        with patch.dict(sys.modules, {"torch": fake_torch}):
            self.assertEqual(resolve_device("cpu"), "cpu")


if __name__ == "__main__":
    unittest.main()
