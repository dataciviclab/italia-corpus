"""Test per lab_tools.monitor_sunsetting — sunsetting score."""


from lab_tools.monitor_sunsetting import ANNO_CORRENTE, _calcola_sunsetting_score


class TestCalcolaSunsettingScore:
    """Test per _calcola_sunsetting_score(): candidatura decadenza."""

    def _r(self, **kwargs) -> dict:
        base = {
            "anno_atto": 2020, "n_citazioni": 10, "orfano": False,
            "collezione": "Decreti Legislativi", "qualita_score": 90,
        }
        base.update(kwargs)
        return base

    def test_attivo_base(self):
        """Atto recente, citato, di qualità → score basso."""
        assert _calcola_sunsetting_score(self._r()) <= 20

    def test_pre1980_mai_citati(self):
        """Pre-1980 mai citati → +40."""
        score = _calcola_sunsetting_score(self._r(anno_atto=1950, n_citazioni=0))
        assert score >= 40

    def test_pre1980_poco_citati(self):
        """Pre-1980 poco citati (1-3) → +25."""
        score = _calcola_sunsetting_score(self._r(anno_atto=1960, n_citazioni=2))
        assert score >= 25

    def test_1980_2000_mai_citati(self):
        """1980-2000 mai citati → +20."""
        score = _calcola_sunsetting_score(self._r(anno_atto=1990, n_citazioni=0))
        assert score >= 20

    def test_dl_proroghe_vecchie(self):
        """DL proroghe con >20 anni → +30."""
        score = _calcola_sunsetting_score(self._r(
            anno_atto=2000, collezione="DL proroghe", n_citazioni=5,
        ))
        assert score >= 30

    def test_orfano(self):
        """Orfano → +15."""
        score = _calcola_sunsetting_score(self._r(orfano=True, n_citazioni=0))
        assert score >= 15

    def test_qualita_bassa(self):
        """Score qualità <50 → +10."""
        score = _calcola_sunsetting_score(self._r(qualita_score=30, n_citazioni=5))
        assert score >= 10

    def test_strutturale_decremento(self):
        """Testi Unici / Codici → -20 (strutturali)."""
        score_tu = _calcola_sunsetting_score(self._r(
            collezione="Testi Unici", anno_atto=1950, n_citazioni=0,
        ))
        score_normale = _calcola_sunsetting_score(self._r(
            anno_atto=1950, n_citazioni=0,
        ))
        assert score_tu < score_normale

    def test_score_bounds(self):
        """Score sempre tra 0 e 100."""
        for kwargs in [
            {"anno_atto": 1800, "n_citazioni": 0, "orfano": True,
             "collezione": "DL proroghe", "qualita_score": 0},
            {"anno_atto": 2026, "n_citazioni": 100, "qualita_score": 100},
        ]:
            score = _calcola_sunsetting_score(self._r(**kwargs))
            assert 0 <= score <= 100

    def test_anno_corrente_dinamico(self):
        """ANNO_CORRENTE usa l'anno corrente, non hardcodato."""
        from datetime import datetime
        assert ANNO_CORRENTE == datetime.now().year
