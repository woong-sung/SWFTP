import socket
import threading
import time
import unittest
from unittest.mock import Mock, patch

from paramiko import SFTPClient
from sftp_encoding import EncodingSFTPClient


class SFTPConcurrencyTests(unittest.TestCase):
    def client(self):
        client = object.__new__(EncodingSFTPClient)
        client.operation_lock = threading.RLock()
        client.sock = Mock()
        return client

    def test_parallel_requests_do_not_read_each_others_replies(self):
        client = self.client()
        active = 0
        maximum = 0
        results = []

        def request(_client, value):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(0.02)
            active -= 1
            return value

        with patch.object(SFTPClient, "_request", request):
            threads = [threading.Thread(target=lambda n=n: results.append(client._request(n)))
                       for n in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(maximum, 1)
        self.assertEqual(sorted(results), list(range(8)))

    def test_timeout_closes_channel_and_releases_operation_lock(self):
        client = self.client()
        with patch.object(SFTPClient, "_request", side_effect=socket.timeout("no response")):
            with self.assertRaises(socket.timeout):
                client._request(1)
        client.sock.close.assert_called_once()
        with patch.object(SFTPClient, "_request", return_value="recovered"):
            self.assertEqual(client._request(2), "recovered")

    def test_channel_timeout_is_set_before_protocol_handshake(self):
        channel = Mock()
        with patch.object(SFTPClient, "__init__") as initialize:
            initialize.side_effect = lambda sock: self.assertEqual(sock.settimeout.call_args.args, (30,))
            EncodingSFTPClient(channel)


if __name__ == "__main__":
    unittest.main()
