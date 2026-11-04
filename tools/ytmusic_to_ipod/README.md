# «Швидкий вибір» з YouTube Music → iPod

`quickpicks_to_ipod.py` бере полицю **«Швидкий вибір» / Quick picks** з вашої
головної сторінки YouTube Music, завантажує треки у формат, який розуміє iPod
(AAC `.m4a` або `.mp3`), записує теги й обкладинки, створює плейлист і
передає його на iPod.

## Чому скрипт, а не готова програма

* «Швидкий вибір» — це не плейлист, а персональна полиця рекомендацій, яка
  змінюється щодня. Звичайні завантажувачі (yt-dlp, spotDL тощо) вміють
  працювати з плейлистами, але не з цією полицею.
* Офлайн-завантаження YouTube Music Premium зашифровані й відтворюються лише
  в застосунку YouTube Music, тож перенести їх на iPod не можна.
* Готової програми саме для «Quick picks → iPod» немає, тому скрипт з'єднує
  перевірені інструменти:
  [ytmusicapi](https://github.com/sigma67/ytmusicapi) (читає полицю),
  [yt-dlp](https://github.com/yt-dlp/yt-dlp) (завантажує звук),
  [mutagen](https://github.com/quodlibet/mutagen) (теги) та iTunes / Музику /
  Rockbox (запис на iPod).

## Встановлення

1. **Python 3.9+** — <https://www.python.org/downloads/>
   (на Windows позначте «Add python.exe to PATH»).
2. **ffmpeg**:
   * Windows: `winget install Gyan.FFmpeg`
   * macOS: `brew install ffmpeg`
   * Linux: `sudo apt install ffmpeg`
3. **Deno** — потрібен yt-dlp для YouTube:
   * Windows: `winget install DenoLand.Deno`
   * macOS: `brew install deno`
   * Linux: `curl -fsSL https://deno.land/install.sh | sh`
4. Пакети Python (у теці зі скриптом):

   ```bash
   pip install -r requirements.txt
   ```

## Вхід в акаунт

«Швидкий вибір» персональний, тож скрипту потрібні cookies браузера, у якому
ви увійшли на <https://music.youtube.com>.

* **Найпростіше — Firefox:** `--browser firefox`.
* Chrome/Edge на Windows шифрують cookies так, що сторонні програми часто не
  можуть їх прочитати. Якщо `--browser chrome` видає помилку, використайте
  Firefox або експортуйте cookies у файл розширенням на кшталт
  «Get cookies.txt LOCALLY» (на сторінці music.youtube.com) і передайте
  `--cookies cookies.txt`.
* Кілька Google-акаунтів у браузері: `--authuser 1` (2, 3…).
* Слухаєте з бренд-акаунта/каналу: `--brand-account <ID>`.

Cookies нікуди не надсилаються, окрім YouTube. Файл `cookies.txt` дає доступ
до вашого акаунта, тож не діліться ним.

## Використання

Спершу перевірте, що скрипт бачить ваш «Швидкий вибір»:

```bash
python quickpicks_to_ipod.py --browser firefox --list
```

Далі — залежно від того, що у вас за iPod.

### iPod зі стандартною прошивкою (Classic, Nano, Mini, Shuffle, Video, touch)

Такий iPod бачить лише музику, яку записав iTunes / Finder (або програма на
libgpod), просто скопіювати файли не вийде.

**Windows (iTunes):**

```bash
python quickpicks_to_ipod.py --browser firefox --itunes --sync
```

Скрипт створить або оновить в iTunes плейлист «Quick Picks» і запустить
синхронізацію. Один раз налаштуйте в iTunes: iPod → Музика → «Синхронізувати
музику» → «Вибрані плейлисти…» → позначте «Quick Picks». Якщо iPod у режимі
«Керувати музикою вручну», просто перетягніть плейлист на iPod.

**macOS (Музика + Finder):**

```bash
python3 quickpicks_to_ipod.py --browser firefox --itunes
```

Плейлист з'явиться в застосунку «Музика». Під час першого запуску macOS
попросить дозволити терміналу керувати «Музикою» — дозвольте. Потім: Finder →
iPod → Музика → «Синхронізувати вибрані плейлисти» → «Quick Picks» →
«Синхронізувати».

**Linux:** запустіть без `--itunes`, а теку `QuickPicks` з плейлистом
`Quick Picks.m3u8` імпортуйте у Strawberry або Rhythmbox — вони записують на
iPod через libgpod.

### iPod з прошивкою Rockbox

```bash
python quickpicks_to_ipod.py --browser firefox --rockbox E:\
```

```bash
python3 quickpicks_to_ipod.py --browser firefox --rockbox /media/$USER/IPOD
```

Файли потраплять у `Music/YouTube Music/`, плейлист — у `Playlists/`.

## Корисні параметри

| Параметр | Що робить |
| --- | --- |
| `--out ТЕКА` | куди складати музику (типово `./QuickPicks`) |
| `--format mp3` | mp3 замість m4a (m4a завантажується без перекодування, тому якісніший) |
| `--dated` | додати дату до назви плейлиста, щоб зберігати «Швидкий вибір» за різні дні |
| `--limit N` | взяти лише перші N треків |
| `--shelf "Назва"` | інша полиця головної сторінки (наприклад «Listen again») |
| `--redownload` | завантажити заново вже наявні треки |
| `--ytdlp-cookies` | передати cookies і в yt-dlp — потрібно лише для треків 18+ |

Наступні запуски не завантажують ті самі треки вдруге: скрипт пам'ятає їх у
файлі `QuickPicks/.quickpicks.json`. Старі треки з теки не видаляються —
приберіть їх вручну, якщо місце на iPod закінчується.

## Якщо щось не так

* **«не знайшов полицю Quick picks»** — скрипт покаже назви полиць, які
  бачить; передайте потрібну через `--shelf`. Якщо там немає персональних
  рекомендацій, найімовірніше, cookies не з того акаунта (`--authuser`).
* **«у cookies немає входу в YouTube»** — увійдіть на music.youtube.com саме
  в тому браузері (і профілі: `--browser firefox:назва-профілю`).
* **Помилки yt-dlp, «Sign in to confirm…», порожні формати** — оновіть його:
  `pip install -U "yt-dlp[default]"` і переконайтеся, що встановлено Deno.
* **Немає обкладинок на Rockbox** — Rockbox показує лише baseline-JPEG; скрипт
  вже зберігає обкладинки саме так, але в деяких збірках Rockbox вбудовані
  обкладинки в m4a не підтримуються — спробуйте `--format mp3`.

Скрипт призначений для особистого користування вашою музикою; дотримуйтеся
умов YouTube та авторського права.
