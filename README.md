# Çiftlik ve Kurban Takip Sistemi

Flask tabanlı hayvan, satış, tahsilat, canlı ağırlık, yem stoku ve rasyon yönetim uygulaması.

## Yerel kurulum

Python 3.11 veya daha yeni bir sürüm kullanın.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\run.ps1
```

İlk açılışta `http://127.0.0.1:5000/ilk-kurulum` adresinden yönetici hesabınızı oluşturabilirsiniz.

Ortam değişkenleriyle kurulum yapmak için `.env.example` dosyasındaki değerleri barındırma hizmetinizde tanımlayın. Üretimde `SECRET_KEY` zorunludur. İlk yöneticiyi otomatik oluşturmak isterseniz `INITIAL_ADMIN_PASSWORD` en az 10 karakter olmalıdır.

## Testler

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
python -m bandit -q -r app.py
```

## Üretim

```text
gunicorn app:app
```

HTTPS kullanılan üretim ortamında `COOKIE_SECURE=true` ayarlayın. SQLite dosyaları `instance/` altında tutulur ve Git'e eklenmez.

## Python kurmadan Windows'ta çalıştırma

Bu çalışma klasöründe hazır yerel ortam bulunduğu için `BASLAT.bat` dosyasına çift tıklayabilirsiniz. Bağımsız Windows uygulamasını yeniden üretmek için:

```powershell
.\build_windows.ps1
```

Oluşan `dist\CiftlikTakip.exe`, bilgisayarda ayrıca Python kurulmasına ihtiyaç duymaz. Yerel veritabanı EXE'nin yanındaki `data` klasöründe saklanır.

## Render'a dağıtma

Depo kökündeki `render.yaml`, web servisini ve PostgreSQL veritabanını birlikte oluşturur. Render panelinde **New → Blueprint** ile depoyu seçin ve istenen `INITIAL_ADMIN_PASSWORD` değerine en az 10 karakterli ilk yönetici parolanızı girin. `SECRET_KEY` otomatik üretilir; bağlantı ve güvenli çerez ayarları Blueprint tarafından yapılır.
