import errno
import unittest
from unittest.mock import patch

from power_herald.models import PingMethod

with patch("sqlalchemy.create_engine"):
    from power_herald.probe import ping_host


class PingHostTests(unittest.IsolatedAsyncioTestCase):
    async def test_tcp_no_route_to_host_returns_false_without_warning(self):
        error = OSError(errno.EHOSTUNREACH, "No route to host")
        with patch("power_herald.probe.socket.create_connection", side_effect=error), patch(
            "power_herald.probe.logger.warning"
        ) as warning:
            result = await ping_host("example.com:1234", 2, PingMethod.TCP)

        self.assertFalse(result)
        warning.assert_not_called()
