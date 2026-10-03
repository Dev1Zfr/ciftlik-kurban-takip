import os
from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["INITIAL_ADMIN_PASSWORD"] = ""

import app as project


@pytest.fixture(autouse=True)
def clean_database():
    project.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with project.app.app_context():
        project.db.drop_all()
        project.db.create_all()
        project.db.session.add(
            project.User(
                username="admin",
                password=generate_password_hash("AuditPassword123!"),
                is_admin=True,
            )
        )
        project.db.session.commit()
        yield
        project.db.session.remove()
        project.db.drop_all()


@pytest.fixture
def client():
    client = project.app.test_client()
    response = client.post(
        "/login",
        data={"username": "admin", "password": "AuditPassword123!"},
    )
    assert response.status_code == 302
    return client


def create_animal(tag="GRUP-1", current_weight=350):
    animal = project.Hayvan(
        kupe_no=tag,
        irk="Simental",
        alis_kg=300,
        guncel_kg=current_weight,
        alis_fiyati=50000,
        alis_tarihi=project.utc_now() - timedelta(days=10),
    )
    project.db.session.add(animal)
    project.db.session.flush()
    project.db.session.add(project.KiloGecmisi(hayvan_id=animal.id, kilo=300))
    project.db.session.add(
        project.KiloGecmisi(hayvan_id=animal.id, kilo=current_weight)
    )
    project.db.session.commit()
    return animal.id


def test_weight_pages_show_group_average_and_daily_ranking(client):
    with project.app.app_context():
        animal_id = create_animal(current_weight=360)

    response = client.get("/mevcut")
    assert response.status_code == 200
    assert "GRUP" in response.text
    assert "Günlük Canlı Ağırlık Artışı" in response.text

    history = client.get(f"/gecmis/{animal_id}")
    assert history.status_code == 200
    assert "Canlı Ağırlık Ortalaması" in history.text
    assert "330.0 kg" in history.text


def test_customer_purchase_history_and_repeat_sale_protection(client):
    with project.app.app_context():
        animal_id = create_animal("SALE-1")

    response = client.post(
        f"/satis-yap/{animal_id}",
        data={
            "satis_turu": "Normal",
            "satis_fiyati": "10000",
            "alici_ad": "Ayşe Yılmaz",
            "alici_tel": "5551112233",
            "randiman": "55",
        },
    )
    assert response.status_code == 302

    search = client.get("/satilanlar?q=Ay%C5%9Fe")
    assert search.status_code == 200
    assert "Ayşe Yılmaz" in search.text
    assert "SALE-1" in search.text

    with project.app.app_context():
        share = project.Hisse.query.filter_by(hayvan_id=animal_id).one()
        share_id = share.id
    client.post(f"/odeme-ekle/{share_id}", data={"ek_odeme": "1000"})
    repeat = client.post(
        f"/satis-yap/{animal_id}",
        data={
            "satis_turu": "Normal",
            "satis_fiyati": "20000",
            "alici_ad": "Başka Alıcı",
        },
    )
    assert repeat.status_code == 302
    with project.app.app_context():
        share = project.Hisse.query.filter_by(hayvan_id=animal_id).one()
        assert share.hissedar_adi == "Ayşe Yılmaz"
        assert share.toplam_odenen == 1000


def test_duplicate_bulk_ids_are_rejected(client):
    with project.app.app_context():
        animal_id = create_animal("BULK-1")
    response = client.post(
        "/toplu-satis",
        data={
            "secilen_hayvanlar": [str(animal_id), str(animal_id)],
            "toplam_satis_fiyati": "10000",
            "alici_ad": "Toplu Alıcı",
        },
    )
    assert response.status_code == 302
    with project.app.app_context():
        animal = project.db.session.get(project.Hayvan, animal_id)
        assert animal.durum == "Mevcut"
        assert project.Hisse.query.filter_by(hayvan_id=animal_id).count() == 0


def test_feed_stock_consumption_and_history(client):
    client.post("/rasyon/yem-ekle", data={"yem_adi": "Yonca", "stok_kg": "100"})
    with project.app.app_context():
        feed_id = project.Yem.query.filter_by(yem_adi="Yonca").one().id
    response = client.post(
        "/rasyon/yem-harca",
        data={"yem_id": str(feed_id), "harcanan_kg": "12.5", "aciklama": "Grup 1"},
    )
    assert response.status_code == 302
    page = client.get("/rasyon")
    assert page.status_code == 200
    assert "87.5 kg" in page.text
    assert "−12.5 kg" in page.text
    assert "Grup 1" in page.text
    assert "standartYemler" in page.text


def test_kurban_distribution_and_cut_actions(client):
    with project.app.app_context():
        animal_id = create_animal("KURBAN-1")
    data = {
        "satis_turu": "Kurban",
        "satis_fiyati": "10",
        "kesim_sirasi": "1",
        "randiman": "55",
    }
    for index in range(1, 8):
        data[f"hissedar_ad_{index}"] = f"Hissedar {index}"
    response = client.post(f"/satis-yap/{animal_id}", data=data)
    assert response.status_code == 302
    with project.app.app_context():
        shares = project.Hisse.query.filter_by(hayvan_id=animal_id).all()
        assert len(shares) == 7
        assert round(sum(share.toplam_borc for share in shares), 2) == 10.0

    marked = client.post(f"/kesildi-isaretle/{animal_id}")
    assert marked.status_code == 302
    with project.app.app_context():
        assert (
            project.db.session.get(project.Hayvan, animal_id).kesim_durumu == "Kesildi"
        )


def test_main_authenticated_pages_render(client):
    for path in [
        "/",
        "/admin",
        "/ekle",
        "/mevcut",
        "/satilanlar",
        "/rasyon",
        "/kesim-ekrani",
        "/kaba-yem",
    ]:
        assert client.get(path).status_code == 200
