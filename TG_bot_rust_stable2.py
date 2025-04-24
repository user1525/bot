import logging
import sqlite3
import csv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackContext
)
from datetime import datetime, timedelta
import os

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
CHOOSING, TYPING_APPLICATION, TYPING_ADMIN_INPUT, EDITING = range(4)

# ID каналов для проверки подписки
CHANNEL_RUSTRIC = "@rustrics"
CHANNEL_DENZI = "@denziserver"

# ID админов через запятую
ADMIN_IDS = "7642825895,1947369214"  # Замените на реальные ID админов

# ID чата для уведомлений
NOTIFICATION_CHAT_ID = -1002569594175

# Период проверки старых заявок (в секундах)
CHECK_OLD_APPLICATIONS_INTERVAL = 86400  # 1 день

# Файл для хранения информации о пользователях
USERS_FILE = 'users.csv'

# Глобальная переменная для периода автоудаления (по умолчанию 3 дня)
AUTO_DELETE_DAYS = 3

# Типы команд
TEAM_TYPES = {
    'duo': 'Duo',
    'trio': 'Trio',
    'quad': 'Quad',
    'quad_plus': 'Quad+',
    'clan': 'Клан'
}

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        registration_date TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        app_type TEXT,
        team_type TEXT,
        age TEXT,
        hours TEXT,
        role TEXT,
        online TEXT,
        discord TEXT,
        clan_name TEXT,
        leader_name TEXT,
        required TEXT,
        members_count TEXT,
        date TEXT,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    
    # Создаем таблицу для настроек, если ее нет
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # Пытаемся загрузить сохраненное значение периода автоудаления
    cursor.execute('SELECT value FROM bot_settings WHERE key = "auto_delete_days"')
    result = cursor.fetchone()
    if result:
        global AUTO_DELETE_DAYS
        AUTO_DELETE_DAYS = int(result[0])
    
    conn.commit()
    conn.close()

init_db()

# Инициализация файла пользователей
def init_users_file():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['user_id', 'username', 'registration_date'])

init_users_file()

# Утилиты
def create_button(text, callback_data):
    return InlineKeyboardButton(text, callback_data=callback_data)

def save_user(user_id, username):
    # Сохранение в базу данных
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            'INSERT INTO users (user_id, username, registration_date) VALUES (?, ?, ?)',
            (user_id, username, datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
    conn.commit()
    conn.close()
    
    # Сохранение в CSV файл
    user_exists = False
    with open(USERS_FILE, mode='r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if row and row[0] == str(user_id):
                user_exists = True
                break
    
    if not user_exists:
        with open(USERS_FILE, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([user_id, username, datetime.now().strftime("%d.%m.%Y %H:%M")])

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    try:
        member_rustric = await context.bot.get_chat_member(CHANNEL_RUSTRIC, user.id)
        member_denzi = await context.bot.get_chat_member(CHANNEL_DENZI, user.id)
        return (member_rustric.status in ['member', 'administrator', 'creator'] and 
                member_denzi.status in ['member', 'administrator', 'creator'])
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        return False

async def delete_old_applications(context: CallbackContext):
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    days_ago = (datetime.now() - timedelta(days=AUTO_DELETE_DAYS)).strftime("%d.%m.%Y %H:%M")
    
    cursor.execute('''
    SELECT id, user_id, app_type FROM applications 
    WHERE date < ? AND is_active = 1
    ''', (days_ago,))
    
    old_apps = cursor.fetchall()
    
    for app_id, user_id, app_type in old_apps:
        cursor.execute('UPDATE applications SET is_active = 0 WHERE id = ?', (app_id,))
        
        try:
            message = f"🕒 Ваша заявка на поиск тиммейта была автоматически удалена из системы по истечении {AUTO_DELETE_DAYS} дней."
            if app_type == 'clan':
                message = f"🕒 Ваша заявка на поиск клана была автоматически удалена из системы по истечении {AUTO_DELETE_DAYS} дней."
            
            await context.bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
    
    conn.commit()
    conn.close()
    logger.info(f"Автоматически удалено {len(old_apps)} заявок старше {AUTO_DELETE_DAYS} дней")

async def send_welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 Добро пожаловать в Rust Search Team Bot!\n\n"
        "Этот бот создан для поиска тиммейтов и кланов в игре Rust.\n\n"
        "⭐️ Вы можете зарегистрироваться как соискатель и найти себе команду или как лидер клана и найти новых участников\n\n"
        "✅ Бот абсолютно бесплатный и поможет вам:\n"
        "- Найти надежных тиммейтов\n"
        "- Вступить в активный клан\n"
        "- Создать свою команду\n\n"
        "Для начала работы подпишитесь на наши каналы и нажмите /start"
    )
    
    keyboard = [
        [InlineKeyboardButton("Rustric", url=f"https://t.me/{CHANNEL_RUSTRIC[1:]}")],
        [InlineKeyboardButton("Дэнзи", url=f"https://t.me/{CHANNEL_DENZI[1:]}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=welcome_text,
        reply_markup=reply_markup
    )

async def safe_edit_message(query, text, reply_markup=None):
    if query is None or query.message is None:
        logger.error("Не удалось редактировать сообщение: query или query.message равно None")
        return
    
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.debug("Сообщение не изменено (содержимое идентично)")
        elif "Message to edit not found" in str(e):
            logger.debug("Сообщение для редактирования не найдено, отправляем новое")
            try:
                await query.message.reply_text(
                    text=text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке нового сообщения: {e}")
        else:
            logger.error(f"Ошибка при редактировании сообщения: {e}")

# Главное меню
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_chat or not update.effective_user:
        logger.error("Неверный update в обработчике start")
        return ConversationHandler.END
    
    if not await check_subscription(update, context):
        await send_welcome_message(update, context)
        return ConversationHandler.END
    
    user = update.effective_user
    save_user(user.id, user.username or user.first_name)
    
    context.user_data.clear()
    
    welcome_text = (
        "🔄 <b>Внимание!</b> Вы всегда можете перезапустить бота командой /start\n\n"
        "🏠 <b>Главное меню</b>:"
    )
    
    keyboard = [
        [create_button("🔍 Найти Тиммейта", 'find_teammate')],
        [create_button("🏰 Клан", 'find_clan')],
        [create_button("❌ Удалиться из поиска", 'remove_from_search')],
        [create_button("📚 Гайд по боту", 'guide')]
    ]
    
    # Добавляем кнопку админа только если пользователь админ
    if str(user.id) in ADMIN_IDS.split(','):
        keyboard.append([create_button("👑 Админу", 'admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if update.callback_query:
            try:
                await update.callback_query.answer()
                await safe_edit_message(
                    update.callback_query,
                    welcome_text,
                    reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка при обработке callback_query: {e}")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=welcome_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        return CHOOSING
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        return ConversationHandler.END

# Поиск тиммейта
async def find_teammate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [create_button("👥 Duo", 'duo')],
        [create_button("👥👥 Trio", 'trio')],
        [create_button("👥👥👥 Quad", 'quad')],
        [create_button("👥👥👥+ Quad+", 'quad_plus')],
        [create_button("🔙 Назад в главное меню", 'back_to_main')]
    ]
    
    message_text = '🎮 Выберите тип поиска:'
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

# Поиск клана
async def find_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["app_type"] = "clan"
    
    keyboard = [
        [create_button("📝 Подать Заявку", 'apply_clan')],
        [create_button("📋 Список Заявок", 'list_clan')],
        [create_button("✏️ Мои заявки", 'my_apps_clan')],
        [create_button("🔙 Назад в главное меню", 'back_to_main')]
    ]
    
    message_text = "🏰 Выберите действие для поиска клана:"
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

# Обработчики для типов команд
async def duo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['team_type'] = 'duo'
    context.user_data['app_type'] = 'teammate'
    
    keyboard = [
        [create_button("📝 Подать Заявку", 'apply_duo')],
        [create_button("📋 Список Заявок", 'list_duo')],
        [create_button("✏️ Мои заявки", 'my_apps_duo')],
        [create_button("🔙 Назад", 'back_to_teammate')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    message_text = "👥 Выберите действие для Duo:"
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def trio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['team_type'] = 'trio'
    context.user_data['app_type'] = 'teammate'
    
    keyboard = [
        [create_button("📝 Подать Заявку", 'apply_trio')],
        [create_button("📋 Список Заявок", 'list_trio')],
        [create_button("✏️ Мои заявки", 'my_apps_trio')],
        [create_button("🔙 Назад", 'back_to_teammate')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    message_text = "👥👥 Выберите действие для Trio:"
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def quad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['team_type'] = 'quad'
    context.user_data['app_type'] = 'teammate'
    
    keyboard = [
        [create_button("📝 Подать Заявку", 'apply_quad')],
        [create_button("📋 Список Заявок", 'list_quad')],
        [create_button("✏️ Мои заявки", 'my_apps_quad')],
        [create_button("🔙 Назад", 'back_to_teammate')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    message_text = "👥👥👥 Выберите действие для Quad:"
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def quad_plus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['team_type'] = 'quad_plus'
    context.user_data['app_type'] = 'teammate'
    
    keyboard = [
        [create_button("📝 Подать Заявку", 'apply_quad_plus')],
        [create_button("📋 Список Заявок", 'list_quad_plus')],
        [create_button("✏️ Мои заявки", 'my_apps_quad_plus')],
        [create_button("🔙 Назад", 'back_to_teammate')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    message_text = "👥👥👥+ Выберите действие для Quad+:"
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

# Обработка заявки
async def apply_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    team_type = context.user_data.get('team_type', 'duo')
    app_type = context.user_data.get('app_type', 'teammate')
    
    if app_type == 'teammate':
        message_text = (
            f"📝 Заполните информацию о себе для {TEAM_TYPES.get(team_type, team_type)}:\n\n"
            "Укажите следующие данные (каждый пункт с новой строки):\n"
            "1. Возраст\n"
            "2. Часов в Rust\n"
            "3. Ваша роль в Rust\n"
            "4. Онлайн в день\n"
            "5. Discord для связи\n\n"
            "Пример заполнения заявки:\n\n"
            "24 года\n"
            "11000 часов\n"
            "Комбатёр, Фармила\n"
            "От 5 часов в день\n"
            "exemple#Discord_Vasya"
        )
    else:
        message_text = (
            "📝 Заполните информацию о клане:\n\n"
            "Укажите следующие данные (каждый пункт с новой строки):\n"
            "1. Название клана\n"
            "2. Имя Лидера Клана\n"
            "3. Кто требуется в клан\n"
            "4. Количество людей в клане\n"
            "5. Discord для связи\n\n"
            "Пример:\n"
            "Rust Legends\n"
            "ProPlayer\n"
            "Строители, электрики\n"
            "15\n"
            "clanleader#5678"
        )
    
    keyboard = [
        [create_button("🔙 Назад", f'back_to_{team_type}')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    await safe_edit_message(
        query,
        text=message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return TYPING_APPLICATION

# Сохранение заявки
async def save_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_data = update.message.text.split('\n')
        if len(user_data) != 5:
            await update.message.reply_text("❌ Неверный формат данных. Пожалуйста, укажите все 5 пунктов, каждый с новой строки.")
            return TYPING_APPLICATION
        
        team_type = context.user_data.get('team_type', 'duo')
        app_type = context.user_data.get('app_type', 'teammate')
        user = update.message.from_user
        
        save_user(user.id, user.username or user.first_name)
        
        conn = sqlite3.connect('rust_bot.db')
        cursor = conn.cursor()
        
        if app_type == 'teammate':
            cursor.execute('''
            INSERT INTO applications 
            (user_id, app_type, team_type, age, hours, role, online, discord, date, is_active) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (
                user.id, app_type, team_type, user_data[0].strip(), 
                user_data[1].strip(), user_data[2].strip(), 
                user_data[3].strip(), user_data[4].strip(), 
                datetime.now().strftime("%d.%m.%Y %H:%M")
            ))
            
            # Получаем ID только что созданной заявки
            app_id = cursor.lastrowid
            
            # Формируем сообщение для админского чата
            notification_text = (
                "🆕 <b>Новая заявка на тиммейта</b>\n\n"
                f"👤 Пользователь: @{user.username or user.first_name} (ID: {user.id})\n"
                f"📌 Тип: {TEAM_TYPES.get(team_type, team_type)}\n"
                f"🆔 ID заявки: {app_id}\n\n"
                f"🎂 Возраст: {user_data[0].strip()}\n"
                f"⏱ Часов в Rust: {user_data[1].strip()}\n"
                f"🎮 Роль: {user_data[2].strip()}\n"
                f"⏳ Онлайн в день: {user_data[3].strip()}\n"
                f"📞 Discord: {user_data[4].strip()}\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        else:
            cursor.execute('''
            INSERT INTO applications 
            (user_id, app_type, clan_name, leader_name, required, members_count, discord, date, is_active) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (
                user.id, app_type, user_data[0].strip(), 
                user_data[1].strip(), user_data[2].strip(),
                user_data[3].strip(), user_data[4].strip(),
                datetime.now().strftime("%d.%m.%Y %H:%M")
            ))
            
            # Получаем ID только что созданной заявки
            app_id = cursor.lastrowid
            
            # Формируем сообщение для админского чата
            notification_text = (
                "🆕 <b>Новая заявка на клан</b>\n\n"
                f"👤 Пользователь: @{user.username or user.first_name} (ID: {user.id})\n"
                f"🆔 ID заявки: {app_id}\n\n"
                f"🏰 Название: {user_data[0].strip()}\n"
                f"👑 Лидер: {user_data[1].strip()}\n"
                f"🔍 Требуются: {user_data[2].strip()}\n"
                f"👥 Количество участников: {user_data[3].strip()}\n"
                f"📞 Discord: {user_data[4].strip()}\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        
        conn.commit()
        conn.close()
        
        # Отправляем уведомление в админский чат
        try:
            await context.bot.send_message(
                chat_id=NOTIFICATION_CHAT_ID,
                text=notification_text,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления в админский чат: {e}")
        
        if app_type == 'teammate':
            response = (
                "🎉 🎉 🎉\n\n"
                f"✅ Ваша заявка на {TEAM_TYPES.get(team_type, team_type)} подана:\n\n"
                f"👤 Игрок: {user.username or user.first_name}\n"
                f"🎂 Возраст: {user_data[0].strip()}\n"
                f"⏱ Часов в Rust: {user_data[1].strip()}\n"
                f"🎮 Роль: {user_data[2].strip()}\n"
                f"⏳ Онлайн в день: {user_data[3].strip()}\n"
                f"📞 Discord: {user_data[4].strip()}\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"ℹ️ Заявка будет автоматически удалена через {AUTO_DELETE_DAYS} дней"
            )
        else:
            response = (
                "🎉 🎉 🎉\n\n"
                "✅ Информация о клане сохранена:\n\n"
                f"🏰 Название: {user_data[0].strip()}\n"
                f"👑 Лидер: {user_data[1].strip()}\n"
                f"🔍 Требуются: {user_data[2].strip()}\n"
                f"👥 Количество участников: {user_data[3].strip()}\n"
                f"📞 Discord: {user_data[4].strip()}\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"ℹ️ Заявка будет автоматически удалена через {AUTO_DELETE_DAYS} дней"
            )
        
        await update.message.reply_text(response)
        return await start(update, context)
    
    except Exception as e:
        logger.error(f"Ошибка при сохранении заявки: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при сохранении заявки. Попробуйте позже.")
        return await start(update, context)

# Список заявок с пагинацией
async def list_applications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        
        team_type = context.user_data.get('team_type', 'duo')
        app_type = context.user_data.get('app_type', 'teammate')
        page = context.user_data.get('page', 0)
        
        conn = sqlite3.connect('rust_bot.db')
        cursor = conn.cursor()
        
        if app_type == 'teammate':
            cursor.execute('''
            SELECT u.username, a.age, a.hours, a.role, a.online, a.discord, a.date 
            FROM applications a
            JOIN users u ON a.user_id = u.user_id
            WHERE a.team_type = ? AND a.app_type = ? AND a.is_active = 1
            ORDER BY a.date DESC
            ''', (team_type, app_type))
        else:
            cursor.execute('''
            SELECT u.username, a.clan_name, a.leader_name, a.required, a.members_count, a.discord, a.date 
            FROM applications a
            JOIN users u ON a.user_id = u.user_id
            WHERE a.app_type = ? AND a.is_active = 1
            ORDER BY a.date DESC
            ''', (app_type,))
        
        all_apps = cursor.fetchall()
        conn.close()
        
        if not all_apps:
            keyboard = [
                [create_button("🔙 Назад", f'back_to_{team_type}')],
                [create_button("🏠 Главное меню", 'back_to_main')]
            ]
            await safe_edit_message(
                query,
                f"ℹ️ Нет заявок в категории {TEAM_TYPES.get(team_type, team_type)}.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CHOOSING
        
        # Разбиваем на страницы по 5 заявок
        apps_per_page = 5
        total_pages = (len(all_apps) + apps_per_page - 1) // apps_per_page
        start_idx = page * apps_per_page
        end_idx = start_idx + apps_per_page
        filtered_apps = all_apps[start_idx:end_idx]
        
        if app_type == 'teammate':
            applications_text = f"📋 Список заявок {TEAM_TYPES.get(team_type, team_type)} (Страница {page + 1}/{total_pages}):\n\n"
            for idx, app in enumerate(filtered_apps, start_idx + 1):
                applications_text += (
                    f"{idx}. 👤 {app[0]} ({app[6]})\n"
                    f"   🎂 Возраст: {app[1]}\n"
                    f"   ⏱ Часов: {app[2]}\n"
                    f"   🎮 Роль: {app[3]}\n"
                    f"   ⏳ Онлайн: {app[4]}\n"
                    f"   📞 Discord: {app[5]}\n\n"
                )
        else:
            applications_text = "📋 Список кланов:\n\n"
            for idx, clan in enumerate(filtered_apps, start_idx + 1):
                applications_text += (
                    f"{idx}. 🏰 {clan[1]} ({clan[6]})\n"
                    f"   👑 Лидер: {clan[2]}\n"
                    f"   🔍 Требуются: {clan[3]}\n"
                    f"   👥 Участников: {clan[4]}\n"
                    f"   📞 Discord: {clan[5]}\n\n"
                )
        
        keyboard = []
        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(create_button("⬅️ Предыдущая", f'prev_page_{team_type}'))
            if page < total_pages - 1:
                nav_buttons.append(create_button("➡️ Следующая", f'next_page_{team_type}'))
            if nav_buttons:
                keyboard.append(nav_buttons)
        
        if app_type == 'clan':
            keyboard.append([create_button("🔙 Назад", 'back_from_clan_list')])
        else:
            keyboard.append([create_button(f"🔙 Назад к {TEAM_TYPES.get(team_type, team_type)}", f'back_to_{team_type}')])
        
        keyboard.append([create_button("🏠 Главное меню", 'back_to_main')])
        
        context.user_data['page'] = page
        
        await safe_edit_message(
            query,
            text=applications_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSING
    
    except Exception as e:
        logger.error(f"Ошибка в list_applications: {e}")
        await safe_edit_message(
            query,
            "⚠️ Произошла ошибка при загрузке списка. Попробуйте позже."
        )
        return await start(update, context)
    
# Обработка переключения страниц
async def handle_prev_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['page'] -= 1
    return await list_applications(update, context)

async def handle_next_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['page'] += 1
    return await list_applications(update, context)

# Показать заявки пользователя
async def my_applications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if not update.callback_query:
            logger.error("Ошибка: update.callback_query равно None")
            return await start(update, context)
            
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        team_type = context.user_data.get('team_type', 'duo')
        app_type = context.user_data.get('app_type', 'teammate')
        
        conn = sqlite3.connect('rust_bot.db')
        cursor = conn.cursor()
        
        if app_type == 'teammate':
            cursor.execute('''
            SELECT id, age, hours, role, online, discord, date 
            FROM applications 
            WHERE user_id = ? AND team_type = ? AND app_type = ? AND is_active = 1
            ORDER BY date DESC
            ''', (user_id, team_type, app_type))
        else:
            cursor.execute('''
            SELECT id, clan_name, leader_name, required, members_count, discord, date 
            FROM applications 
            WHERE user_id = ? AND app_type = ? AND is_active = 1
            ORDER BY date DESC
            ''', (user_id, app_type))
        
        apps = cursor.fetchall()
        conn.close()
        
        if not apps:
            keyboard = [
                [create_button("📝 Подать новую заявку", f'apply_{team_type}')],
                [create_button(f"🔙 Назад к {TEAM_TYPES.get(team_type, team_type)}", f'back_to_{team_type}')],
                [create_button("🏠 Главное меню", 'back_to_main')]
            ]
            await safe_edit_message(
                query,
                f"ℹ️ У вас нет активных заявок в категории {TEAM_TYPES.get(team_type, team_type)}.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CHOOSING
        
        if app_type == 'teammate':
            apps_text = f"📋 Ваши заявки {TEAM_TYPES.get(team_type, team_type)}:\n\n"
            for app in apps:
                apps_text += (
                    f"🆔 ID: {app[0]}\n"
                    f"🎂 Возраст: {app[1]}\n"
                    f"⏱ Часов: {app[2]}\n"
                    f"🎮 Роль: {app[3]}\n"
                    f"⏳ Онлайн: {app[4]}\n"
                    f"📞 Discord: {app[5]}\n"
                    f"📅 Дата: {app[6]}\n\n"
                )
        else:
            apps_text = "📋 Ваши заявки кланов:\n\n"
            for app in apps:
                apps_text += (
                    f"🆔 ID: {app[0]}\n"
                    f"🏰 Название: {app[1]}\n"
                    f"👑 Лидер: {app[2]}\n"
                    f"🔍 Требуются: {app[3]}\n"
                    f"👥 Участников: {app[4]}\n"
                    f"📞 Discord: {app[5]}\n"
                    f"📅 Дата: {app[6]}\n\n"
                )
        
        keyboard = []
        for app in apps:
            keyboard.append([
                create_button(f"✏️ Редактировать {app[0]}", f'edit_{app[0]}'),
                create_button(f"❌ Удалить {app[0]}", f'delete_{app[0]}')
            ])
        
        keyboard.extend([
            [create_button("📝 Подать новую заявку", f'apply_{team_type}')],
            [create_button(f"🔙 Назад к {TEAM_TYPES.get(team_type, team_type)}", f'back_to_{team_type}')],
            [create_button("🏠 Главное меню", 'back_to_main')]
        ])
        
        await safe_edit_message(
            query,
            apps_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSING
    
    except Exception as e:
        logger.error(f"Ошибка в my_applications: {e}")
        if update.callback_query:
            await safe_edit_message(
                update.callback_query,
                "⚠️ Произошла ошибка при загрузке ваших заявок. Попробуйте позже."
            )
        return await start(update, context)

# Редактирование заявки
async def edit_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    app_id = int(query.data.split('_')[1])
    context.user_data['editing_app_id'] = app_id
    
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT app_type FROM applications WHERE id = ?', (app_id,))
    app_type = cursor.fetchone()[0]
    
    if app_type == 'teammate':
        cursor.execute('''
        SELECT age, hours, role, online, discord 
        FROM applications 
        WHERE id = ?
        ''', (app_id,))
        
        app_data = cursor.fetchone()
        message_text = (
            "✏️ Редактирование заявки:\n\n"
            "Введите новые данные (каждый пункт с новой строки):\n"
            f"1. Возраст (текущее: {app_data[0]})\n"
            f"2. Часов в Rust (текущее: {app_data[1]})\n"
            f"3. Ваша роль в Rust (текущее: {app_data[2]})\n"
            f"4. Онлайн в день (текущее: {app_data[3]})\n"
            f"5. Discord для связи (текущее: {app_data[4]})\n\n"
            "Пример заполнения заявки:\n\n"
            "24 года\n"
            "11000 часов\n"
            "Комбатёр, Фармила\n"
            "От 5 часов в день\n"
            "exemple#Discord_Vasya"
        )
    else:
        cursor.execute('''
        SELECT clan_name, leader_name, required, members_count, discord 
        FROM applications 
        WHERE id = ?
        ''', (app_id,))
        
        app_data = cursor.fetchone()
        message_text = (
            "✏️ Редактирование информации о клане:\n\n"
            "Введите новые данные (каждый пункт с новой строки):\n"
            f"1. Название клана (текущее: {app_data[0]})\n"
            f"2. Имя Лидера Клана (текущее: {app_data[1]})\n"
            f"3. Кто требуется в клан (текущее: {app_data[2]})\n"
            f"4. Количество людей в клане (текущее: {app_data[3]})\n"
            f"5. Discord для связи (текущее: {app_data[4]})\n\n"
            "Пример:\n"
            "Rust Legends\n"
            "ProPlayer\n"
            "Строители, электрики\n"
            "15\n"
            "clanleader#5678"
        )
    
    conn.close()
    
    keyboard = [
        [create_button("❌ Отменить редактирование", 'cancel_edit')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    await safe_edit_message(
        query,
        text=message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDITING

# Сохранение отредактированной заявки
async def save_edited_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_data = update.message.text.split('\n')
        if len(user_data) != 5:
            await update.message.reply_text("❌ Неверный формат данных. Пожалуйста, укажите все 5 пунктов, каждый с новой строки.")
            return EDITING
        
        app_id = context.user_data.get('editing_app_id')
        if not app_id:
            await update.message.reply_text("❌ Ошибка: не найден ID заявки.")
            return await start(update, context)
        
        conn = sqlite3.connect('rust_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT app_type FROM applications WHERE id = ?', (app_id,))
        app_type = cursor.fetchone()[0]
        
        if app_type == 'teammate':
            cursor.execute('''
            UPDATE applications 
            SET age = ?, hours = ?, role = ?, online = ?, discord = ?, date = ?
            WHERE id = ?
            ''', (
                user_data[0].strip(), user_data[1].strip(), user_data[2].strip(),
                user_data[3].strip(), user_data[4].strip(), 
                datetime.now().strftime("%d.%m.%Y %H:%M"), app_id
            ))
            
            cursor.execute('SELECT team_type FROM applications WHERE id = ?', (app_id,))
            team_type = cursor.fetchone()[0]
            context.user_data['team_type'] = team_type
            context.user_data['app_type'] = 'teammate'
            
            response = (
                f"✅ Ваша заявка обновлена:\n\n"
                f"🎂 Возраст: {user_data[0].strip()}\n"
                f"⏱ Часов в Rust: {user_data[1].strip()}\n"
                f"🎮 Роль: {user_data[2].strip()}\n"
                f"⏳ Онлайн в день: {user_data[3].strip()}\n"
                f"📞 Discord: {user_data[4].strip()}\n"
                f"📅 Дата обновления: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        else:
            cursor.execute('''
            UPDATE applications 
            SET clan_name = ?, leader_name = ?, required = ?, members_count = ?, discord = ?, date = ?
            WHERE id = ?
            ''', (
                user_data[0].strip(), user_data[1].strip(), user_data[2].strip(),
                user_data[3].strip(), user_data[4].strip(), 
                datetime.now().strftime("%d.%m.%Y %H:%M"), app_id
            ))
            
            context.user_data['app_type'] = 'clan'
            
            response = (
                "✅ Информация о клане обновлена:\n\n"
                f"🏰 Название: {user_data[0].strip()}\n"
                f"👑 Лидер: {user_data[1].strip()}\n"
                f"🔍 Требуются: {user_data[2].strip()}\n"
                f"👥 Количество участников: {user_data[3].strip()}\n"
                f"📞 Discord: {user_data[4].strip()}\n"
                f"📅 Дата обновления: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        
        conn.commit()
        conn.close()
        
        await update.message.reply_text(response)
        return await my_applications(update, context)
    
    except Exception as e:
        logger.error(f"Ошибка при обновлении заявки: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при обновлении заявки. Попробуйте позже.")
        return await start(update, context)

# Удаление заявки
async def delete_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    app_id = int(query.data.split('_')[1])
    user = query.from_user
    
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    # Получаем информацию о заявке перед удалением
    cursor.execute('''
    SELECT app_type, team_type, age, hours, role, online, discord, 
           clan_name, leader_name, required, members_count 
    FROM applications 
    WHERE id = ?
    ''', (app_id,))
    
    app_info = cursor.fetchone()
    
    # Обновляем статус заявки (не удаляем полностью)
    cursor.execute('UPDATE applications SET is_active = 0 WHERE id = ?', (app_id,))
    conn.commit()
    conn.close()
    
    # Формируем сообщение для админского чата
    if app_info[0] == 'teammate':
        notification_text = (
            "🗑 <b>Заявка удалена</b>\n\n"
            f"👤 Пользователь: @{user.username or user.first_name} (ID: {user.id})\n"
            f"📌 Тип: {TEAM_TYPES.get(app_info[1], app_info[1])}\n"
            f"🆔 ID заявки: {app_id}\n\n"
            f"🎂 Возраст: {app_info[2]}\n"
            f"⏱ Часов: {app_info[3]}\n"
            f"🎮 Роль: {app_info[4]}\n"
            f"⏳ Онлайн: {app_info[5]}\n"
            f"📞 Discord: {app_info[6]}"
        )
    else:
        notification_text = (
            "🗑 <b>Заявка на клан удалена</b>\n\n"
            f"👤 Пользователь: @{user.username or user.first_name} (ID: {user.id})\n"
            f"🆔 ID заявки: {app_id}\n"
            f"🏰 Название клана: {app_info[7]}\n"
            f"👑 Лидер: {app_info[8]}"
        )
    
    # Отправляем уведомление в админский чат
    try:
        await context.bot.send_message(
            chat_id=NOTIFICATION_CHAT_ID,
            text=notification_text,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления в админский чат: {e}")
    
    await safe_edit_message(
        query,
        "✅ Заявка успешно удалена."
    )
    return await my_applications(update, context)

# Удаление из поиска
async def remove_from_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT 1 FROM applications WHERE user_id = ? AND is_active = 1', (user_id,))
    has_apps = cursor.fetchone() is not None
    
    conn.close()
    
    keyboard = [
        [create_button("✅ Да, удалить мои заявки", 'confirm_remove')],
        [create_button("❌ Нет, оставить всё как есть", 'cancel_remove')],
        [create_button("🔙 Назад в главное меню", 'back_to_main')]
    ]
    
    message_text = "❓ Вы уверены, что хотите прекратить поиск?\n\n"
    if has_apps:
        message_text += "У вас есть активные заявки в поиске\n"
    else:
        message_text += "У вас нет активных заявок в поиске"
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def confirm_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = query.from_user
    
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    # Получаем все активные заявки пользователя перед удалением
    cursor.execute('''
    SELECT id, app_type, team_type FROM applications 
    WHERE user_id = ? AND is_active = 1
    ''', (user_id,))
    
    user_apps = cursor.fetchall()
    
    # Обновляем статус заявок (не удаляем полностью)
    cursor.execute('UPDATE applications SET is_active = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    # Формируем сообщение для админского чата
    if user_apps:
        apps_list = "\n".join(
            f"🆔 {app[0]} | 📌 {app[1]}{'/'+app[2] if app[2] else ''}"
            for app in user_apps
        )
        notification_text = (
            "🗑 <b>Пользователь удалил все свои заявки</b>\n\n"
            f"👤 Пользователь: @{user.username or user.first_name} (ID: {user.id})\n"
            f"🔢 Количество заявок: {len(user_apps)}\n\n"
            f"📋 Список удаленных заявок:\n{apps_list}"
        )
        
        # Отправляем уведомление в админский чат
        try:
            await context.bot.send_message(
                chat_id=NOTIFICATION_CHAT_ID,
                text=notification_text,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления в админский чат: {e}")
    
    await safe_edit_message(
        query,
        "✅ Все ваши заявки успешно удалены из поиска."
    )
    return await start(update, context)

async def cancel_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    await safe_edit_message(
        query,
        "❌ Удаление отменено. Ваши заявки остаются активными."
    )
    return await start(update, context)

# Гайд по боту
async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    guide_text = (
        "📚 Гайд по боту:\n\n"
        "1. Используйте кнопки для навигации\n"
        "2. Заполняйте заявки полностью и правдиво\n"
        "3. Для выхода используйте 'Удалиться из поиска'\n"
        "4. Не указывайте личную информацию кроме Discord\n"
        "5. Будьте вежливы с другими игроками\n"
        "6. Если что-то не работает, удалите чат и заново войдите\n\n"
        "Приятной игры! 🎮"
    )
    
    keyboard = [[create_button("🔙 Назад в главное меню", 'back_to_main')]]
    
    await safe_edit_message(
        query,
        guide_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

# Админ-панель
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if str(user.id) not in ADMIN_IDS.split(','):
        await query.edit_message_text("⛔ У вас нет прав доступа к этой панели.")
        return await start(update, context)
    
    admin_text = f"👑 <b>МЕНЮ АДМИНИСТРАТОРА БОТА</b>:\n\nТекущий период автоудаления: {AUTO_DELETE_DAYS} дней"
    
    keyboard = [
        [create_button("📋 Полный список заявок", 'admin_all_apps')],
        [create_button("🕒 Изменить период автоудаления", 'admin_set_autodelete')],
        [create_button("⚠️ Список жалоб", 'admin_complaints')],
        [create_button("🏆 Конкурсы", 'admin_contests')],
        [create_button("🔙 Назад", 'back_to_main')]
    ]
    
    await safe_edit_message(
        query,
        admin_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def admin_set_autodelete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if str(user.id) not in ADMIN_IDS.split(','):
        await query.edit_message_text("⛔ У вас нет прав доступа к этой панели.")
        return await start(update, context)
    
    message_text = f"🕒 Текущий период автоудаления: {AUTO_DELETE_DAYS} дней\n\nВыберите новый период:"
    
    keyboard = [
        [create_button("1 день", 'admin_set_days_1')],
        [create_button("2 дня", 'admin_set_days_2')],
        [create_button("3 дня", 'admin_set_days_3')],
        [create_button("4 дня", 'admin_set_days_4')],
        [create_button("5 дней", 'admin_set_days_5')],
        [create_button("7 дней", 'admin_set_days_7')],
        [create_button("🔙 Назад", 'admin_panel')]
    ]
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def admin_set_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    global AUTO_DELETE_DAYS
    days = int(query.data.split('_')[-1])
    AUTO_DELETE_DAYS = days
    
    # Сохраняем настройку в базу данных
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    # Создаем таблицу для настроек, если ее нет
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # Сохраняем значение
    cursor.execute('''
    INSERT OR REPLACE INTO bot_settings (key, value) 
    VALUES ('auto_delete_days', ?)
    ''', (str(days),))
    
    conn.commit()
    conn.close()
    
    # Отправляем уведомление в админский чат
    notification_text = (
        f"⚙️ <b>Изменен период автоудаления</b>\n\n"
        f"👤 Администратор: @{query.from_user.username or query.from_user.first_name}\n"
        f"🕒 Новый период: {days} дней"
    )
    
    try:
        await context.bot.send_message(
            chat_id=NOTIFICATION_CHAT_ID,
            text=notification_text,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления в админский чат: {e}")
    
    await safe_edit_message(
        query,
        f"✅ Период автоудаления изменен на {days} дней."
    )
    return await admin_panel(update, context)

async def admin_delete_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if str(user.id) not in ADMIN_IDS.split(','):
        await query.edit_message_text("⛔ У вас нет прав доступа к этой панели.")
        return await start(update, context)
    
    message_text = "🗑 Введите ID заявки, которую нужно удалить:"
    
    keyboard = [[create_button("🔙 Назад к списку", 'admin_all_apps')]]
    
    await safe_edit_message(
        query,
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['awaiting_app_id'] = True
    return TYPING_ADMIN_INPUT

async def admin_confirm_delete_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        app_id = int(update.message.text)
        context.user_data['app_to_delete'] = app_id
        
        conn = sqlite3.connect('rust_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM applications WHERE id = ? AND is_active = 1', (app_id,))
        exists = cursor.fetchone()
        conn.close()
        
        if not exists:
            await update.message.reply_text("❌ Заявка не найдена или уже удалена.")
            return await admin_all_applications(update, context)
            
        keyboard = [
            [create_button("✅ Да, удалить", 'admin_execute_delete')],
            [create_button("❌ Нет, отменить", 'admin_all_apps')]
        ]
        
        await update.message.reply_text(
            f"❓ Вы уверены, что хотите удалить заявку #{app_id}?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSING
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите число.")
        return TYPING_ADMIN_INPUT

async def admin_execute_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    app_id = context.user_data.get('app_to_delete')
    if not app_id:
        await query.edit_message_text("❌ Ошибка: ID заявки не найден.")
        return await admin_all_applications(update, context)
    
    user = update.effective_user
    
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    # Получаем информацию о заявке перед удалением
    cursor.execute('''
    SELECT a.user_id, u.username, a.app_type, a.team_type, a.clan_name, a.leader_name
    FROM applications a
    JOIN users u ON a.user_id = u.user_id
    WHERE a.id = ? AND a.is_active = 1
    ''', (app_id,))
    
    app_info = cursor.fetchone()
    
    if not app_info:
        await query.edit_message_text("❌ Заявка не найдена или уже удалена.")
        return await admin_all_applications(update, context)
    
    user_id, username, app_type, team_type, clan_name, leader_name = app_info
    
    # Удаляем заявку
    cursor.execute('UPDATE applications SET is_active = 0 WHERE id = ?', (app_id,))
    conn.commit()
    conn.close()
    
    # Уведомляем пользователя
    try:
        message = f"❌ Ваша заявка (ID: {app_id}) была удалена администратором."
        await context.bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    
    # Отправляем уведомление в админский чат
    if app_type == 'teammate':
        notification_text = (
            "🗑 <b>Заявка удалена администратором</b>\n\n"
            f"👤 Администратор: @{user.username or user.first_name}\n"
            f"👤 Пользователь: @{username} (ID: {user_id})\n"
            f"🆔 ID заявки: {app_id}\n"
            f"📌 Тип: {TEAM_TYPES.get(team_type, team_type)}"
        )
    else:
        notification_text = (
            "🗑 <b>Заявка на клан удалена администратором</b>\n\n"
            f"👤 Администратор: @{user.username or user.first_name}\n"
            f"👤 Пользователь: @{username} (ID: {user_id})\n"
            f"🆔 ID заявки: {app_id}\n"
            f"🏰 Название клана: {clan_name}\n"
            f"👑 Лидер: {leader_name}"
        )
    
    try:
        await context.bot.send_message(
            chat_id=NOTIFICATION_CHAT_ID,
            text=notification_text,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления в админский чат: {e}")
    
    await query.edit_message_text(f"✅ Заявка {app_id} успешно удалена.")
    return await admin_all_applications(update, context)

async def admin_all_applications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if str(user.id) not in ADMIN_IDS.split(','):
        await query.edit_message_text("⛔ У вас нет прав доступа к этой панели.")
        return await start(update, context)
    
    page = context.user_data.get('admin_page', 0)
    apps_per_page = 10
    
    conn = sqlite3.connect('rust_bot.db')
    cursor = conn.cursor()
    
    # Получаем общее количество заявок
    cursor.execute('SELECT COUNT(*) FROM applications')
    total_apps = cursor.fetchone()[0]
    
    # Получаем заявки для текущей страницы
    cursor.execute('''
    SELECT a.id, u.username, a.app_type, a.team_type, a.date, a.is_active 
    FROM applications a
    JOIN users u ON a.user_id = u.user_id
    ORDER BY a.date DESC
    LIMIT ? OFFSET ?
    ''', (apps_per_page, page * apps_per_page))
    
    apps = cursor.fetchall()
    conn.close()
    
    if not apps:
        await safe_edit_message(
            query,
            "ℹ️ В базе нет заявок.",
            reply_markup=InlineKeyboardMarkup([[create_button("🔙 Назад", 'admin_panel')]])
        )
        return CHOOSING
    
    apps_text = f"📋 <b>Список заявок (страница {page + 1}/{(total_apps + apps_per_page - 1) // apps_per_page}):</b>\n\n"
    for app in apps:
        status = "✅ Активна" if app[5] else "❌ Неактивна"
        apps_text += (
            f"🆔 {app[0]} | 👤 {app[1]} | "
            f"📌 {app[2]}{'/'+app[3] if app[3] else ''} | "
            f"📅 {app[4]} | {status}\n"
        )
    
    keyboard = []
    
    # Кнопки навигации по страницам
    if page > 0:
        keyboard.append([create_button("⬅️ Предыдущая страница", 'admin_prev_page')])
    if (page + 1) * apps_per_page < total_apps:
        keyboard.append([create_button("➡️ Следующая страница", 'admin_next_page')])
    
    # Кнопка удаления заявки
    keyboard.append([create_button("🗑 Удалить заявку", 'admin_delete_app')])
    
    keyboard.append([create_button("🔙 Назад", 'admin_panel')])
    
    context.user_data['admin_page'] = page
    
    await safe_edit_message(
        query,
        apps_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def admin_next_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['admin_page'] = context.user_data.get('admin_page', 0) + 1
    return await admin_all_applications(update, context)

async def admin_prev_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['admin_page'] = max(0, context.user_data.get('admin_page', 0) - 1)
    return await admin_all_applications(update, context)

async def admin_complaints(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if str(user.id) not in ADMIN_IDS.split(','):
        await query.edit_message_text("⛔ У вас нет прав доступа к этой панели.")
        return await start(update, context)
    
    complaints_text = "⚠️ <b>Список жалоб:</b>\n\n"
    complaints_text += "Функционал в разработке. Здесь будет отображаться список жалоб от пользователей."
    
    keyboard = [
        [create_button("🔙 Назад", 'admin_panel')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    await safe_edit_message(
        query,
        complaints_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

async def admin_contests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if str(user.id) not in ADMIN_IDS.split(','):
        await query.edit_message_text("⛔ У вас нет прав доступа к этой панели.")
        return await start(update, context)
    
    contests_text = "🏆 <b>Управление конкурсами:</b>\n\n"
    contests_text += "Функционал в разработке. Здесь будет управление конкурсами."
    
    keyboard = [
        [create_button("🔙 Назад", 'admin_panel')],
        [create_button("🏠 Главное меню", 'back_to_main')]
    ]
    
    await safe_edit_message(
        query,
        contests_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING

# Основная функция для запуска бота
async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer("❌ Редактирование отменено.")
    return await start(update, context)

async def my_apps_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['app_type'] = 'clan'
    context.user_data['team_type'] = 'clan'
    return await my_applications(update, context)

async def back_to_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возвращает в меню клана (используется в других местах)."""
    return await find_clan(update, context)

async def back_from_clan_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возвращает в меню выбора действий для клана."""
    return await find_clan(update, context)

def main() -> None:
    application = ApplicationBuilder().token("118050186477:AAHaULshRa8ZdnIe8SV5sAEjjBwT487FtCw").build()
    
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(msg="Exception while handling an update:", exc_info=context.error)
        if update and update.callback_query:
            try:
                await update.callback_query.answer("⚠️ Произошла ошибка. Попробуйте позже.")
            except:
                pass
    
    application.add_error_handler(error_handler)
    
    # Добавляем задачу для периодической проверки старых заявок
    if application.job_queue:
        application.job_queue.run_repeating(
            delete_old_applications,
            interval=CHECK_OLD_APPLICATIONS_INTERVAL,
            first=10
        )
    else:
        logger.warning("JobQueue не доступен. Автоматическое удаление старых заявок не будет работать.")
    
    # Настройка ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING: [
                CallbackQueryHandler(find_teammate, pattern='^find_teammate$'),
                CallbackQueryHandler(find_clan, pattern='^find_clan$'),
                CallbackQueryHandler(remove_from_search, pattern='^remove_from_search$'),
                CallbackQueryHandler(guide, pattern='^guide$'),
                CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
                CallbackQueryHandler(admin_complaints, pattern='^admin_complaints$'),
                CallbackQueryHandler(admin_contests, pattern='^admin_contests$'),
                CallbackQueryHandler(admin_set_autodelete, pattern='^admin_set_autodelete$'),
                CallbackQueryHandler(admin_delete_app, pattern='^admin_delete_app$'),
                CallbackQueryHandler(admin_set_days, pattern='^admin_set_days_'),
                CallbackQueryHandler(admin_all_applications, pattern='^admin_all_apps$'),
                CallbackQueryHandler(admin_next_page, pattern='^admin_next_page$'),
                CallbackQueryHandler(admin_prev_page, pattern='^admin_prev_page$'),
                CallbackQueryHandler(admin_execute_delete, pattern='^admin_execute_delete$'),
                
                # Обработчики для типов команд
                CallbackQueryHandler(duo, pattern='^duo$'),
                CallbackQueryHandler(trio, pattern='^trio$'),
                CallbackQueryHandler(quad, pattern='^quad$'),
                CallbackQueryHandler(quad_plus, pattern='^quad_plus$'),
                
                # Обработчики для кнопок "Назад"
                CallbackQueryHandler(find_teammate, pattern='^back_to_teammate$'),
                CallbackQueryHandler(duo, pattern='^back_to_duo$'),
                CallbackQueryHandler(trio, pattern='^back_to_trio$'),
                CallbackQueryHandler(quad, pattern='^back_to_quad$'),
                CallbackQueryHandler(quad_plus, pattern='^back_to_quad_plus$'),
                CallbackQueryHandler(find_clan, pattern='^back_to_clan$'),
                
                # Обработчики для клана
                CallbackQueryHandler(apply_application, pattern='^apply_clan$'),
                CallbackQueryHandler(list_applications, pattern='^list_clan$'),
                CallbackQueryHandler(my_apps_clan, pattern='^my_apps_clan$'),
                CallbackQueryHandler(back_from_clan_list, pattern='^back_from_clan_list$'),
                
                # Обработчики для тиммейтов
                CallbackQueryHandler(apply_application, pattern='^apply_(duo|trio|quad|quad_plus)$'),
                CallbackQueryHandler(list_applications, pattern='^list_(duo|trio|quad|quad_plus)$'),
                CallbackQueryHandler(my_applications, pattern='^my_apps_(duo|trio|quad|quad_plus)$'),
                
                # Общие обработчики
                CallbackQueryHandler(edit_application, pattern='^edit_'),
                CallbackQueryHandler(delete_application, pattern='^delete_'),
                CallbackQueryHandler(confirm_remove, pattern='^confirm_remove$'),
                CallbackQueryHandler(cancel_remove, pattern='^cancel_remove$'),
                CallbackQueryHandler(handle_prev_page, pattern='^prev_page_'),
                CallbackQueryHandler(handle_next_page, pattern='^next_page_'),
                CallbackQueryHandler(cancel_edit, pattern='^cancel_edit$'),
                
                # Навигация
                CallbackQueryHandler(start, pattern='^back_to_main$'),
            ],
            TYPING_APPLICATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_application),
                CallbackQueryHandler(start, pattern='^back_to_main$'),
            ],
            TYPING_ADMIN_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_confirm_delete_app),
                CallbackQueryHandler(start, pattern='^back_to_main$'),
            ],
            EDITING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_application),
                CallbackQueryHandler(cancel_edit, pattern='^cancel_edit$'),
            ]
        },
        fallbacks=[CommandHandler('start', start)],
        per_message=False
    )
    
    application.add_handler(conv_handler)
    
    # Добавляем тестовую команду для проверки
    async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Бот работает! Используйте /start")
    
    application.add_handler(CommandHandler('test', test))
    
    logger.info("Бот запущен и ожидает сообщений...")
    application.run_polling()

if __name__ == '__main__':
    main()
