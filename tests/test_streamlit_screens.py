"""Execute the real Streamlit script across all five views."""

from streamlit.testing.v1 import AppTest

from unknownid.paths import ROOT


def test_five_streamlit_screens(monkeypatch):
    monkeypatch.setenv("UNKNOWNID_MODE", "demo")
    app = AppTest.from_file(str(ROOT / "app/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    assert any("Demo mode" in item.value for item in app.info)
    for index in range(1, 5):
        app.sidebar.radio[0].set_value(
            [
                "1 · Provenance",
                "2 · Investigation",
                "3 · Next experiment",
                "4 · Final report",
                "5 · Evaluation",
            ][index]
        ).run()
        assert not app.exception, app.exception
