"""Ordinary compressed text PDF smoke tests; all content is synthetic."""
import unittest
import zlib
from careerbrain.resume import BoundedPdfExtractor, ResumeRejected


def standard_pdf(phrase='Python e redes de computadores'):
    raw = f'BT /F1 14 Tf 72 720 Td ({phrase}) Tj ET'.encode()
    compressed = zlib.compress(raw)
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(compressed)).encode() + b' /Filter /FlateDecode >>\nstream\n' + compressed + b'\nendstream'
    ]
    result = bytearray(b'%PDF-1.4\n')
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(result))
        result += f'{index} 0 obj\n'.encode() + value + b'\nendobj\n'
    position = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets:
        result += f'{offset:010d} 00000 n \n'.encode()
    result += b'trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n' + str(position).encode() + b'\n%%EOF\n'
    return bytes(result)


class OrdinaryPdfTests(unittest.TestCase):
    def test_bounded_text_extract_and_evidence(self):
        extractor = BoundedPdfExtractor()
        document = standard_pdf('Experiencia profissional em Python')
        text = extractor.extract(document)
        self.assertIn('Python', text)
        status, attributes = extractor.profile(document)
        self.assertEqual(status, 'READY')
        self.assertTrue(any(attribute['value'] == 'Python' for attribute in attributes))

    def test_active_pdf_rejected(self):
        with self.assertRaises(ResumeRejected):
            BoundedPdfExtractor().extract(b'%PDF-1.4\n/JavaScript\n%%EOF')

    def test_no_skill_evidence_is_uncertain(self):
        state, attributes = BoundedPdfExtractor().profile(standard_pdf('Setor administrativo'))
        self.assertEqual((state, attributes), ('UNCERTAIN', []))


if __name__ == '__main__':
    unittest.main()
