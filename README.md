# Jasur | Turk tili (@jasurturktili) — avtomatik post tizimi

Bu tizim @jasurturktili kanaliga kuniga 2 ta turk tili posti tayyorlab chiqaradi: 10:00 va 18:00 da (Toshkent vaqti). Post mavzusi aylanib turadi: yangi so'zlar, diologlar, iboralar, hayotiy maslahat, mavzuli lug'at, imtihon. Bundan tashqari haftada 1 marta (yakshanba 14:00) 20 ta savollik test (quiz) chiqadi.
Har bir post matni oxirida Telegram va Instagram havolalari bo'ladi.
U **GitHub Actions**'da bepul ishlaydi, server kerak emas.

## Qanday ishlaydi

Tizimni **navbatchi** ishga tushiradi (`EnTurk navbatchi` workflow). U keyingi post yoki test vaqtini o'zi kutib turadi: vaqtiga taxminan 1 soat qolganda asosiy tizimni ishga tushiradi, keyin o'zini qayta ishga tushiradi. Shuning uchun GitHub jadvali kechiksa ham postlar o'z vaqtida chiqadi. Zaxira sifatida GitHub jadvali ham tizimni har 30 daqiqada uyg'otadi.

Post tayyorlash bosqichlari:

| # | Agent | Nima qiladi |
|---|-------|-------------|
| 1 | Tadqiqotchi | Rubrika bo'yicha Google Search orqali yangi, dolzarb mavzu topadi (Gemini) |
| 2 | Yozuvchi | Uslublar bankidan navbatdagi uslubni tanlab, postni yozadi |
| 5 | Sifat nazorati | Turkcha grammatika, tarjima, faktlar, uzunlik va takrorlanmaslikni tekshiradi. Xato bo'lsa, post qayta yoziladi |
| 3 | Rassom | **Hayotiy mavzularda** (yangi so'zlar, iboralar, lug'at, diolog, maslahat) Unsplash'dan mavzuga mos **haqiqiy foto** oladi: Gemini qidiruv so'zlari va rangni tanlaydi, foto mavzuga mosligi tekshiriladi, oxirgi postlardagi fotolar takrorlanmaydi. Foto ustiga 7 xil maketdan biri (gradient, rangli plashka, duoton, panel, karta, shisha, vinyetka) bilan sarlavha, so'zlar va JSR logosi qo'yiladi, post matniga esa "📷 Foto: muallif / Unsplash" qatori qo'shiladi. Ketma-ket 3 ta fotodan keyin bitta illyustratsiya chiqadi. Imtihon kabi mavhum mavzularda yoki foto topilmasa: Har bir postga **yangi, qolipsiz dizayn** chizadi. Gemini matn modeli shu post uchun alohida SVG illyustratsiya, rang palitrasi va kompozitsiya o'ylab topadi (rasm modeli va billing kerak emas). Kod esa sarlavha, rubrika, 2–4 ta turkcha so'z va JSR logosini qo'yadi, matn o'qilishini (kontrast) o'zi kafolatlaydi. 24 ta badiiy yo'nalish (kollaj, izometriya, Bauhaus, tungi sahna va h.k.), 7 xil matn joyi va 22 ta shrift navbat bilan almashadi, ketma-ket takrorlanmaydi. Naqsh, takroriy bezak va bir xil pastki tasma yo'q. Rasm tekshiruvchi mavzuga mosligini va yozuv yo'qligini tekshiradi. Dizayn chizilmasa, eski kod grafikasi zaxira bo'lib chiqadi |
| 4 | Diktor | ElevenLabs orqali misollarni o'qiydi. Diologlarda ikki ovoz ishlatiladi |
| 6 | Admin bot | Post vaqtidan **10 daqiqa oldin** postni sizga yuboradi. Unda **🔄 Qayta ishlash** va **✅ Hozir chiqarish** tugmalari bor. Hech narsa bosmasangiz, post o'z vaqtida chiqadi |

**🔄 Qayta ishlash tugmasi:**
- Yangi post boshqa mavzu va boshqa uslubda tayyorlanadi.
- Tayyor bo'lgach sizga yana ko'rsatiladi va 10 daqiqadan keyin chiqadi, hatto asl vaqt o'tib ketgan bo'lsa ham.
- Tugmalar faqat navbatdagi post uchun ishlaydi. Eski xabarlardagi tugmalar "eskirgan" deb javob beradi.

## O'rnatish (bir marta, taxminan 20 daqiqa)

### 1. Telegram bot
1. @BotFather → `/newbot` buyrug'i bilan bot yarating va tokenni saqlab qo'ying.
2. Botni @jasurturktili kanaliga **admin** qilib qo'shing va unga **"Post yozish"** huquqini bering.
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
| `UNSPLASH_ACCESS_KEY` | unsplash.com/oauth/applications → New Application → **Access Key** (bo'lmasa fotolar ishlatilmaydi, faqat illyustratsiya chiqadi) |
| `ADMIN_IDS` | Telegram ID raqamingiz |

Kanal nomi boshqa bo'lsa, **Variables** bo'limida `CHANNEL_ID` o'zgaruvchisini yarating.

### 4. Ovozlar
`config.yaml` faylida 2 ta turkcha ovoz tanlab qo'yilgan: AURA VOX va Mehmet Akif.
elevenlabs.io → Voice Library'da har birini qidirib, **"Add to My Voices"** tugmasini bosing.
Boshqa ovoz xohlasangiz, uning ID'sini `config.yaml` → `elevenlabs.voices` bo'limiga yozing.

### 5. Sinash
Repozitoriyda: **Actions → EnTurk avtopost → Run workflow**
1. `rejim: tekshirish` — bot, kanal, Gemini, ElevenLabs va ovozlar tekshiriladi. Natijani jurnal (log) oxirida ko'rasiz.
2. `rejim: sinov_posti`, `tur: yangi_sozlar` — 3–5 daqiqada Telegram'ga sinov posti keladi. U kanalga o'zi chiqmaydi. Chiqarmoqchi bo'lsangiz, **✅ Kanalga chiqarish** tugmasini bosing.

Shundan keyin tizim jadval bo'yicha o'zi ishlaydi.

## Haftalik test (quiz)

Haftada 1 marta, **yakshanba 14:00** da kanalga avval **"Haftalik test"** posti (rasm bilan) chiqadi, ketidan **20 ta quiz**: 10 ta grammatika va 10 ta kelime bilgisi. Ular QuizBot'dagi kabi ishlaydi: 4 ta variant, bitta to'g'ri javob, xato tanlansa 💡 izoh ko'rinadi.

- Har hafta navbatdagi daraja olinadi: A1 → A2 → B1 → B2.
- Har bir savol 4 bosqichdan o'tadi:
  1. **Kod tekshiruvi:** 4 ta variant, bitta to'g'ri javob, uzunlik, kirill harfi yo'qligi va takrorlanmaslik.
  2. **O'zbekcha muharrir:** imlo, atamalar va so'z tanlovini tuzatadi. Turkcha qismga tegmaydi, buni kod tekshiradi.
  3. **Qattiq tekshiruvchi:** 9/10 dan past baholangan savol tashlanadi.
  4. **Mustaqil yechuvchi:** javobni bilmagan holda testni yechadi. Javobi mos kelmasa yoki ikkita javob to'g'ri bo'lsa, savol tashlanadi.
  - Tashlangan savollar o'rniga yangilari yoziladi.
- To'g'ri javob o'rni aralashtiriladi, avvalgi testlar takrorlanmaydi.
- **10 daqiqa oldin** savol-javoblar sizga keladi, **🔄 Qayta ishlash** va **✅ Hozir chiqarish** tugmalari bilan. Ko'rib chiqish shart emas: hech narsa bosmasangiz, o'z vaqtida chiqadi.
- **Sinash:** Actions → EnTurk avtopost → Run workflow → `rejim: sinov_testi`. Testlar faqat sizga keladi. `rejim: test_tahlili` esa Telegram'ga hech narsa yubormaydi, faqat savollarni jurnalda ko'rsatadi.
- **Sozlash:** `config.yaml` → `quiz` bo'limi (vaqt, kun, savollar soni, darajalar). O'chirish uchun `enabled: false`. Vaqtni o'zgartirsangiz, cron'ga tegish shart emas.

## Boshqarish

- **To'xtatish:** Settings → Secrets and variables → Actions → **Variables** bo'limida `PAUSED` = `1` qo'ying. Davom ettirish uchun `0` qiling.
- **Navbatchi:** Actions bo'limida "EnTurk navbatchi" doim bitta ishlab turgan holatda ko'rinadi. Bu normal holat: u keyingi post vaqtini kutyapti. Zanjir biror sababdan uzilsa, 3 soat ichida o'zi qayta boshlanadi. Qo'lda boshlash uchun: **Actions → EnTurk navbatchi → Run workflow**.
- **Chiqmay qolgan post:** **Actions → EnTurk avtopost → Run workflow → `rejim: qayta_chiqarish`**. Raqamni bo'sh qoldirsangiz, bugungi chiqmay qolgan oxirgi post yangi imzo va logo bilan chiqadi.
- **Jadval:** `config.yaml` → `weekly` bo'limida (har kuni 10:00 va 18:00, `type: auto`). Post turi `rotation` ro'yxatidan aylanib tanlanadi: oxirgi 2 ta postning turi takrorlanmaydi, qolganlaridan eng kam chiqqani olinadi. Biror vaqtga aniq tur kerak bo'lsa, `auto` o'rniga tur nomini yozing. Soatlarni o'zgartirsangiz, cron'ga tegish shart emas: tizim har 30 daqiqada o'zi tekshiradi.
- **Havolalar:** post oxiridagi Telegram va Instagram havolalari `config.yaml` → `links` bo'limida.
- **Fotolar:** `config.yaml` → `photo` bo'limi (yoqish/o'chirish, qaysi post turlari, ketma-ket nechta foto). Unsplash bepul kaliti soatiga 50 ta so'rov beradi, bitta postga 2–4 ta ketadi.
- **Dizayn namunalari:** Actions → EnTurk avtopost → Run workflow → `rejim: dizayn_namunalari`. Oxirgi postlar mavzularida 6 ta rasm (foto va illyustratsiya) chiziladi va `dizayn-namunalari` tarmog'iga saqlanadi. Telegram'ga hech narsa yubormaydi.
- **Uslublar:** `styles.yaml` faylida. Yangi uslub qo'shish mumkin.
- **Takrorlanmaslik:** chiqqan postlar tarixi `state/enturk.db` faylida saqlanadi. GitHub uni har safar o'zi yangilab qo'yadi, uni o'chirmang.

## Bilish kerak bo'lgan narsalar

- **Kechikish:** GitHub jadvali ba'zan soatlab kechikadi yoki ishga tushishni tashlab ketadi. Shuning uchun asosiy ishni navbatchi bajaradi, jadval esa zaxira. Post vaqti o'tib ketgan bo'lsa ham, 4 soat ichida u baribir chiqariladi. Faqat keyingi post yaqin qolgan bo'lsa, eskisi tashlab ketiladi, shunda ikkita post ketma-ket chiqmaydi.
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
