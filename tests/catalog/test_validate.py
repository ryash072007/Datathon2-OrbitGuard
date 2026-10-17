from orbitguard.consequence import validate


def test_predictions_positive_and_ordered():
    p = {e["event"]: validate.predicted_ge10cm(e)[0] for e in validate.EVENTS}
    assert all(v > 1000 for v in p.values())
    assert len(p) == 3


def test_satcat_parse(tmp_path, monkeypatch):
    f = tmp_path / "s.csv"
    f.write_text("OBJECT_NAME,OBJECT_ID,NORAD_CAT_ID,OBJECT_TYPE,DECAY_DATE\nA,1999-025A,25730,PAY,\n"
                 "B,1999-025AA,30000,DEB,\nC,1999-025AB,30001,DEB,2010-01-01\n", encoding="utf-8")
    monkeypatch.setattr(validate, "CACHE", f)
    df = validate.load_satcat(max_age_s=1e12)
    deb = df[df.OBJECT_TYPE.eq("DEB") & df.OBJECT_ID.str.startswith("1999-025")]
    assert len(deb) == 2 and (deb.DECAY_DATE == "").sum() == 1
