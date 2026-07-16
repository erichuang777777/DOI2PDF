from doi2pdf import capabilities


def test_browser_capabilities_detect_optional_modules_without_importing(monkeypatch):
    seen = []

    def fake_find_spec(name):
        seen.append(name)
        return object() if name == "playwright" else None

    monkeypatch.setattr(capabilities, "find_spec", fake_find_spec)
    assert capabilities.browser_capabilities() == {"playwright": True, "browser_use": False}
    assert seen == ["playwright", "browser_use"]


def test_module_detection_treats_broken_optional_package_as_unavailable(monkeypatch):
    monkeypatch.setattr(capabilities, "find_spec", lambda _name: (_ for _ in ()).throw(ValueError("broken spec")))
    assert capabilities.module_available("browser_use") is False
