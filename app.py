import math
import os
import secrets
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash


def utc_now():
    """Return a timezone-neutral UTC value for the existing database columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

is_production = bool(database_url and not database_url.startswith("sqlite"))
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    if is_production:
        raise RuntimeError("Üretim ortamında SECRET_KEY tanımlanmalıdır.")
    secret_key = secrets.token_hex(32)

if getattr(sys, "frozen", False):
    executable_root = Path(sys.executable).resolve().parent
    bundle_root = Path(getattr(sys, "_MEIPASS", executable_root))
    instance_path = executable_root / "data"
    instance_path.mkdir(parents=True, exist_ok=True)
    app = Flask(
        __name__,
        template_folder=str(bundle_root / "templates"),
        instance_path=str(instance_path),
    )
else:
    app = Flask(__name__)
app.config.update(
    SECRET_KEY=secret_key,
    SQLALCHEMY_DATABASE_URI=database_url or "sqlite:///ciftlik.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=env_flag("COOKIE_SECURE", is_production),
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SECURE=env_flag("COOKIE_SECURE", is_production),
)
if is_production:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Bu sayfayı görmek için giriş yapmalısınız."
login_manager.login_message_category = "warning"

RATION_PROFILES = [
    {
        "label": "200–400 kg",
        "min": 200,
        "max": 400,
        "energy": 18.0,
        "protein": 14.0,
        "dry_matter": 5.5,
    },
    {
        "label": "400–600 kg",
        "min": 400,
        "max": 600,
        "energy": 25.0,
        "protein": 13.0,
        "dry_matter": 7.0,
    },
    {
        "label": "600–1000 kg",
        "min": 600,
        "max": 1000,
        "energy": 31.0,
        "protein": 12.0,
        "dry_matter": 8.0,
    },
]

STANDARD_FEEDS = {
    "yonca": {"energy": 2.2, "protein": 16.0, "dry_matter": 85.0},
    "mısır silajı": {"energy": 2.5, "protein": 8.0, "dry_matter": 30.0},
    "arpa": {"energy": 3.1, "protein": 11.0, "dry_matter": 88.0},
    "saman": {"energy": 1.5, "protein": 4.0, "dry_matter": 90.0},
    "fabrika yemi": {"energy": 3.0, "protein": 18.0, "dry_matter": 89.0},
}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)


class Yem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yem_adi = db.Column(db.String(100), nullable=False)
    stok_kg = db.Column(db.Float, default=0.0, nullable=False)
    # Eski kurulumlarla şema uyumluluğu için korunur; rasyon değerleri kullanıcı tarafından düzenlenir.
    enerji_me = db.Column(db.Float, default=0.0)
    protein_hp = db.Column(db.Float, default=0.0)
    kuru_madde = db.Column(db.Float, default=0.0)


class YemTuketim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yem_adi = db.Column(db.String(100), nullable=False)
    harcanan_kg = db.Column(db.Float, nullable=False)
    aciklama = db.Column(db.String(200))
    tarih = db.Column(db.DateTime, default=utc_now, nullable=False)


class KiloGecmisi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hayvan_id = db.Column(db.Integer, db.ForeignKey("hayvan.id"), nullable=False)
    tarih = db.Column(db.DateTime, default=utc_now, nullable=False)
    kilo = db.Column(db.Float, nullable=False)


class OdemeGecmisi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hisse_id = db.Column(db.Integer, db.ForeignKey("hisse.id"), nullable=False)
    tarih = db.Column(db.DateTime, default=utc_now, nullable=False)
    tutar = db.Column(db.Float, nullable=False)
    aciklama_not = db.Column(db.String(200))


class Hisse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hayvan_id = db.Column(db.Integer, db.ForeignKey("hayvan.id"), nullable=False)
    hisse_sira = db.Column(db.Integer, default=1, nullable=False)
    hissedar_adi = db.Column(db.String(100), nullable=False)
    hissedar_tel = db.Column(db.String(20))
    toplam_borc = db.Column(db.Float, default=0.0, nullable=False)
    odemeler = db.relationship(
        "OdemeGecmisi",
        backref="hisse",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def toplam_odenen(self):
        return round(sum(odeme.tutar for odeme in self.odemeler), 2)

    @property
    def kalan_borc(self):
        return round(max(0.0, self.toplam_borc - self.toplam_odenen), 2)


class Hayvan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kupe_no = db.Column(db.String(50), unique=True, nullable=False)
    irk = db.Column(db.String(50), nullable=False)
    alis_kg = db.Column(db.Float, nullable=False)
    guncel_kg = db.Column(db.Float, nullable=False)
    alis_fiyati = db.Column(db.Float, nullable=False)
    alis_tarihi = db.Column(db.DateTime, default=utc_now, nullable=False)
    durum = db.Column(db.String(20), default="Mevcut", nullable=False)
    satis_turu = db.Column(db.String(20), default="Normal", nullable=False)
    satis_fiyati = db.Column(db.Float)
    randiman = db.Column(db.Float, default=55.0, nullable=False)
    kesim_sirasi = db.Column(db.Integer)
    kesim_durumu = db.Column(db.String(20), default="Bekliyor", nullable=False)

    tartimlar = db.relationship(
        "KiloGecmisi",
        backref="hayvan",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    hisseler = db.relationship(
        "Hisse",
        backref="hayvan",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def grup_adi(self):
        if "-" in self.kupe_no:
            aday, sira = self.kupe_no.rsplit("-", 1)
            if aday and sira.isdigit():
                return aday
        return "Bireysel Kayıtlar"

    @property
    def gunluk_artis(self):
        gun_farki = max(1, (utc_now() - self.alis_tarihi).days)
        return round((self.guncel_kg - self.alis_kg) / gun_farki, 3)


def admin_required(view):
    @wraps(view)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return "Bu sayfaya yalnızca yönetici erişebilir!", 403
        return view(*args, **kwargs)

    return decorated_function


def parse_number(value, *, minimum=None, maximum=None):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    if minimum is not None and number < minimum:
        raise ValueError
    if maximum is not None and number > maximum:
        raise ValueError
    return number


def parse_money(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError
    return amount


def distribute_amount(total, count):
    base = (total / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    amounts = [base for _ in range(count)]
    amounts[-1] += total - sum(amounts)
    return amounts


def commit_or_flash(success_message, error_message):
    try:
        db.session.commit()
    except (IntegrityError, SQLAlchemyError):
        db.session.rollback()
        flash(error_message, "danger")
        return False
    flash(success_message, "success")
    return True


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:",
    )
    if request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


with app.app_context():
    db.create_all()
    if db.engine.dialect.name == "postgresql":
        db.session.execute(
            text('ALTER TABLE "user" ALTER COLUMN password TYPE VARCHAR(255)')
        )
        db.session.commit()

    admin_user = User.query.filter_by(username="admin").first()
    if not admin_user:
        initial_password = os.environ.get("INITIAL_ADMIN_PASSWORD")
        if initial_password and len(initial_password) >= 10:
            db.session.add(
                User(
                    username="admin",
                    password=generate_password_hash(initial_password),
                    is_admin=True,
                )
            )
            db.session.commit()
    elif not admin_user.is_admin:
        admin_user.is_admin = True
        db.session.commit()


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    hata = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        submitted_password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        valid_password = False
        if user:
            is_hashed = user.password.startswith(("pbkdf2:", "scrypt:"))
            valid_password = (
                check_password_hash(user.password, submitted_password)
                if is_hashed
                else user.password == submitted_password
            )

        if valid_password:
            if not user.password.startswith(("pbkdf2:", "scrypt:")):
                user.password = generate_password_hash(submitted_password)
                db.session.commit()
            login_user(user, remember=bool(request.form.get("hatirla")))
            return redirect(url_for("index"))
        hata = "Hatalı kullanıcı adı veya şifre!"

    return render_template(
        "login.html", hata=hata, kurulum_gerekli=User.query.count() == 0
    )


@app.route("/ilk-kurulum", methods=["GET", "POST"])
def ilk_kurulum():
    if User.query.count() > 0:
        return redirect(url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or len(username) > 50 or len(password) < 10:
            flash("Kullanıcı adı girin; parola en az 10 karakter olmalıdır.", "danger")
        else:
            db.session.add(
                User(
                    username=username,
                    password=generate_password_hash(password),
                    is_admin=True,
                )
            )
            if commit_or_flash("Yönetici hesabı oluşturuldu.", "Hesap oluşturulamadı."):
                return redirect(url_for("login"))
    return render_template("ilk_kurulum.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if User.query.count() == 0:
        return redirect(url_for("ilk_kurulum"))
    flash("Yeni kullanıcı hesapları yönetici panelinden oluşturulur.", "info")
    return redirect(url_for("login"))


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/hesap/parola", methods=["POST"])
@login_required
def parola_degistir():
    current_password = request.form.get("mevcut_parola", "")
    new_password = request.form.get("yeni_parola", "")
    is_hashed = current_user.password.startswith(("pbkdf2:", "scrypt:"))
    password_matches = (
        check_password_hash(current_user.password, current_password)
        if is_hashed
        else current_user.password == current_password
    )
    if not password_matches or len(new_password) < 10:
        flash(
            "Mevcut parolayı doğru girin; yeni parola en az 10 karakter olmalıdır.",
            "danger",
        )
    else:
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash("Parolanız güncellendi.", "success")
    return redirect(url_for("admin") if current_user.is_admin else url_for("index"))


@app.route("/admin")
@login_required
@admin_required
def admin():
    kullanicilar = User.query.order_by(User.username).all()
    toplam_hayvan = Hayvan.query.count()
    mevcut_hayvan = Hayvan.query.filter_by(durum="Mevcut").count()
    satilan_hayvan = Hayvan.query.filter_by(durum="Satildi").count()
    toplam_satis_tutari = (
        db.session.query(db.func.sum(Hayvan.satis_fiyati))
        .filter(Hayvan.durum == "Satildi")
        .scalar()
        or 0.0
    )
    hisseler = Hisse.query.all()
    toplam_tahsilat = sum(hisse.toplam_odenen for hisse in hisseler)
    toplam_kalan_alacak = sum(hisse.kalan_borc for hisse in hisseler)
    return render_template(
        "admin.html",
        kullanicilar=kullanicilar,
        toplam_hayvan=toplam_hayvan,
        mevcut_hayvan=mevcut_hayvan,
        satilan_hayvan=satilan_hayvan,
        toplam_satis_tutari=toplam_satis_tutari,
        toplam_tahsilat=toplam_tahsilat,
        toplam_kalan_alacak=toplam_kalan_alacak,
    )


@app.route("/admin/kullanici-ekle", methods=["POST"])
@login_required
@admin_required
def admin_kullanici_ekle():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if (
        not username
        or len(username) > 50
        or len(password) < 10
        or User.query.filter(db.func.lower(User.username) == username.lower()).first()
    ):
        flash(
            "Kullanıcı adı benzersiz olmalı; parola en az 10 karakter olmalıdır.",
            "danger",
        )
    else:
        db.session.add(
            User(
                username=username,
                password=generate_password_hash(password),
                is_admin=bool(request.form.get("is_admin")),
            )
        )
        commit_or_flash(
            "Kullanıcı hesabı oluşturuldu.", "Kullanıcı hesabı oluşturulamadı."
        )
    return redirect(url_for("admin"))


@app.route("/admin/kullanici-sil/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def kullanici_sil(user_id):
    user = db.get_or_404(User, user_id)
    admin_count = User.query.filter_by(is_admin=True).count()
    if user.id == current_user.id:
        flash("Kendi hesabınızı silemezsiniz.", "danger")
    elif user.is_admin and admin_count <= 1:
        flash("Sistemde en az bir yönetici kalmalıdır.", "danger")
    else:
        db.session.delete(user)
        commit_or_flash("Kullanıcı silindi.", "Kullanıcı silinemedi.")
    return redirect(url_for("admin"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.session.rollback()
        return {"status": "error"}, 503
    return {"status": "ok"}


@app.route("/mevcut")
@login_required
def mevcut():
    hayvanlar = Hayvan.query.filter_by(durum="Mevcut").order_by(Hayvan.id).all()
    gruplar = defaultdict(list)
    for hayvan in hayvanlar:
        gruplar[hayvan.grup_adi].append(hayvan)
    hayvanlar_sirali = sorted(
        hayvanlar, key=lambda item: item.gunluk_artis, reverse=True
    )
    return render_template(
        "mevcut.html",
        gruplar=dict(gruplar),
        hayvanlar_sirali=hayvanlar_sirali,
    )


@app.route("/ekle", methods=["GET", "POST"])
@login_required
def ekle():
    if request.method == "POST":
        kayit_turu = request.form.get("kayit_turu", "Bireysel")
        irk = request.form.get("irk", "").strip()
        try:
            alis_kg = parse_number(request.form.get("alis_kg"), minimum=0.1)
            alis_fiyati = parse_number(request.form.get("alis_fiyati"), minimum=0)
            if not irk or len(irk) > 50:
                raise ValueError
        except (TypeError, ValueError):
            flash(
                "Irk, alış kilosu ve alış fiyatını geçerli değerlerle girin.", "danger"
            )
            return redirect(url_for("ekle"))

        yeni_hayvanlar = []
        if kayit_turu == "Toplu":
            try:
                adet = int(request.form.get("adet", ""))
                grup_adi = request.form.get("grup_adi", "").strip()
                if not grup_adi or len(grup_adi) > 40 or not 1 <= adet <= 500:
                    raise ValueError
            except (TypeError, ValueError):
                flash("Grup adı girin; adet 1 ile 500 arasında olmalıdır.", "danger")
                return redirect(url_for("ekle"))

            kupe_numaralari = [f"{grup_adi}-{i}" for i in range(1, adet + 1)]
            if Hayvan.query.filter(Hayvan.kupe_no.in_(kupe_numaralari)).first():
                flash(
                    "Bu grup adıyla oluşturulmuş küpe numaraları zaten var.", "danger"
                )
                return redirect(url_for("ekle"))
            for kupe_no in kupe_numaralari:
                yeni_hayvanlar.append(
                    Hayvan(
                        kupe_no=kupe_no,
                        irk=irk,
                        alis_kg=alis_kg,
                        guncel_kg=alis_kg,
                        alis_fiyati=alis_fiyati,
                    )
                )
        else:
            kupe_no = request.form.get("kupe_no", "").strip()
            if not kupe_no or len(kupe_no) > 50:
                flash("Geçerli bir küpe numarası girin.", "danger")
                return redirect(url_for("ekle"))
            yeni_hayvanlar.append(
                Hayvan(
                    kupe_no=kupe_no,
                    irk=irk,
                    alis_kg=alis_kg,
                    guncel_kg=alis_kg,
                    alis_fiyati=alis_fiyati,
                )
            )

        try:
            for hayvan in yeni_hayvanlar:
                db.session.add(hayvan)
                db.session.flush()
                db.session.add(KiloGecmisi(hayvan_id=hayvan.id, kilo=alis_kg))
            db.session.commit()
        except (IntegrityError, SQLAlchemyError):
            db.session.rollback()
            flash("Bu küpe veya grup numarası zaten kayıtlı olabilir.", "danger")
            return redirect(url_for("ekle"))
        flash(f"{len(yeni_hayvanlar)} hayvan kaydı oluşturuldu.", "success")
        return redirect(url_for("mevcut"))
    return render_template("ekle.html")


@app.route("/toplu-satis", methods=["POST"])
@login_required
def toplu_satis():
    raw_ids = request.form.getlist("secilen_hayvanlar")
    alici_ad = request.form.get("alici_ad", "").strip()
    alici_tel = request.form.get("alici_tel", "").strip()
    try:
        ids = [int(value) for value in raw_ids]
        if not ids or len(ids) != len(set(ids)) or not alici_ad or len(alici_ad) > 100:
            raise ValueError
        toplam_fiyat = parse_money(request.form.get("toplam_satis_fiyati"))
    except (TypeError, ValueError):
        flash(
            "Hayvanları bir kez seçin ve geçerli alıcı/fiyat bilgisi girin.", "danger"
        )
        return redirect(url_for("mevcut"))

    hayvanlar = Hayvan.query.filter(Hayvan.id.in_(ids), Hayvan.durum == "Mevcut").all()
    if len(hayvanlar) != len(ids):
        flash("Seçilen hayvanlardan biri bulunamadı veya daha önce satıldı.", "danger")
        return redirect(url_for("mevcut"))

    fiyatlar = distribute_amount(toplam_fiyat, len(hayvanlar))
    for hayvan, fiyat in zip(hayvanlar, fiyatlar, strict=True):
        hayvan.durum = "Satildi"
        hayvan.satis_turu = "Normal"
        hayvan.satis_fiyati = float(fiyat)
        db.session.add(
            Hisse(
                hayvan_id=hayvan.id,
                hissedar_adi=alici_ad,
                hissedar_tel=alici_tel[:20],
                toplam_borc=float(fiyat),
            )
        )
    if commit_or_flash(
        f"{len(hayvanlar)} hayvan satıldı ve alıcı kaydı oluşturuldu.",
        "Toplu satış kaydedilemedi.",
    ):
        return redirect(url_for("satilanlar"))
    return redirect(url_for("mevcut"))


@app.route("/satilanlar")
@login_required
def satilanlar():
    q = request.args.get("q", "").strip()
    query = Hayvan.query.filter_by(durum="Satildi")
    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Hayvan.kupe_no.ilike(search),
                Hayvan.hisseler.any(Hisse.hissedar_adi.ilike(search)),
                Hayvan.hisseler.any(Hisse.hissedar_tel.ilike(search)),
            )
        )
    hayvanlar = query.order_by(Hayvan.id.desc()).all()
    kurbanlar = sorted(
        (hayvan for hayvan in hayvanlar if hayvan.satis_turu == "Kurban"),
        key=lambda item: item.kesim_sirasi if item.kesim_sirasi is not None else 10**9,
    )
    normal_satilanlar = [
        hayvan for hayvan in hayvanlar if hayvan.satis_turu == "Normal"
    ]
    return render_template(
        "satilanlar.html",
        kurbanlar=kurbanlar,
        normal_satilanlar=normal_satilanlar,
        q=q,
    )


@app.route("/satis-yap/<int:id>", methods=["GET", "POST"])
@login_required
def satis_yap(id):
    hayvan = db.get_or_404(Hayvan, id)
    if hayvan.durum != "Mevcut":
        flash(
            "Bu hayvan daha önce satılmıştır; satış kaydı tekrar oluşturulamaz.",
            "danger",
        )
        return redirect(url_for("satilanlar"))

    if request.method == "POST":
        satis_turu = request.form.get("satis_turu", "Normal")
        try:
            if satis_turu not in {"Normal", "Kurban"}:
                raise ValueError
            toplam_fiyat = parse_money(request.form.get("satis_fiyati"))
            randiman = parse_number(
                request.form.get("randiman") or 55, minimum=1, maximum=100
            )
            kesim_sirasi = None
            if satis_turu == "Kurban":
                kesim_sirasi = int(request.form.get("kesim_sirasi", ""))
                if kesim_sirasi < 1:
                    raise ValueError
        except (TypeError, ValueError):
            flash("Satış fiyatı, randıman ve kesim sırası geçerli olmalıdır.", "danger")
            return redirect(url_for("satis_yap", id=id))

        hissedarlar = []
        if satis_turu == "Kurban":
            for i in range(1, 8):
                ad = request.form.get(f"hissedar_ad_{i}", "").strip()
                tel = request.form.get(f"hissedar_tel_{i}", "").strip()
                if not ad or len(ad) > 100:
                    flash(
                        "Kurban satışında yedi hissedarın adı da girilmelidir.",
                        "danger",
                    )
                    return redirect(url_for("satis_yap", id=id))
                hissedarlar.append((i, ad, tel[:20]))
            borclar = distribute_amount(toplam_fiyat, 7)
        else:
            ad = request.form.get("alici_ad", "").strip()
            tel = request.form.get("alici_tel", "").strip()
            if not ad or len(ad) > 100:
                flash("Alıcı adı zorunludur.", "danger")
                return redirect(url_for("satis_yap", id=id))
            hissedarlar = [(1, ad, tel[:20])]
            borclar = [toplam_fiyat]

        hayvan.satis_turu = satis_turu
        hayvan.satis_fiyati = float(toplam_fiyat)
        hayvan.randiman = randiman
        hayvan.durum = "Satildi"
        hayvan.kesim_sirasi = kesim_sirasi
        hayvan.kesim_durumu = "Bekliyor"
        for (sira, ad, tel), borc in zip(hissedarlar, borclar, strict=True):
            db.session.add(
                Hisse(
                    hayvan_id=hayvan.id,
                    hisse_sira=sira,
                    hissedar_adi=ad,
                    hissedar_tel=tel,
                    toplam_borc=float(borc),
                )
            )
        if commit_or_flash(
            "Satış ve tahsilat kaydı oluşturuldu.", "Satış kaydedilemedi."
        ):
            return redirect(url_for("satilanlar"))
        return redirect(url_for("satis_yap", id=id))
    return render_template("satis_detay.html", hayvan=hayvan)


@app.route("/odeme-ekle/<int:hisse_id>", methods=["POST"])
@login_required
def odeme_ekle(hisse_id):
    hisse = db.get_or_404(Hisse, hisse_id)
    try:
        ek_odeme = parse_money(request.form.get("ek_odeme"))
        if ek_odeme > Decimal(str(hisse.kalan_borc)):
            raise ValueError
    except (TypeError, ValueError):
        flash("Ödeme, sıfırdan büyük ve kalan borçtan fazla olmamalıdır.", "danger")
        return redirect(url_for("satilanlar"))
    db.session.add(
        OdemeGecmisi(
            hisse_id=hisse.id,
            tutar=float(ek_odeme),
            aciklama_not=request.form.get("aciklama_not", "").strip()[:200],
        )
    )
    commit_or_flash("Ödeme geçmişe kaydedildi.", "Ödeme kaydedilemedi.")
    return redirect(url_for("satilanlar"))


@app.route("/rasyon")
@login_required
def rasyon():
    yemler = Yem.query.order_by(Yem.yem_adi).all()
    tuketimler = YemTuketim.query.order_by(YemTuketim.tarih.desc()).limit(50).all()
    return render_template(
        "rasyon.html",
        yemler=yemler,
        tuketimler=tuketimler,
        ration_profiles=RATION_PROFILES,
        standard_feeds=STANDARD_FEEDS,
    )


@app.route("/rasyon/yem-ekle", methods=["POST"])
@login_required
def yem_ekle():
    yem_adi = request.form.get("yem_adi", "").strip()
    try:
        stok_kg = parse_number(request.form.get("stok_kg"), minimum=0)
        if not yem_adi or len(yem_adi) > 100:
            raise ValueError
    except (TypeError, ValueError):
        flash("Yem adı ve sıfır veya üzeri stok miktarı zorunludur.", "danger")
        return redirect(url_for("rasyon"))

    yem = Yem.query.filter(db.func.lower(Yem.yem_adi) == yem_adi.lower()).first()
    if yem:
        yem.stok_kg = round(yem.stok_kg + stok_kg, 2)
        message = "Mevcut yem stoğu artırıldı."
    else:
        db.session.add(Yem(yem_adi=yem_adi, stok_kg=stok_kg))
        message = "Yem depoya eklendi."
    commit_or_flash(message, "Yem stoğu kaydedilemedi.")
    return redirect(url_for("rasyon"))


@app.route("/rasyon/yem-harca", methods=["POST"])
@login_required
def yem_harca():
    try:
        yem_id = int(request.form.get("yem_id", ""))
        harcanan_kg = parse_number(request.form.get("harcanan_kg"), minimum=0.01)
    except (TypeError, ValueError):
        flash("Yem ve geçerli bir tüketim miktarı seçin.", "danger")
        return redirect(url_for("rasyon"))

    yem = db.get_or_404(Yem, yem_id)
    if harcanan_kg > yem.stok_kg:
        flash("Harcanan miktar mevcut stoktan fazla olamaz.", "danger")
        return redirect(url_for("rasyon"))
    yem.stok_kg = round(yem.stok_kg - harcanan_kg, 2)
    db.session.add(
        YemTuketim(
            yem_adi=yem.yem_adi,
            harcanan_kg=harcanan_kg,
            aciklama=request.form.get("aciklama", "").strip()[:200],
        )
    )
    commit_or_flash(
        "Yem tüketimi stoktan düşüldü ve geçmişe kaydedildi.", "Tüketim kaydedilemedi."
    )
    return redirect(url_for("rasyon"))


@app.route("/rasyon/yem-sil/<int:id>", methods=["POST"])
@login_required
def yem_sil(id):
    yem = db.get_or_404(Yem, id)
    db.session.delete(yem)
    commit_or_flash(
        "Yem stok listesinden silindi; tüketim geçmişi korundu.", "Yem silinemedi."
    )
    return redirect(url_for("rasyon"))


@app.route("/kesim-ekrani")
@login_required
def kesim_ekrani():
    yon = request.args.get("yon", "asc")
    order = Hayvan.kesim_sirasi.desc() if yon == "desc" else Hayvan.kesim_sirasi.asc()
    kurbanlar = (
        Hayvan.query.filter_by(durum="Satildi", satis_turu="Kurban")
        .order_by(order, Hayvan.id.asc())
        .all()
    )
    return render_template("kesim_ekrani.html", kurbanlar=kurbanlar, yon=yon)


@app.route("/kesim-sira-degistir/<int:id>/<yon>", methods=["POST"])
@login_required
def kesim_sira_degistir(id, yon):
    if yon not in {"ust", "alt"}:
        return "Geçersiz yön", 400
    kurbanlar = (
        Hayvan.query.filter_by(durum="Satildi", satis_turu="Kurban")
        .order_by(Hayvan.kesim_sirasi.asc(), Hayvan.id.asc())
        .all()
    )
    for sira, hayvan in enumerate(kurbanlar, 1):
        if hayvan.kesim_sirasi is None:
            hayvan.kesim_sirasi = sira
    index = next((i for i, hayvan in enumerate(kurbanlar) if hayvan.id == id), None)
    if index is None:
        return "Kurbanlık bulunamadı", 404
    hedef = index - 1 if yon == "ust" else index + 1
    if 0 <= hedef < len(kurbanlar):
        kurbanlar[index].kesim_sirasi, kurbanlar[hedef].kesim_sirasi = (
            kurbanlar[hedef].kesim_sirasi,
            kurbanlar[index].kesim_sirasi,
        )
        db.session.commit()
    return redirect(url_for("kesim_ekrani"))


@app.route("/kesildi-isaretle/<int:id>", methods=["POST"])
@login_required
def kesildi_isaretle(id):
    hayvan = db.get_or_404(Hayvan, id)
    if hayvan.satis_turu != "Kurban" or hayvan.durum != "Satildi":
        return "Bu hayvan kesim listesinde değil", 400
    hayvan.kesim_durumu = "Kesildi"
    db.session.commit()
    flash(f"{hayvan.kupe_no} kesildi olarak işaretlendi.", "success")
    return redirect(url_for("kesim_ekrani"))


@app.route("/sira-guncelle/<int:id>", methods=["POST"])
@login_required
def sira_guncelle(id):
    hayvan = db.get_or_404(Hayvan, id)
    try:
        kesim_sirasi = int(request.form.get("kesim_sirasi", ""))
        kesim_durumu = request.form.get("kesim_durumu", "Bekliyor")
        if kesim_sirasi < 1 or kesim_durumu not in {"Bekliyor", "Kesildi"}:
            raise ValueError
    except (TypeError, ValueError):
        flash("Kesim sırası veya durumu geçersiz.", "danger")
        return redirect(url_for("kesim_ekrani"))
    hayvan.kesim_sirasi = kesim_sirasi
    hayvan.kesim_durumu = kesim_durumu
    db.session.commit()
    return redirect(url_for("kesim_ekrani"))


@app.route("/guncelle/<int:id>", methods=["POST"])
@login_required
def guncelle(id):
    hayvan = db.get_or_404(Hayvan, id)
    try:
        yeni_kilo = parse_number(request.form.get("yeni_kg"), minimum=0.1)
    except (TypeError, ValueError):
        flash("Geçerli bir tartım kilosu girin.", "danger")
        return redirect(url_for("mevcut"))
    hayvan.guncel_kg = yeni_kilo
    db.session.add(KiloGecmisi(hayvan_id=hayvan.id, kilo=yeni_kilo))
    db.session.commit()
    flash(f"{hayvan.kupe_no} için tartım kaydedildi.", "success")
    return redirect(url_for("mevcut"))


@app.route("/gecmis/<int:id>")
@login_required
def gecmis(id):
    hayvan = db.get_or_404(Hayvan, id)
    tartimlar = (
        KiloGecmisi.query.filter_by(hayvan_id=id)
        .order_by(KiloGecmisi.tarih.desc())
        .all()
    )
    ortalama_kilo = (
        round(sum(item.kilo for item in tartimlar) / len(tartimlar), 2)
        if tartimlar
        else 0
    )
    toplam_artis = round(hayvan.guncel_kg - hayvan.alis_kg, 2)
    return render_template(
        "gecmis.html",
        hayvan=hayvan,
        tartimlar=tartimlar,
        ortalama_kilo=ortalama_kilo,
        toplam_artis=toplam_artis,
    )


@app.route("/kaba-yem")
@login_required
def kaba_yem():
    return render_template("kaba_yem.html")


if __name__ == "__main__":
    app.run(debug=env_flag("FLASK_DEBUG"))
