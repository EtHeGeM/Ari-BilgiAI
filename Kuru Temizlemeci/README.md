# Dry Cleaning SaaS MVP

FastAPI tabanli, PostgreSQL ve Redis kullanan, cok kiracili SaaS mantigina uygun kuru temizleme siparis platformu. Proje artik backend API ile birlikte admin ve vendor operasyon panelini de icerir.

## Ozellikler

- Telefon tabanli OTP girisi ve JWT authentication
- Kullanici, adres, vendor ve siparis yonetimi
- En yakin vendor atamasi
- Siparis durum akisi
- Vendor panel API'leri
- Admin siparis ve vendor yonetimi
- Dahili web arayuzu (`/` veya `/panel`)
- Dockerized calisma ortami
- Swagger/OpenAPI dokumantasyonu

## Folder Structure

```text
.
├── app
│   ├── api
│   │   ├── deps.py
│   │   └── v1/endpoints
│   ├── core
│   ├── db
│   ├── models
│   ├── schemas
│   ├── services
│   ├── utils
│   └── main.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Data Model

### User
- `id`
- `phone_number`
- `full_name`
- `role`: `customer`, `vendor`, `admin`
- `vendor_id`: vendor operator icin baglanti

### Vendor
- `id`
- `tenant_id`: SaaS tenant anahtari
- `name`
- `phone_number`
- `address_line`
- `latitude`
- `longitude`
- `is_active`

### Address
- `id`
- `user_id`
- `label`
- `line_1`, `line_2`
- `city`, `district`
- `latitude`, `longitude`

### Order
- `id`
- `user_id`
- `vendor_id`
- `address_id`
- `status`
- `subtotal`
- `delivery_fee`
- `total_price`
- `assigned_distance_km`
- `notes`

### OrderItem
- `id`
- `order_id`
- `item_type`
- `quantity`
- `unit_price`
- `total_price`

## Order State Machine

`ASSIGNED -> PICKED_UP -> CLEANING -> READY -> OUT_FOR_DELIVERY -> DELIVERED`

Vendor red halinde siparis alternatif vendor'a yeniden atanir.

## Setup

## Hizli Baslangic

Varsayilan `.env` lokal calisma icin SQLite + memory queue ile hazirdir. Bu sayede Postgres/Redis kurmadan demoyu kaldirabilirsiniz.

1. Ortami hazirlayin:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

2. Uygulamayi acin:

- Web panel: `http://localhost:8000/`
- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Docker ile Postgres + Redis

Docker kullanmak istiyorsaniz:

```bash
cp .env.example .env
docker compose up --build
```

`docker-compose.yml` icinde `DATABASE_URL` Postgres'e, `REDIS_URL` Redis'e override edilir. Boylece uretim yoluna yakin bir ortam elde edilir.

## Seed and Access

Uygulama acilisinda varsayilan admin otomatik olusturulur:

- Admin phone: `.env` icindeki `DEFAULT_ADMIN_PHONE`
- Demo vendor phone: `+905550000101`

OTP endpoint'i MVP amacli test kodunu response icinde dondurur.

Sistem ilk acilista demo vendor, vendor operatoru, musteri ve ornek siparis de olusturur.

## API Flow Example

1. `POST /api/v1/auth/otp/request`
2. `POST /api/v1/auth/otp/verify`
3. `POST /api/v1/users/me/addresses`
4. `POST /api/v1/orders`
5. `GET /api/v1/vendor-panel/orders`
6. `POST /api/v1/vendor-panel/orders/{order_id}/accept`
7. `POST /api/v1/vendor-panel/orders/{order_id}/status`

## Web Panel Akisi

1. Ana sayfayi acin: `http://localhost:8000/`
2. Demo admin veya vendor telefonu ile `OTP Iste`
3. Kod otomatik dolduktan sonra `Giris Yap`
4. Admin panelde vendor ekleyin, operator olusturun ve tum siparisleri izleyin
5. Vendor panelde siparisi kabul edin ve durumlarini ilerletin

## Multi-Tenant Note

Bu MVP'de tenant seviyesi `Vendor.tenant_id` ile temsil edilir. Siparisler vendor tenant'ina baglanir. Bir sonraki iterasyonda:

- tenant-bazli branding
- tenant ayarlari
- tenant-bazli fiyat kataloglari
- tenant-bazli rol yonetimi

eklenebilir.
