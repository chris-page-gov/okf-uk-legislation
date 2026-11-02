"""Synthetic response controls for the validation HTTP dependency."""

import http.client
import io
import unittest

import urllib3


class ResponseBytes(io.BytesIO):
    largest_line = 0

    def readline(self, size=-1):
        line = super().readline(size)
        self.largest_line = max(self.largest_line, len(line))
        return line


class SocketFixture:
    def __init__(self, stream):
        self.stream = stream

    def makefile(self, *args, **kwargs):
        return self.stream


def response(body):
    stream = ResponseBytes(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + body)
    original = http.client.HTTPResponse(SocketFixture(stream))
    original.begin()
    parsed = urllib3.HTTPResponse(
        body=original, headers=original.getheaders(), preload_content=False,
        decode_content=False,
    )
    return parsed, stream


class ChunkSizeSecurityTests(unittest.TestCase):
    def test_streaming_rejects_a_chunk_size_line_before_buffering_it_all(self):
        for method in ("read_chunked", "stream"):
            with self.subTest(method=method):
                parsed, stream = response(b"1" * 70000 + b"\r\n")
                with self.assertRaises(urllib3.exceptions.ProtocolError):
                    list(getattr(parsed, method)())
                self.assertLessEqual(stream.largest_line, 65537)

    def test_ordinary_chunked_response_still_streams(self):
        for method in ("read_chunked", "stream"):
            with self.subTest(method=method):
                parsed, _ = response(b"3\r\none\r\n3\r\ntwo\r\n0\r\n\r\n")
                self.assertEqual(b"".join(getattr(parsed, method)()), b"onetwo")
