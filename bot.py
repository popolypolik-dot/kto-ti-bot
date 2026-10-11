import asyncio
import re
import sqlite3
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# =========================================================
# НАСТРОЙКИ
# =========================================================

TOKEN = "8927681434:AAFizoMwdwqq1_P3g8cBSkpo0XsfjYwh9lg"

# Если хочешь получать жалобы себе, впиши сюда свой Telegram ID.
# Например: ADMIN_ID = 123456789
ADMIN_ID = 7898433714

if TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН_BOTFATHER":
    raise RuntimeError("Сначала вставь токен BotFather в переменную TOKEN.")

bot = Bot(TOKEN)
dp = Dispatcher()

# =========================================================
# БАЗА ДАННЫХ
# =========================================================

db = sqlite3.connect("bot.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    age_group TEXT,
    gender TEXT,
    searching INTEGER DEFAULT 0,
    partner_id INTEGER,
    messages_sent INTEGER DEFAULT 0,
    conversations_count INTEGER DEFAULT 0,
    contact_offered INTEGER DEFAULT 0,
    profanity_filter INTEGER DEFAULT 0,
    chat_session_id TEXT,
    search_gender TEXT
)
""")

db.commit()

# Мягкая миграция: если bot.db уже существует от старой версии,
# добавляем новый счётчик, не удаляя старые данные.
cursor.execute("PRAGMA table_info(users)")
existing_columns = {row[1] for row in cursor.fetchall()}

if "conversations_count" not in existing_columns:
    cursor.execute(
        "ALTER TABLE users ADD COLUMN conversations_count INTEGER DEFAULT 0"
    )
    db.commit()

cursor.execute("PRAGMA table_info(users)")
existing_columns = {row[1] for row in cursor.fetchall()}

if "contact_offered" not in existing_columns:
    cursor.execute(
        "ALTER TABLE users ADD COLUMN contact_offered INTEGER DEFAULT 0"
    )
    db.commit()

cursor.execute("PRAGMA table_info(users)")
existing_columns = {row[1] for row in cursor.fetchall()}

if "profanity_filter" not in existing_columns:
    cursor.execute(
        "ALTER TABLE users ADD COLUMN profanity_filter INTEGER DEFAULT 0"
    )
    db.commit()

if "chat_session_id" not in existing_columns:
    cursor.execute(
        "ALTER TABLE users ADD COLUMN chat_session_id TEXT"
    )
    db.commit()

# Для уже существующей базы: сохраняем выбранный пол собеседника.
cursor.execute("PRAGMA table_info(users)")
existing_columns = {row[1] for row in cursor.fetchall()}
if "search_gender" not in existing_columns:
    cursor.execute(
        "ALTER TABLE users ADD COLUMN search_gender TEXT"
    )
    db.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    sender_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()

# =========================================================
# КЛАВИАТУРЫ
# =========================================================

age_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="17 и младше")],
        [KeyboardButton(text="18–21")],
        [KeyboardButton(text="22–25")],
        [KeyboardButton(text="26–30")]
    ],
    resize_keyboard=True
)

gender_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👨 Парень")],
        [KeyboardButton(text="👩 Девушка")],
        [KeyboardButton(text="🤷 Неважно")]
    ],
    resize_keyboard=True
)

search_gender_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔎 👨 Парень")],
        [KeyboardButton(text="🔎 👩 Девушка")],
        [KeyboardButton(text="🔎 🤷 Неважно")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔎 Найти собеседника")],
        [KeyboardButton(text="☰ Меню")],
        [KeyboardButton(text="➡️ Следующий"), KeyboardButton(text="🛑 Стоп")],
        [KeyboardButton(text="🚨 Пожаловаться")]
    ],
    resize_keyboard=True
)

chat_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="☰ Меню")],
        [KeyboardButton(text="➡️ Следующий"), KeyboardButton(text="🛑 Стоп")],
        [KeyboardButton(text="🚨 Пожаловаться")]
    ],
    resize_keyboard=True
)

def menu_keyboard_for(user_id: int):
    user = get_user(user_id)

    rows = [
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="👥 Собеседник")],
        [KeyboardButton(text="🎂 Сменить возраст")],
        [KeyboardButton(text="🚻 Сменить пол")],
    ]

    if user and user[1] != "17 и младше":
        status = "ВКЛ" if user[8] else "ВЫКЛ"
        rows.append([KeyboardButton(text=f"🤬 Фильтр матов: {status}")])

    rows.extend([
        [KeyboardButton(text="📊 Моя статистика")],
        [KeyboardButton(text="ℹ️ Помощь")],
        [KeyboardButton(text="🔙 Назад")],
    ])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True
    )

contact_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(
            text="📱 Обменяться номером",
            request_contact=True
        )],
        [KeyboardButton(text="☰ Меню")],
        [KeyboardButton(text="➡️ Следующий"), KeyboardButton(text="🛑 Стоп")],
        [KeyboardButton(text="🚨 Пожаловаться")]
    ],
    resize_keyboard=True
)

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👁 Все активные диалоги")],
        [KeyboardButton(text="🗂 Все сохранённые диалоги")],
        [KeyboardButton(text="🔙 Выйти из админки")]
    ],
    resize_keyboard=True
)

# =========================================================
# СЛОВАРЬ ИЗ ПРИСЛАННОГО ГЛОССАРИЯ
# =========================================================

BAD_WORDS = ['бля буду', 'блдь', 'блдки', 'блдовать', 'блдство', 'ебать', 'ебало', 'ебальник', 'ебать его в рот', 'его', 'ебать его конем', 'ебать колотить', 'ебать меня в рот ебать мой рот', 'ебать мой рот', 'ебаться сраться', 'ебическая сила', 'ебло', 'еблом щелкать', 'ебальничком прощелкал', 'поебать', 'шобла ебла', 'выебываться', 'долбоеб', 'дуроеб', 'ебанатик', 'ебанутый', 'ебаришка', 'ебать му му', 'ебливая', 'ебукентий', 'ебаный в рот жопу', 'жопу', 'ебарь', 'ебнутый', 'ебанатический', 'ебеня малые беня', 'малые беня', 'ебантроп', 'еблище', 'ебицкая сила', 'невротъебательский', 'уебан', 'уебантус', 'заеб', 'злоебучая', 'изъебнуться', 'к беням', 'коноебиться', 'мозгоеб', 'мудоеб', 'разъебай', 'худоебина', 'взъебка', 'доебаться', 'ебаторий', 'ебать мозги', 'ебаться', 'ебля', 'ебаный', 'заебать', 'заебанный', 'заебаться', 'настоебать', 'отъебаться', 'прибаться', 'пробаться', 'самого хоть в жопу би', 'уебать', 'ебануть', 'ебнуть', 'ебнуться', 'ебс еблысь', 'еблысь', 'наебнуться', 'до баной матери', 'ебистика', 'заебись', 'поебень', 'разъебаный', 'выебать', 'наебать', 'наебнуть', 'пробать', 'разъебаться', 'уебывать', 'елда ялда', 'ялда', 'манда', 'муда', 'мудак', 'мудень', 'мудвин', 'мудаспрудск', 'мудозвон', 'пзда', 'без пзды', 'в пзде', 'в пзду', 'до пзды', 'остопздеть', 'пзда малосольная', 'пздобратия', 'пздой накрыться', 'пздолет', 'пздопроушина', 'пздорванка', 'пздодрищенск', 'пздогробина', 'пздолиз', 'стропздюлина', 'пздорванец пздорванка', 'пзденыш', 'пздюлина', 'пздюшник', 'распздяй ка', 'выпздеться', 'допздеться', 'запздеть', 'пздеть', 'пздеж', 'пздануть', 'пздобол', 'пздун', 'пздюк', 'попздеть', 'распздон', 'впздячить', 'испздить', 'пздить', 'пздошить', 'пзды дать', 'пзды получить', 'пздюлей навешать', 'пздюли', 'отпздить', 'напздить', 'попздили', 'спздить', 'выпздить', 'пздопротивный', 'пздуй', 'пздюрить', 'пздюхать', 'припздить', 'пропздить', 'упздить', 'какого хя', 'на хй', 'на хя', 'нехй', 'хуем груши околачивать', 'хуев нарисовать', 'хуевина', 'строхй', 'хуепутало', 'хуевничать', 'хй его знает', 'хй к носу прикинуть', 'хй ночевал', 'хуями обложить', 'хули', 'хуяк', 'через хй кинуть', 'охуенный', 'охуенно', 'охительный', 'хевато', 'хуета', 'хуетень', 'хуево', 'хуевый', 'хуе мое', 'хй знает что', 'хйня', 'всего ни хя', 'до хя', 'до хя и больше', 'ни хя', 'однохйственно', 'с хеву душу', 'с хеву тучу', 'хй чего', 'в хй не дует', 'за всю хйню', 'на хй послать', 'на хю видеть', 'ни хя себе', 'по хю', 'сосешь хй', 'хй в рот жопу', 'хоть бы хй', 'хй забить', 'хй на нэ', 'хй на рыло', 'хй не стоит', 'хй показать', 'хй положить', 'хй с ним', 'хуя ни хя', 'вхуярить вхуячить', 'захярить', 'исхуячить', 'на хй сесть', 'нахяриться', 'охуячить', 'перехуярить', 'похярили', 'прихярить', 'расхуюжить', 'схуярить', 'тянуть за хй', 'хйнуть', 'хйню спороть', 'хуячить', 'хуебратия', 'хуеглот', 'хуегрыз', 'хуемырло', 'хуеплет', 'хуила', 'хйло', 'хй важный', 'хй моржовый голландский стоптанный мамин с горы', 'голландский стоптанный мамин с горы', 'хй немытый']

def normalize_text(text: str) -> str:
    # casefold() надёжнее для разных вариантов регистра, чем обычный lower().
    text = text.casefold().replace("ё", "е")

    # Telegram/клавиатура могут прислать похожие латинские символы.
    # Приводим самые частые визуально похожие буквы к кириллице.
    lookalikes = str.maketrans({
        "a": "а", "e": "е", "o": "о", "c": "с",
        "x": "х", "y": "у", "p": "р", "k": "к",
        "m": "м", "t": "т",
    })
    text = text.translate(lookalikes)

    # Убираем распространённые способы обхода фильтра.
    text = text.replace("*", "")
    text = re.sub(r"[‐‑‒–—−_-]+", " ", text)
    text = re.sub(r"[^а-яa-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def obfuscated_contains_bad_root(text: str) -> bool:
    """Ловит ругань, разбитую знаками/пробелами между буквами."""
    normalized = normalize_text(text)
    if not normalized:
        return False

    # Из каждой фразы берём только буквенные последовательности.
    compact_words = re.findall(r"[а-яa-z0-9]+", normalized)

    for root in BAD_ROOTS:
        if len(root) < 4:
            continue

        # Разрешаем пробелы/символы между буквами корня:
        # "ш-л-ю-х-а", "ш*л*ю*х*а", "ш л ю х а".
        pattern = r"(?<![а-яa-z0-9])" + r"[^а-яa-z0-9]*".join(map(re.escape, root))
        if re.search(pattern, normalized):
            return True

    # Дополнительная проверка по каждому обычному слову.
    for word in compact_words:
        if len(word) >= 4 and any(
            len(root) >= 4 and root in word for root in BAD_ROOTS
        ):
            return True

    return False

# Нормализуем словарь один раз при запуске.
# "его" в исходном списке — обычное слово, поэтому исключаем его,
# чтобы фильтр не блокировал нормальную речь.
COMMON_BAD_WORDS = [
    "блядь", "бля", "ебать", "ебал", "ебан", "ебл", "ебат",
    "пизд", "хуй", "хуя", "хуе", "хуйн", "жоп", "мудак",
    "пидор", "гандон", "шлюх", "дроч", "манда", "сосать",
    "сучара", "сука", "уеб", "заеб", "доеб", "наеб", "выеб",
    "разъеб", "оху", "поху"
]
BAD_WORDS_NORMALIZED = {
    normalize_text(word)
    for word in BAD_WORDS + COMMON_BAD_WORDS
    if normalize_text(word) and normalize_text(word) != "его"
}

# Части слов, по которым ловятся обычные формы ругани: "хуйня", "хуйню",
# "ебаный", "пиздец", "блядский" и т.п.
BAD_ROOTS = tuple(sorted({
    normalize_text(x) for x in [
        "бля", "бляд", "еб", "пизд", "хуй", "хуя", "хуе", "хуйн",
        "жоп", "ебан", "ебл", "ебат", "заеб", "доеб", "наеб", "выеб",
        "уеб", "оху", "поху", "шлюх", "дроч", "гандон", "пидор",
        "сучар", "манда"
    ]
}))


def contains_bad_words(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False

    padded = f" {normalized} "

    # Сначала проверяем точные слова и фразы из пользовательского словаря.
    for word in BAD_WORDS_NORMALIZED:
        if " " in word:
            if f" {word} " in padded:
                return True
        elif re.search(r"(?<![а-яa-z0-9])" + re.escape(word) + r"(?![а-яa-z0-9])", normalized):
            return True

    # Затем — корни ругани, чтобы фильтр ловил словоформы.
    for root in BAD_ROOTS:
        if re.search(
            r"(?<![а-яa-z0-9])"
            + re.escape(root)
            + r"[а-яa-z]*",
            normalized
        ):
            return True

    # И варианты, где слово специально разбили символами/пробелами.
    return obfuscated_contains_bad_root(text)


# =========================================================
# РАБОТА С ПОЛЬЗОВАТЕЛЕМ
# =========================================================

def create_user(user_id: int):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
        (user_id,)
    )
    db.commit()

def get_user(user_id: int):
    cursor.execute(
        "SELECT user_id, age_group, gender, searching, partner_id, "
        "messages_sent, conversations_count, contact_offered, "
        "profanity_filter, chat_session_id, search_gender "
        "FROM users WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchone()

def update_user(user_id: int, **fields):
    if not fields:
        return

    allowed = {
        "age_group",
        "gender",
        "searching",
        "partner_id",
        "messages_sent",
        "contact_offered",
        "profanity_filter",
        "chat_session_id",
        "search_gender"
    }

    for key in fields:
        if key not in allowed:
            raise ValueError(f"Недопустимое поле: {key}")

    query = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [user_id]

    cursor.execute(
        f"UPDATE users SET {query} WHERE user_id = ?",
        values
    )
    db.commit()

# =========================================================
# ЗАВЕРШЕНИЕ ТЕКУЩЕГО ДИАЛОГА
# =========================================================

async def close_current_chat(
    user_id: int,
    partner_text: str = "❌ Собеседник завершил диалог.",
):
    user = get_user(user_id)

    if not user:
        return None

    partner_id = user[4]

    update_user(
        user_id,
        partner_id=None,
        searching=0,
        messages_sent=0,
        contact_offered=0,
        chat_session_id=None
    )

    if partner_id:
        partner = get_user(partner_id)
        if partner and partner[4] == user_id:
            update_user(
                partner_id,
                partner_id=None,
                searching=0,
                messages_sent=0,
                contact_offered=0,
                chat_session_id=None
            )

        try:
            await bot.send_message(
                partner_id,
                partner_text,
                reply_markup=main_keyboard
            )
        except Exception as e:
            print("Не удалось уведомить собеседника:", e)

    return partner_id

# =========================================================
# ИСТОРИЯ ТЕКУЩЕГО ЧАТА / ЖАЛОБЫ
# =========================================================

def save_chat_message(session_id: str, sender_id: int, message_id: int):
    cursor.execute(
        "INSERT INTO chat_messages (session_id, sender_id, message_id) "
        "VALUES (?, ?, ?)",
        (session_id, sender_id, message_id)
    )
    db.commit()


def ensure_chat_session(user_id: int, partner_id: int) -> str:
    """Guarantees that both sides of the current chat have the same session ID."""
    user = get_user(user_id)
    partner = get_user(partner_id)

    if not user or not partner:
        return ""

    session_id = user[9] or partner[9] or uuid.uuid4().hex

    if user[9] != session_id:
        update_user(user_id, chat_session_id=session_id)
    if partner[9] != session_id:
        update_user(partner_id, chat_session_id=session_id)

    return session_id


async def send_full_chat_to_admin(
    reporter_id: int,
    partner_id: int,
    session_id: str | None
):
    if not ADMIN_ID:
        return

    if not session_id:
        session_id = ensure_chat_session(reporter_id, partner_id)

    if not session_id:
        await bot.send_message(
            ADMIN_ID,
            f"🚨 Жалоба\nОт: {reporter_id}\nНа: {partner_id}\n"
            "Не удалось создать идентификатор чата."
        )
        return

    cursor.execute(
        "SELECT sender_id, message_id FROM chat_messages "
        "WHERE session_id = ? ORDER BY id",
        (session_id,)
    )
    messages = cursor.fetchall()

    await bot.send_message(
        ADMIN_ID,
        "🚨 ЖАЛОБА\n\n"
        f"👤 Жалоба от: {reporter_id}\n"
        f"🎯 Жалоба на: {partner_id}\n"
        f"💬 Сообщений в чате: {len(messages)}\n\n"
        "Ниже — полный чат в порядке отправки."
    )

    for sender_id, message_id in messages:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"👤 От пользователя {sender_id}:"
            )
            await bot.copy_message(
                chat_id=ADMIN_ID,
                from_chat_id=sender_id,
                message_id=message_id
            )
        except Exception as e:
            print(
                f"Не удалось передать админу сообщение "
                f"{message_id} от {sender_id}: {e}"
            )

    await bot.send_message(
        ADMIN_ID,
        "✅ Передача полной истории жалобы завершена."
    )


def incoming_filter_enabled(partner_id: int) -> bool:
    partner = get_user(partner_id)
    if not partner:
        return False

    # Фильтр доступен только взрослым.
    return partner[1] != "17 и младше" and bool(partner[8])


def filter_label(user_id: int) -> str:
    user = get_user(user_id)
    return "ВЫКЛ" if not user or not user[8] else "ВКЛ"


# =========================================================
# АДМИН: ПРОСМОТР ДИАЛОГОВ
# =========================================================

def is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID) and user_id == ADMIN_ID


def get_active_sessions():
    cursor.execute("""
        SELECT DISTINCT u.chat_session_id, u.user_id, u.partner_id
        FROM users u
        WHERE u.chat_session_id IS NOT NULL
          AND u.partner_id IS NOT NULL
        ORDER BY u.chat_session_id
    """)
    return cursor.fetchall()


def get_all_sessions():
    cursor.execute("""
        SELECT session_id,
               MIN(created_at) AS started_at,
               COUNT(*) AS message_count,
               GROUP_CONCAT(DISTINCT sender_id) AS participants
        FROM chat_messages
        GROUP BY session_id
        ORDER BY MIN(id) DESC
    """)
    return cursor.fetchall()


async def send_session_to_admin(session_id: str, title: str = "💬 Диалог"):
    cursor.execute("""
        SELECT sender_id, message_id, created_at
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY id
    """, (session_id,))
    messages = cursor.fetchall()

    if not messages:
        return False

    participants = sorted({row[0] for row in messages})
    await bot.send_message(
        ADMIN_ID,
        f"{title}\n\n"
        f"🆔 Сессия: {session_id}\n"
        f"👥 Участники: {', '.join(map(str, participants))}\n"
        f"💬 Сообщений: {len(messages)}\n\n"
        "История ниже:"
    )

    for sender_id, message_id, created_at in messages:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"👤 {sender_id} | {created_at}"
            )
            await bot.copy_message(
                chat_id=ADMIN_ID,
                from_chat_id=sender_id,
                message_id=message_id
            )
        except Exception as e:
            await bot.send_message(
                ADMIN_ID,
                f"⚠️ Не удалось показать сообщение {message_id} "
                f"от {sender_id}: {e}"
            )

    return True


# =========================================================
# СТАТИСТИКА РАЗГОВОРОВ
# =========================================================

def increment_conversations(user_id: int, partner_id: int):
    """Считает каждый найденный чат один раз для обоих пользователей."""
    cursor.execute(
        "UPDATE users SET conversations_count = conversations_count + 1 "
        "WHERE user_id IN (?, ?)",
        (user_id, partner_id)
    )
    db.commit()


def get_conversations_count(user_id: int) -> int:
    user = get_user(user_id)
    return int(user[6]) if user else 0


def partner_info_text(partner_id: int) -> str:
    partner = get_user(partner_id)
    if not partner:
        return "👥 Собеседник сейчас недоступен."

    return (
        "👥 Собеседник\n\n"
        f"🎂 Возраст: {partner[1]}\n"
        f"🚻 Пол: {partner[2]}\n"
        f"💬 Разговоров: {partner[6]}"
    )


def my_profile_text(user_id: int) -> str:
    user = get_user(user_id)
    if not user:
        return "Профиль не найден."

    return (
        "👤 Мой профиль\n\n"
        f"🎂 Возраст: {user[1] or 'не указан'}\n"
        f"🚻 Пол: {user[2] or 'не указан'}\n"
        f"💬 Разговоров: {user[6]}"
        f"\n🔎 Ищу: {user[10] or 'не выбрано'}" +
        (f"\n🤬 Фильтр матов: {('ВКЛ' if user[8] else 'ВЫКЛ')}"
         if user[1] != "17 и младше" else "")
    )

# =========================================================
# СОВМЕСТИМОСТЬ
# =========================================================

def compatible(user1, user2) -> bool:
    age1, age2 = user1[1], user2[1]
    gender1, gender2 = user1[2], user2[2]
    wanted1 = user1[10] or "🤷 Неважно"
    wanted2 = user2[10] or "🤷 Неважно"

    # Несовершеннолетние — только с несовершеннолетними.
    if (age1 == "17 и младше") != (age2 == "17 и младше"):
        return False

    # Желание пользователя должно совпадать с полом собеседника.
    # "Неважно" подходит к любому полу.
    if wanted1 != "🤷 Неважно" and wanted1 != gender2:
        return False
    if wanted2 != "🤷 Неважно" and wanted2 != gender1:
        return False

    return True

# =========================================================
# ПОИСК СОБЕСЕДНИКА
# =========================================================

async def find_partner(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        create_user(user_id)
        user = get_user(user_id)

    if not user[1] or not user[2]:
        await message.answer(
            "Сначала выбери возраст и пол через /start."
        )
        return

    if not user[10]:
        await message.answer(
            "Сначала выбери, кого искать.",
            reply_markup=search_gender_keyboard
        )
        return

    if user[4] is not None:
        await message.answer("У тебя уже есть собеседник.")
        return

    cursor.execute("""
        SELECT user_id, age_group, gender, searching, partner_id,
               messages_sent, conversations_count, contact_offered, search_gender
        FROM users
        WHERE searching = 1
          AND user_id != ?
          AND partner_id IS NULL
        ORDER BY user_id
    """, (user_id,))

    candidates = cursor.fetchall()

    for candidate in candidates:
        candidate_for_match = (
            candidate[0], candidate[1], candidate[2], candidate[3], candidate[4],
            candidate[5], candidate[6], candidate[7], 0, None, candidate[8]
        )
        if not compatible(user, candidate_for_match):
            continue

        partner_id = candidate[0]
        session_id = uuid.uuid4().hex

        update_user(
            user_id,
            searching=0,
            partner_id=partner_id,
            messages_sent=0,
            contact_offered=0,
            chat_session_id=session_id
        )
        update_user(
            partner_id,
            searching=0,
            partner_id=user_id,
            messages_sent=0,
            contact_offered=0,
            chat_session_id=session_id
        )

        increment_conversations(user_id, partner_id)

        user_info = partner_info_text(partner_id)
        partner_info = partner_info_text(user_id)

        await bot.send_message(
            user_id,
            "✅ Собеседник найден!\n\n"
            "Общение анонимное. Можешь писать.\n\n"
            + user_info,
            reply_markup=chat_keyboard
        )

        await bot.send_message(
            partner_id,
            "✅ Собеседник найден!\n\n"
            "Общение анонимное. Можешь писать.\n\n"
            + partner_info,
            reply_markup=chat_keyboard
        )
        return

    update_user(user_id, searching=1)

    await message.answer(
        "🔎 Ищу собеседника...\n"
        "Подожди немного."
    )

# =========================================================
# АДМИН-ПАНЕЛЬ
# =========================================================

@dp.message(F.text == "/admin")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 Админ-панель\n\n"
        "Здесь можно посмотреть текущие и сохранённые диалоги.",
        reply_markup=admin_keyboard
    )


@dp.message(F.text == "👁 Все активные диалоги")
async def admin_active_dialogs(message: Message):
    if not is_admin(message.from_user.id):
        return

    sessions = get_active_sessions()
    if not sessions:
        await message.answer("👁 Сейчас активных диалогов нет.", reply_markup=admin_keyboard)
        return

    # DISTINCT здесь не гарантирует уникальность, если оба пользователя
    # попали в выборку, поэтому дополнительно убираем дубли.
    unique = {}
    for session_id, user_id, partner_id in sessions:
        unique[session_id] = (user_id, partner_id)

    await message.answer(
        f"👁 Активных диалогов: {len(unique)}\n"
        "Сейчас отправлю их истории."
        , reply_markup=admin_keyboard
    )

    for session_id, (user_id, partner_id) in unique.items():
        await send_session_to_admin(
            session_id,
            title=f"🟢 АКТИВНЫЙ ДИАЛОГ\n👥 {user_id} ↔ {partner_id}"
        )

    await message.answer("✅ Все активные диалоги показаны.", reply_markup=admin_keyboard)


@dp.message(F.text == "🗂 Все сохранённые диалоги")
async def admin_all_dialogs(message: Message):
    if not is_admin(message.from_user.id):
        return

    sessions = get_all_sessions()
    if not sessions:
        await message.answer("🗂 Сохранённых диалогов пока нет.", reply_markup=admin_keyboard)
        return

    await message.answer(
        f"🗂 Найдено сохранённых диалогов: {len(sessions)}\n"
        "Отправляю истории по очереди. Это может занять время.",
        reply_markup=admin_keyboard
    )

    for session_id, started_at, message_count, participants in sessions:
        await send_session_to_admin(
            session_id,
            title=f"🗂 СОХРАНЁННЫЙ ДИАЛОГ\n📅 {started_at}\n👥 {participants or 'неизвестно'}"
        )

    await message.answer("✅ Все сохранённые диалоги показаны.", reply_markup=admin_keyboard)


@dp.message(F.text == "🔙 Выйти из админки")
async def admin_exit(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🔙 Вышел из админ-панели.", reply_markup=main_keyboard)


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id

    create_user(user_id)

    current = get_user(user_id)
    if current and current[4]:
        await close_current_chat(
            user_id,
            "⚙️ Собеседник заново открыл бота. Диалог завершён."
        )

    update_user(
        user_id,
        searching=0,
        partner_id=None,
        messages_sent=0,
        contact_offered=0,
        chat_session_id=None
    )

    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Выбери свой возраст:",
        reply_markup=age_keyboard
    )

# =========================================================
# МЕНЮ
# =========================================================

@dp.message(F.text == "☰ Меню")
async def menu(message: Message):
    user_id = message.from_user.id
    await message.answer(
        "☰ Меню\n\n"
        "Здесь можно посмотреть профиль, статистику и изменить настройки.",
        reply_markup=menu_keyboard_for(user_id)
    )


@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    user_id = message.from_user.id
    create_user(user_id)

    await message.answer(
        my_profile_text(user_id),
        reply_markup=menu_keyboard_for(user_id)
    )


@dp.message(F.text == "👥 Собеседник")
async def partner_profile(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user or not user[4]:
        await message.answer(
            "👥 Сейчас у тебя нет собеседника.",
            reply_markup=menu_keyboard_for(user_id)
        )
        return

    await message.answer(
        partner_info_text(user[4]),
        reply_markup=menu_keyboard_for(user_id)
    )


@dp.message(F.text == "📊 Моя статистика")
async def statistics(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        await message.answer(
            "Сначала напиши /start.",
            reply_markup=main_keyboard
        )
        return

    await message.answer(
        "📊 Твоя статистика\n\n"
        f"💬 Всего разговоров: {user[6]}\n"
        f"✉️ Сообщений в текущем разговоре: {user[5]}",
        reply_markup=menu_keyboard_for(user_id)
    )


@dp.message(F.text == "🎂 Сменить возраст")
async def change_age(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        await message.answer("Сначала напиши /start.")
        return

    if user[4]:
        await close_current_chat(
            user_id,
            "⚙️ Собеседник изменяет настройки. Диалог завершён."
        )

    update_user(user_id, searching=0)

    await message.answer(
        "🎂 Выбери новый возраст:",
        reply_markup=age_keyboard
    )


@dp.message(F.text == "🚻 Сменить пол")
async def change_gender(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        await message.answer("Сначала напиши /start.")
        return

    if user[4]:
        await close_current_chat(
            user_id,
            "⚙️ Собеседник изменяет настройки. Диалог завершён."
        )

    update_user(user_id, searching=0)

    await message.answer(
        "🚻 Выбери новый пол:",
        reply_markup=gender_keyboard
    )


@dp.message(F.text.in_([
    "🤬 Фильтр матов: ВКЛ",
    "🤬 Фильтр матов: ВЫКЛ"
]))
async def toggle_profanity_filter(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        await message.answer("Сначала напиши /start.")
        return

    if user[1] == "17 и младше":
        await message.answer(
            "⚠️ Эта настройка доступна только для 18+.",
            reply_markup=menu_keyboard_for(user_id)
        )
        return

    # Переключаем именно по нажатой кнопке, чтобы ВКЛ/ВЫКЛ всегда работал.
    new_value = 0 if message.text == "🤬 Фильтр матов: ВКЛ" else 1
    update_user(user_id, profanity_filter=new_value)

    status = "включён ✅" if new_value else "выключен ❌"
    await message.answer(
        f"🤬 Фильтр матов {status}.\n"
        "Он скрывает ругательства от тебя в текущих и новых чатах.",
        reply_markup=menu_keyboard_for(user_id)
    )


@dp.message(F.text == "ℹ️ Помощь")
async def help_menu(message: Message):
    user_id = message.from_user.id

    await message.answer(
        "ℹ️ Как пользоваться ботом\n\n"
        "🔎 Найти собеседника — начать поиск.\n"
        "➡️ Следующий — завершить текущий чат и искать другого.\n"
        "🛑 Стоп — завершить чат.\n"
        "🚨 Пожаловаться — отправить жалобу.\n"
        "☰ Меню — профиль и настройки.\n\n"
        "💬 В карточке собеседника видно, сколько разговоров у него уже было.\n"
        "🤬 Для 18+ в меню можно включить фильтр матов.\n"
        "🚫 Для 17 и младше нельзя отправлять голосовые и видео.",
        reply_markup=menu_keyboard_for(user_id)
    )


@dp.message(F.text == "🔙 Назад")
async def menu_back(message: Message):
    await message.answer(
        "🔙 Главное меню.",
        reply_markup=main_keyboard
    )

# =========================================================
# ВОЗРАСТ
# =========================================================

@dp.message(F.text.in_([
    "17 и младше",
    "18–21",
    "22–25",
    "26–30"
]))
async def choose_age(message: Message):
    create_user(message.from_user.id)
    current = get_user(message.from_user.id)

    if current and current[4]:
        await close_current_chat(
            message.from_user.id,
            "⚙️ Собеседник изменяет настройки. Диалог завершён."
        )

    update_user(
        message.from_user.id,
        age_group=message.text,
        partner_id=None,
        searching=0,
        messages_sent=0,
        chat_session_id=None,
        profanity_filter=0 if message.text == "17 и младше" else get_user(message.from_user.id)[8]
    )

    await message.answer(
        "Теперь выбери пол:",
        reply_markup=gender_keyboard
    )

# =========================================================
# ПОЛ
# =========================================================

@dp.message(F.text.in_([
    "👨 Парень",
    "👩 Девушка",
    "🤷 Неважно"
]))
async def choose_gender(message: Message):
    create_user(message.from_user.id)
    current = get_user(message.from_user.id)

    if current and current[4]:
        await close_current_chat(
            message.from_user.id,
            "⚙️ Собеседник изменяет настройки. Диалог завершён."
        )

    update_user(
        message.from_user.id,
        gender=message.text,
        partner_id=None,
        searching=0,
        messages_sent=0
    )

    await message.answer(
        "✅ Настройка закончена.\n\n"
        "Нажми «🔎 Найти собеседника».",
        reply_markup=main_keyboard
    )

# =========================================================
# ПОИСК
# =========================================================

@dp.message(F.text == "🔎 Найти собеседника")
async def search(message: Message):
    user = get_user(message.from_user.id)

    if not user or not user[1] or not user[2]:
        await message.answer(
            "Сначала настрой профиль через /start."
        )
        return

    if user[4] is not None:
        await message.answer("У тебя уже есть собеседник.")
        return

    if user[3]:
        await message.answer("Я уже ищу тебе собеседника.")
        return

    await message.answer(
        "🔎 Кого хочешь найти?\n\n"
        "Выбери пол собеседника:",
        reply_markup=search_gender_keyboard
    )


@dp.message(F.text.in_([
    "🔎 👨 Парень",
    "🔎 👩 Девушка",
    "🔎 🤷 Неважно"
]))
async def choose_search_gender(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user or not user[1] or not user[2]:
        await message.answer("Сначала настрой профиль через /start.")
        return

    if user[4] is not None:
        await message.answer("У тебя уже есть собеседник.", reply_markup=chat_keyboard)
        return

    if user[3]:
        await message.answer("Я уже ищу тебе собеседника.")
        return

    target_gender = message.text.replace("🔎 ", "", 1)
    update_user(user_id, search_gender=target_gender)

    await message.answer(
        f"🔎 Ищу: {target_gender}\n\nПодожди немного.",
        reply_markup=main_keyboard
    )
    await find_partner(message)

# =========================================================
# СЛЕДУЮЩИЙ
# =========================================================

@dp.message(F.text == "➡️ Следующий")
async def next_partner(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        await message.answer("Сначала напиши /start.")
        return

    if user[4]:
        await close_current_chat(user_id)

    await message.answer("➡️ Ищу нового собеседника...")
    await find_partner(message)

# =========================================================
# СТОП
# =========================================================

@dp.message(F.text == "🛑 Стоп")
async def stop(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        return

    await close_current_chat(user_id)

    await message.answer(
        "🛑 Диалог завершён.",
        reply_markup=main_keyboard
    )

# =========================================================
# ЖАЛОБА
# =========================================================

@dp.message(F.text == "🚨 Пожаловаться")
async def report(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        return

    partner_id = user[4]

    if not partner_id:
        await message.answer(
            "🚨 Сейчас нет активного собеседника для жалобы.",
            reply_markup=main_keyboard
        )
        return

    session_id = user[9]

    if ADMIN_ID:
        try:
            await send_full_chat_to_admin(
                reporter_id=user_id,
                partner_id=partner_id,
                session_id=session_id
            )
        except Exception as e:
            print("Не удалось передать полный чат админу:", e)

    await close_current_chat(
        user_id,
        "🚨 На вас пожаловались. Диалог завершён."
    )

    await message.answer(
        "🚨 Жалоба отправлена. Диалог завершён.",
        reply_markup=main_keyboard
    )

# =========================================================
# ПРОВЕРКА: МОЖНО ЛИ ОБМЕНИВАТЬСЯ НОМЕРАМИ
# =========================================================

def both_reached_ten(user_id: int, partner_id: int) -> bool:
    user = get_user(user_id)
    partner = get_user(partner_id)

    if not user or not partner:
        return False

    return user[5] >= 10 and partner[5] >= 10

async def offer_contact_exchange(user_id: int, partner_id: int):
    if not both_reached_ten(user_id, partner_id):
        return

    user = get_user(user_id)
    partner = get_user(partner_id)

    if not user or not partner:
        return

    # Показываем предложение только один раз за текущий разговор.
    if user[7] or partner[7]:
        return

    update_user(user_id, contact_offered=1)
    update_user(partner_id, contact_offered=1)

    text = (
        "📱 Вы оба отправили друг другу минимум 10 сообщений.\n\n"
        "Теперь можете обменяться номерами."
    )

    await bot.send_message(
        user_id,
        text,
        reply_markup=contact_keyboard
    )
    await bot.send_message(
        partner_id,
        text,
        reply_markup=contact_keyboard
    )

# =========================================================
# КОНТАКТ
# =========================================================

@dp.message(F.contact)
async def contact(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user or not user[4]:
        await message.answer("Сейчас у тебя нет собеседника.")
        return

    partner_id = user[4]

    if not both_reached_ten(user_id, partner_id):
        await message.answer(
            "❌ Обмен номерами доступен только после "
            "10 сообщений от каждого."
        )
        return

    await bot.send_contact(
        chat_id=partner_id,
        phone_number=message.contact.phone_number,
        first_name=message.contact.first_name or "Контакт"
    )

    session_id = ensure_chat_session(user_id, partner_id)
    if session_id:
        save_chat_message(session_id, user_id, message.message_id)

    await message.answer(
        "✅ Номер отправлен собеседнику.",
        reply_markup=chat_keyboard
    )

# =========================================================
# ПЕРЕСЫЛКА СООБЩЕНИЙ
# =========================================================

@dp.message()
async def relay_message(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        return

    partner_id = user[4]

    if not partner_id:
        await message.answer(
            "Сейчас у тебя нет собеседника.",
            reply_markup=main_keyboard
        )
        return

    age_group = user[1]
    session_id = ensure_chat_session(user_id, partner_id)
    user = get_user(user_id)

    # Для 17 и младше:
    # фотографии разрешены, но голосовые и видео запрещены.
    if age_group == "17 и младше":
        if message.voice:
            await message.answer(
                "🚫 Голосовые сообщения отправлять нельзя."
            )
            return

        if message.video or message.video_note:
            await message.answer(
                "🚫 Видео отправлять нельзя."
            )
            return

    # Для 18+ пользователь может сам включить фильтр матов.
    # Фильтр работает на входящие сообщения именно для получателя.
    incoming_text = message.text or message.caption or ""

    if incoming_filter_enabled(partner_id) and incoming_text:
        # Если пользователь уже включил фильтр, он не получает ругань.
        # Проверяем сообщение ДО пересылки и не считаем его в лимит 10.
        if contains_bad_words(incoming_text):
            try:
                await bot.send_message(
                    partner_id,
                    "🤬 Сообщение скрыто фильтром матов."
                )
            except Exception as e:
                print("Не удалось уведомить собеседника:", e)

            await message.answer(
                "🤬 Сообщение не отправлено: у собеседника "
                "включён фильтр матов."
            )
            return

    try:
        await bot.copy_message(
            chat_id=partner_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        if session_id:
            save_chat_message(
                session_id=session_id,
                sender_id=user_id,
                message_id=message.message_id
            )

        cursor.execute("""
            UPDATE users
            SET messages_sent = messages_sent + 1
            WHERE user_id = ?
        """, (user_id,))
        db.commit()

        await offer_contact_exchange(user_id, partner_id)

    except Exception as e:
        print("Ошибка при пересылке сообщения:", e)


# =========================================================
# ЗАПУСК
# =========================================================

async def main():
    print("🤖 Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        db.close()
