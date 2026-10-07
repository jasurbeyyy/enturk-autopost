# EnTurk_CSR — avtomatik post tizimi

Bu tizim @EnTurk_CSR kanaliga kuniga 3 ta post tayyorlab chiqaradi: 08:00, 13:00 va 20:00 da (Toshkent vaqti).
U **GitHub Actions**'da bepul ishlaydi, server kerak emas.

## Qanday ishlaydi

GitHub har bir post vaqtidan taxminan 50 daqiqa oldin tizimni ishga tushiradi:

| # | Agent | Nima qiladi |
|---|-------|-------------|
| 1 | Tadqiqotchi | Rubrika bo'yicha Google Search orqali yangi, dolzarb mavzu topadi (Gemini) |
| 2 | Yozuvchi | Uslublar bankidan navbatdagi uslubni tanlab, postni yozadi |
| 5 | Sifat nazorati | Turkcha grammatika, tarjima, faktlar, uzunlik va takrorlanmaslikni tekshiradi. Xato bo'lsa, post qayta yoziladi |
| 3 | Rassom | Har bir postga mavzusiga mos grafika chizadi (Gemini'siz, bepul): 8 xil maket (kartochka, katta emoji, chat, test, poster, stikerlar, daftar, Iznik koshinlari), 6 xil sahna (Istanbul, Bosfor, Kappadokiya, lolalar, choy-simit, London) va mavzuli emojilar. Ketma-ket postlarda maket va sahna takrorlanmaydi. Pastda qizil tasma va logo |
| 4 | Diktor | ElevenLabs orqali misollarni o'qiydi. Diologlarda ikki ovoz ishlatiladi |
| 6 | Admin bot | Post vaqtidan **10 daqiqa oldin** postni sizga yuboradi. Unda **🔄 Qayta ishlash** va **✅ Hozir chiqarish** tugmalari bor. Hech narsa bosmasangiz, post o'z vaqtida chiqadi |

**🔄 Qayta ishlash tugmasi:**
- Yangi post boshqa mavzu va boshqa uslubda tayyorlanadi.
- Tayyor bo'lgach sizga yana ko'rsatiladi va 10 daqiqadan keyin chiqadi, hatto asl vaqt o'tib ketgan bo'lsa ham.
- Tugmalar faqat navbatdagi post uchun ishlaydi. Eski xabarlardagi tugmalar "eskirgan" deb javob beradi.

## O'rnatish (bir marta, taxminan 20 daqiqa)

### 1. Telegram bot
1. @BotFather → `/newbot` buyrug'i bilan bot yarating va tokenni saqlab qo'ying.
2. Botni @EnTurk_CSR kanaliga **admin** qilib qo'shing va unga **"Post yozish"** huquqini bering.
3. Botga bitta xabar yozing, masalan `/start`. Bot sizga post yubora olishi uchun shu kerak.
4. O'z Telegram ID raqamingizni @userinfobot'dan oling.

### 2. GitHub repozitoriy
1. github.com'da ro'yxatdan o'ting va **New repository** tugmasini bosing.
   - Nomi: `enturk-autopost`.
   - Ko'rinishi: **Public**. Public repozitoriyda GitHub Actions cheksiz bepul. Kalitlar baribir yashirin qoladi, chunki ular kodda emas, Secrets'da saqlanadi.
2. Loyiha fayllarini repozitoriyga yuklang. Yoki repozitoriy nomini Claude'ga ayting, u kodni o'zi yuklaydi.

### 3. Kalitlarni yashirin joyga qo'yish
Repozitoriyda: **Settings → Secrets and variables → Actions → New repository secret**

| Nomi | Qiymati |
|------|---------|
| `TELEGRAM_BOT_TOKEN` | @BotFather bergan token |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey (rasm uchun billing yoqilgan bo'lishi kerak) |
| `ELEVENLABS_API_KEY` | elevenlabs.io → Profile → API Keys |
| `ADMIN_IDS` | Telegram ID raqamingiz |

Kanal nomi boshqa bo'lsa, **Variables** bo'limida `CHANNEL_ID` o'zgaruvchisini yarating.

### 4. Ovozlar
`config.yaml` faylida 4 ta ovoz tanlab qo'yilgan: AURA VOX, Mehmet Akif, Vanessa Voyce va Lucas.
elevenlabs.io → Voice Library'da har birini qidirib, **"Add to My Voices"** tugmasini bosing.
Boshqa ovoz xohlasangiz, uning ID'sini `config.yaml` → `elevenlabs.voices` bo'limiga yozing.

### 5. Sinash
Repozitoriyda: **Actions → EnTurk avtopost → Run workflow**
1. `rejim: tekshirish` — bot, kanal, Gemini, ElevenLabs va ovozlar tekshiriladi. Natijani jurnal (log) oxirida ko'rasiz.
2. `rejim: sinov_posti`, `tur: yangi_sozlar` — 3–5 daqiqada Telegram'ga sinov posti keladi. U kanalga o'zi chiqmaydi. Chiqarmoqchi bo'lsangiz, **✅ Kanalga chiqarish** tugmasini bosing.

Shundan keyin tizim jadval bo'yicha o'zi ishlaydi.

## Boshqarish

- **To'xtatish:** Settings → Secrets and variables → Actions → **Variables** bo'limida `PAUSED` = `1` qo'ying. Davom ettirish uchun `0` qiling.
- **Jadval:** haftalik jadval `config.yaml` → `weekly` bo'limida. Soatlarni o'zgartirsangiz, `.github/workflows/enturk.yml` faylidagi `cron` qatorini ham moslang. Cron UTC vaqtida yoziladi: Toshkent vaqti minus 5 soat, post vaqtidan ~50 daqiqa oldin.
- **Uslublar:** `styles.yaml` faylida. Yangi uslub qo'shish mumkin.
- **Takrorlanmaslik:** chiqqan postlar tarixi `state/enturk.db` faylida saqlanadi. GitHub uni har safar o'zi yangilab qo'yadi, uni o'chirmang.

## Bilish kerak bo'lgan narsalar

- **Kechikish:** GitHub ba'zan ishga tushishni 5–20 daqiqa kechiktiradi. Tizim shuning uchun ertaroq boshlaydi. Juda katta kechikish bo'lsa, post bir necha daqiqa kech chiqishi mumkin.
- **ElevenLabs:** oyiga taxminan 50–60 ming belgi audio ketadi. "tekshirish" rejimi qolgan belgilarni ko'rsatadi. Voice Library'dagi professional ovozlar pullik tarif talab qilishi mumkin.
- **Gemini:** har bir postda 1–3 ta rasm va bir nechta matn so'rovi bo'ladi. Narxlarni ai.google.dev/pricing sahifasida tekshiring.
- Har bir "Qayta ishlash" — to'liq yangi post, ya'ni qo'shimcha xarajat.

## Muammolar

| Belgi | Yechim |
|-------|--------|
| "tayyorlanmadi" xabari keldi | Xabardagi xatoni o'qing. Ko'pincha kalit, limit (429) yoki billing muammosi bo'ladi. Keyingi post jadval bo'yicha tayyorlanadi |
| Umuman xabar kelmayapti | Actions bo'limida ishga tushish tarixi va jurnalni ko'ring. `ADMIN_IDS`ni tekshiring va botga `/start` yozganingizga ishonch hosil qiling |
| Kanalga chiqmadi | `tekshirish` rejimida bot kanal admini ekanini tekshiring |
| "model not found" | `config.yaml` → `models` bo'limida model nomini yangilang |
| Tarix saqlanmadi (push xatosi) | Settings → Actions → General → Workflow permissions → **Read and write** qiling |

## Qo'shimcha: o'z serveringizda ishlatish
Kelajakda VPS olsangiz, `python main.py` doimiy bot rejimida ishlaydi. Unda `/sinov`, `/holat` va `/pauza` buyruqlari ham bor. `deploy/enturk.service` faylidan foydalaning.
