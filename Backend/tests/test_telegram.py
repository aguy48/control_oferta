"""Telegram: emparejamiento, webhook y avisos a administradores."""
from app.kernel.config import settings
from app.kernel.db import SessionLocal
from app.kernel.models import Usuario
from app.plataforma import telegram_ops
from .conftest import crear_usuario, token, auth_headers


def _h(client, usuario, rol):
    crear_usuario(usuario, rol)
    return auth_headers(token(client, usuario))


def _enable_bot(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "oriol_cot_bot")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    monkeypatch.setattr(settings, "TELEGRAM_MODE", "webhook")
    sent = []

    def _fake(chat_id, texto):
        sent.append((str(chat_id), texto))

    monkeypatch.setattr(telegram_ops, "_enviar", _fake)
    return sent


def _webhook(client, text, chat_id=111, username="ana", tipo="private"):
    return client.post("/telegram/webhook", json={
        "update_id": 1,
        "message": {
            "chat": {"id": chat_id, "type": tipo},
            "from": {"id": chat_id, "username": username},
            "text": text,
        },
    }, headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})


def test_telegram_sin_config_no_rompe(client):
    h = _h(client, "tg_analista", "analista")
    r = client.get("/telegram/estado", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["habilitado"] is False
    assert r.json()["vinculado"] is False
    r = client.post("/telegram/emparejar", headers=h)
    assert r.status_code == 503
    r = client.post("/telegram/webhook", json={"update_id": 1})
    assert r.status_code == 404
    r = client.get("/telegram/estado")
    assert r.status_code == 401


def test_telegram_emparejar_y_ayuda(client, monkeypatch):
    sent = _enable_bot(monkeypatch)
    h_ana = _h(client, "tg_ana2", "analista")
    h_adm = _h(client, "tg_adm2", "admin")

    r = client.get("/telegram/estado", headers=h_ana)
    assert r.status_code == 200
    assert r.json()["habilitado"] is True
    assert r.json()["bot_username"] == "oriol_cot_bot"

    r = client.post("/telegram/emparejar", headers=h_ana)
    assert r.status_code == 200, r.text
    token_ana = r.json()["token"]
    assert "t.me/oriol_cot_bot?start=" in (r.json()["enlace"] or "")

    r = client.post("/telegram/emparejar", headers=h_adm)
    token_adm = r.json()["token"]

    r = _webhook(client, f"/start {token_ana}", chat_id=201, username="ana_tg")
    assert r.status_code == 200, r.text
    r = _webhook(client, f"/start {token_adm}", chat_id=203, username="adm_tg")
    assert r.status_code == 200

    est = client.get("/telegram/estado", headers=h_ana).json()
    assert est["vinculado"] is True
    assert est["telegram_username"] == "ana_tg"
    me = client.get("/auth/me", headers=h_ana).json()
    assert me["telegram_vinculado"] is True
    assert me["telegram_username"] == "ana_tg"

    n_antes = len(sent)
    r = _webhook(client, "/ayuda", chat_id=999, tipo="group")
    assert r.status_code == 200
    assert len(sent) == n_antes

    r = client.post("/telegram/webhook", json={"update_id": 2, "message": {}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "otro"})
    assert r.status_code == 403

    sent.clear()
    r = _webhook(client, "02 Ofertas", chat_id=201, username="ana_tg")
    assert r.status_code == 200
    textos = [t for c, t in sent if c == "201"]
    assert textos, sent
    assert any("Ofertas" in t or "02" in t for t in textos)


def test_telegram_desvincular(client, monkeypatch):
    _enable_bot(monkeypatch)
    h = _h(client, "tg_ana3", "analista")
    token_emp = client.post("/telegram/emparejar", headers=h).json()["token"]
    assert _webhook(client, f"/start {token_emp}", chat_id=401, username="ana2").status_code == 200
    assert client.get("/telegram/estado", headers=h).json()["vinculado"] is True
    r = client.delete("/telegram/vinculo", headers=h)
    assert r.status_code == 200
    assert client.get("/telegram/estado", headers=h).json()["vinculado"] is False

    h_adm = _h(client, "tg_adm3", "admin")
    token_emp = client.post("/telegram/emparejar", headers=h).json()["token"]
    _webhook(client, f"/start {token_emp}", chat_id=402, username="ana3")
    db = SessionLocal()
    try:
        ana = db.query(Usuario).filter(Usuario.usuario == "tg_ana3").first()
        uid = ana.id
    finally:
        db.close()
    r = client.delete(f"/telegram/vinculo/{uid}", headers=h_adm)
    assert r.status_code == 200
    assert client.get("/telegram/estado", headers=h).json()["vinculado"] is False
    r = client.delete(f"/telegram/vinculo/{uid}", headers=h)
    assert r.status_code == 403


def test_telegram_lista_vinculos(client, monkeypatch):
    _enable_bot(monkeypatch)
    h_ana = _h(client, "tg_ana4", "analista")
    h_adm = _h(client, "tg_adm4", "admin")
    r = client.get("/telegram/vinculos", headers=h_ana)
    assert r.status_code == 403
    token_ana = client.post("/telegram/emparejar", headers=h_ana).json()["token"]
    token_adm = client.post("/telegram/emparejar", headers=h_adm).json()["token"]
    _webhook(client, f"/start {token_ana}", chat_id=501, username="ana4")
    _webhook(client, f"/start {token_adm}", chat_id=502, username="adm4")
    r = client.get("/telegram/vinculos", headers=h_adm)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["n_vinculados"] >= 2
    assert all("telegram_chat_id" not in u for u in data["usuarios"])


def test_telegram_notificar_admins(client, monkeypatch):
    sent = _enable_bot(monkeypatch)
    h_adm = _h(client, "tg_adm5", "admin")
    token_adm = client.post("/telegram/emparejar", headers=h_adm).json()["token"]
    assert _webhook(client, f"/start {token_adm}", chat_id=601, username="adm5").status_code == 200
    sent.clear()
    db = SessionLocal()
    try:
        n = telegram_ops.notificar_admins(db, "Cuenta bloqueada de prueba", clave="tg:test-bloqueo")
        assert n >= 1
        n2 = telegram_ops.notificar_admins(db, "Otra vez", clave="tg:test-bloqueo")
        assert n2 == 0
    finally:
        db.close()
    assert any("bloqueada" in t.lower() for _, t in sent)
