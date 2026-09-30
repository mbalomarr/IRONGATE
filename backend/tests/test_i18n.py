from app.core.i18n import localize, parse_accept_language, t

API = "/api/v1"


def test_parse_accept_language():
    assert parse_accept_language("ar-SA,ar;q=0.9,en;q=0.8") == "ar"
    assert parse_accept_language("en-US,en;q=0.9,ar;q=0.8") == "en"
    assert parse_accept_language("fr-FR, ar;q=0.5") == "ar"
    assert parse_accept_language("fr-FR") is None
    assert parse_accept_language("ar;q=0, en") == "en"
    assert parse_accept_language(None) is None


def test_translate_and_localize():
    assert t("auth.invalid_credentials", "ar") == "البريد الإلكتروني أو كلمة المرور غير صحيحة."
    assert t("missing.key", "ar") == "missing.key"
    assert localize({"en": "Shopping Mall", "ar": "مركز تجاري"}, "ar") == "مركز تجاري"
    assert localize({"en": "Shopping Mall"}, "ar") == "Shopping Mall"


def test_lookup_json_columns_are_localized(client):
    res = client.get(f"{API}/lookups/sectors", headers={"Accept-Language": "ar"})
    assert res.headers["content-language"] == "ar"
    names = {s["code"]: s["name"] for s in res.json()["data"]}
    assert names["shopping_mall"] == "مركز تجاري"
    assert res.json()["message"] == "تمت العملية بنجاح."

    res = client.get(f"{API}/lookups/sectors?lang=en", headers={"Accept-Language": "ar"})
    assert {s["code"]: s["name"] for s in res.json()["data"]}["shopping_mall"] == "Shopping Mall"


def test_validation_errors_are_localized(client):
    res = client.post(f"{API}/auth/login", json={"password": "x"}, headers={"Accept-Language": "ar"})
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["message"] == "البيانات المُدخلة غير صحيحة."
    assert body["errors"][0] == {"field": "email", "message": "حقل «البريد الإلكتروني» مطلوب.", "type": "missing"}

    res = client.post(f"{API}/auth/login", json={"password": "x"})
    assert res.json()["errors"][0]["message"] == "Email is required."


def test_custom_validator_errors_are_localized(client):
    res = client.post(f"{API}/shamoos/verify", json={"national_id": "999"}, headers={"Accept-Language": "ar"})
    assert res.status_code == 422
    assert res.json()["errors"][0]["message"].startswith("يجب أن يتكون رقم الهوية")


def test_app_errors_are_localized(client):
    res = client.post(
        f"{API}/auth/login",
        json={"email": "nobody@x.sa", "password": "wrong"},
        headers={"Accept-Language": "ar"},
    )
    assert res.status_code == 401
    assert res.json() == {
        "success": False,
        "message": "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
        "code": "auth.invalid_credentials",
    }


def test_http_404_is_localized(client):
    res = client.get("/does-not-exist", headers={"Accept-Language": "ar"})
    assert res.status_code == 404
    assert res.json()["message"] == "البيانات المطلوبة غير موجودة."
