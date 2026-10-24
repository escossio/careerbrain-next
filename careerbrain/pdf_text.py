"""Constrained text-only PDF extraction in an isolated Python subprocess.

This process never receives account IDs, tokens, or a network resource identifier.
Its input is a bounded PDF on stdin; stdout contains extracted text only.
"""
from __future__ import annotations
import io
import os
import resource
import sys


def main() -> int:
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 9))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        from pypdf import PdfReader
        from careerbrain.resume import MAX_BYTES, MAX_PAGES, MAX_TEXT
        document = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not 1 <= len(document) <= MAX_BYTES or not document.startswith(b'%PDF-'):
            return 3
        reader = PdfReader(io.BytesIO(document), strict=False)
        if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
            return 4
        chunks: list[str] = []
        length = 0
        for page in reader.pages:
            text = page.extract_text(extraction_mode='plain') or ''
            length += len(text) + 1
            if length > MAX_TEXT:
                return 5
            chunks.append(text)
        sys.stdout.buffer.write('\n'.join(chunks).encode('utf-8'))
        return 0
    except (Exception, MemoryError):
        return 6


if __name__ == '__main__':
    sys.exit(main())
