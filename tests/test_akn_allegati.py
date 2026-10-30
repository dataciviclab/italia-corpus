"""Test per `conta_allegati` (#94): misura degli `<attachments>` AKN."""

from __future__ import annotations

from lab_tools.akn_parser import allegati_to_markdown, conta_allegati

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
        """`chars` esclude `<name>`/`<num>`: deve essere comparabile al testo."""
        n, chars = conta_allegati(XML)
        assert n == 2
        assert chars == len("testo uno") + len("testo due")

    def test_name_escluso(self):
        xml = (
            "<akn><attachments><doc><name>Titolo</name>"
            "<p>corpo</p></doc></attachments></akn>"
        )
        assert conta_allegati(xml) == (1, len("corpo"))

    def test_namespace(self):
        n, chars = conta_allegati(XML_NS)
        assert n == 1
        assert chars == len("testo con namespace")

    def test_doc_vuoto_non_contato(self):
        xml = "<akn><attachments><doc><p> </p></doc><doc><p>x</p></doc></attachments></akn>"
        assert conta_allegati(xml) == (1, 1)

    def test_xml_malformato(self):
        assert conta_allegati("<akn><attachments>") == (0, 0)


XML_DOC = """<?xml version="1.0"?>
<akn xmlns="http://www.normattiva.it/akn">
  <attachments>
    <doc name="Codice Penale-art. 1"
         FRBRthis="urn:nir:stato:regio.decreto:1930-10-19;1398/!main/annesso_1">
      <mainBody>
        <article><num>Art. 1</num><heading>Dei reati</heading>
          <paragraph><content><p>Testo dell'articolo.</p></content></paragraph>
        </article>
      </mainBody>
    </doc>
  </attachments>
</akn>"""


class TestAllegatiMarkdown:
    def test_render_doc(self):
        docs = allegati_to_markdown(XML_DOC, {}, "x.md")
        assert len(docs) == 1
        assert docs[0]["doc_id"] == "annesso_1"
        assert docs[0]["doc_name"] == "Codice Penale-art. 1"
        assert "Art. 1" in docs[0]["markdown"]
        assert "Testo dell'articolo." in docs[0]["markdown"]

    def test_senza_frbr_usa_indice(self):
        xml = '<akn><attachments><doc name="A"><mainBody><p>x</p></mainBody></doc></attachments></akn>'
        docs = allegati_to_markdown(xml, {}, "x")
        assert docs[0]["doc_id"] == "doc_1"

    def test_senza_mainbody(self):
        xml = '<akn><attachments><doc name="A"></doc></attachments></akn>'
        docs = allegati_to_markdown(xml, {}, "x")
        assert docs[0]["markdown"] == ""

    def test_xml_malformato(self):
        assert allegati_to_markdown("<akn>", {}, "x") == []

    def test_doc_duplicati_scartati(self):
        xml = (
            '<akn><attachments>'
            '<doc name="A" FRBRthis="u/!main/annesso_1"><mainBody><p>a</p></mainBody></doc>'
            '<doc name="B" FRBRthis="u/!main/annesso_1"><mainBody><p>b</p></mainBody></doc>'
            '</attachments></akn>'
        )
        docs = allegati_to_markdown(xml, {}, "x")
        assert len(docs) == 1
