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

    # Exercise rendered views with a real active case, including final QC/exports.
    def click(label):
        next(button for button in app.button if button.label == label).click().run()
        assert not app.exception, app.exception

    app.sidebar.radio[0].set_value("2 · Investigation").run()
    click("Start")
    app.sidebar.radio[0].set_value("3 · Next experiment").run()
    click("Measure 40 eV")
    app.sidebar.radio[0].set_value("4 · Final report").run()
    click("Stop investigation")
    assert any("IDENTIFIED" in item.value for item in app.markdown)
    assert any("Total acquisitions: 2" in item.value for item in app.caption)
