"""Test per `conta_allegati` (#94): misura degli `<attachments>` AKN."""

from __future__ import annotations

from lab_tools.akn_parser import conta_allegati

XML = """<?xml version="1.0"?>
<akn>
  <body><p>decreto di approvazione</p></body>
  <attachments>
    <doc><name>Art. 1</name><p>testo uno</p></doc>
    <doc><name>Art. 2</name><p>testo due</p></doc>
  </attachments>
</akn>"""

XML_NS = """<?xml version="1.0"?>
<akn xmlns="http://www.normattiva.it/akn">
  <attachments>
    <doc><p>testo con namespace</p></doc>
  </attachments>
</akn>"""


class TestContaAllegati:
    def test_senza_allegati(self):
        assert conta_allegati("<akn><body><p>x</p></body></akn>") == (0, 0)

    def test_due_doc(self):
        n, chars = conta_allegati(XML)
        assert n == 2
        assert chars == len("Art. 1 testo uno") + len("Art. 2 testo due")

    def test_namespace(self):
        n, chars = conta_allegati(XML_NS)
        assert n == 1
        assert chars == len("testo con namespace")

    def test_doc_vuoto_non_contato(self):
        xml = "<akn><attachments><doc><p> </p></doc><doc><p>x</p></doc></attachments></akn>"
        assert conta_allegati(xml) == (1, 1)

    def test_xml_malformato(self):
        assert conta_allegati("<akn><attachments>") == (0, 0)
