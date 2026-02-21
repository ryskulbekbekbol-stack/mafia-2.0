#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

# ================== ТВОЙ ТОКЕН ==================
BOT_TOKEN = "YOUR_BOT_TOKEN"  # ВСТАВЬ СЮДА ТОКЕН ОТ @BOTFATHER
# =================================================

# ================== АДМИНИСТРАТОРЫ ==================
ADMINS = [123456789]  # Замени на свои ID
# ====================================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Хранилище игр по chat_id
games = {}

# ================== БАЗА ДАННЫХ ==================
class Database:
    def __init__(self, db_file='mafia.db'):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 1000,
                purchased_roles TEXT DEFAULT '',
                anonymity INTEGER DEFAULT 0,
                rename_used INTEGER DEFAULT 0
            )
        ''')
        self.conn.commit()

    def get_balance(self, user_id):
        self.cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        else:
            self.cursor.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
            self.conn.commit()
            return 1000

    def update_balance(self, user_id, amount):
        current = self.get_balance(user_id)
        new_balance = current + amount
        self.cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        self.conn.commit()
        return new_balance

    def can_afford(self, user_id, cost):
        if user_id in ADMINS:
            return True
        return self.get_balance(user_id) >= cost

    def spend(self, user_id, cost):
        if user_id in ADMINS:
            return True  # админы тратят "бесконечно"
        current = self.get_balance(user_id)
        if current >= cost:
            self.update_balance(user_id, -cost)
            return True
        return False

    def add_purchased_role(self, user_id, role):
        self.cursor.execute('SELECT purchased_roles FROM users WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        roles = row[0].split(',') if row and row[0] else []
        if role not in roles:
            roles.append(role)
            self.cursor.execute('UPDATE users SET purchased_roles = ? WHERE user_id = ?', (','.join(roles), user_id))
            self.conn.commit()

    def get_purchased_roles(self, user_id):
        self.cursor.execute('SELECT purchased_roles FROM users WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        return row[0].split(',') if row and row[0] else []

    def clear_purchased_roles(self, user_id):
        self.cursor.execute('UPDATE users SET purchased_roles = "" WHERE user_id = ?', (user_id,))
        self.conn.commit()

    def has_anonymity(self, user_id):
        self.cursor.execute('SELECT anonymity FROM users WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        return row and row[0] == 1

    def buy_anonymity(self, user_id):
        if self.spend(user_id, 200):
            self.cursor.execute('UPDATE users SET anonymity = 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        return False

    def has_rename(self, user_id):
        self.cursor.execute('SELECT rename_used FROM users WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        return row and row[0] == 1

    def buy_rename(self, user_id):
        if self.spend(user_id, 150):
            self.cursor.execute('UPDATE users SET rename_used = 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        return False

db = Database()

# ================== ВСЕ РОЛИ (20) ==================
ALL_ROLES = [
    'мафия', 'дон', 'комиссар', 'доктор', 'любовница', 'маньяк',
    'адвокат', 'шериф', 'якудза', 'путана', 'вор', 'бомж',
    'дед мороз', 'самоубийца', 'телохранитель', 'снайпер',
    'журналист', 'бессмертный', 'оборотень', 'мирный'
]

# Роли, доступные для покупки в магазине
SHOP_ROLES = ['мафия', 'комиссар', 'доктор', 'маньяк', 'адвокат', 'путана']

# Цены на роли
ROLE_PRICES = {role: 500 for role in SHOP_ROLES}

# ================== КЛАСС ИГРЫ ==================
class MafiaGame:
    def __init__(self, chat_id, creator_id):
        self.chat_id = chat_id
        self.creator_id = creator_id
        self.players = {}          # user_id -> {'name':, 'role':, 'alive':}
        self.phase = 'registration'
        self.night_actions = {}     # ночные действия
        self.day_votes = {}         # голоса днём
        self.sniper_used = False
        self.lawyer_used = False
        self.immortal_alive = True
        self.purchased_roles = {}   # user_id -> купленная роль (если есть)

    def add_player(self, user_id, name):
        if user_id not in self.players and len(self.players) < 20:
            self.players[user_id] = {'name': name, 'role': None, 'alive': True}
            # Если у игрока есть купленная роль в БД, запоминаем
            purchased = db.get_purchased_roles(user_id)
            if purchased:
                # Берём первую купленную роль (можно доработать)
                self.purchased_roles[user_id] = purchased[0]
            return True
        return False

    def remove_player(self, user_id):
        if user_id in self.players:
            del self.players[user_id]
            if user_id in self.purchased_roles:
                del self.purchased_roles[user_id]
            return True
        return False

    def start_game(self):
        if len(self.players) < 4:
            return False
        players_list = list(self.players.keys())
        random.shuffle(players_list)
        num = len(players_list)

        # Определяем количество мафии (≈1/3)
        num_mafia = max(1, num // 3)

        # Формируем пул ролей с учётом купленных
        # Сначала выделяем роли тем, кто их купил
        assigned_roles = {}
        for uid, role in self.purchased_roles.items():
            if uid in players_list:
                assigned_roles[uid] = role
                players_list.remove(uid)  # убираем из общего списка

        # Оставшиеся роли
        remaining_roles = []
        # Добавляем мафию и дона
        for i in range(num_mafia):
            remaining_roles.append('дон' if i == 0 else 'мафия')
        # Добавляем уникальные роли
        unique_roles = [r for r in ALL_ROLES if r not in ('мафия', 'дон', 'мирный')]
        random.shuffle(unique_roles)
        for r in unique_roles:
            if len(remaining_roles) < num - len(assigned_roles):
                remaining_roles.append(r)
        # Остаток – мирные
        while len(remaining_roles) < num - len(assigned_roles):
            remaining_roles.append('мирный')

        random.shuffle(remaining_roles)

        # Назначаем роли оставшимся игрокам
        for uid in players_list:
            assigned_roles[uid] = remaining_roles.pop(0)

        # Записываем в self.players
        for uid, role in assigned_roles.items():
            self.players[uid]['role'] = role

        # Очищаем купленные роли в БД (чтобы не использовались повторно)
        for uid in self.purchased_roles:
            db.clear_purchased_roles(uid)

        self.phase = 'night'
        return True

    def get_alive_players(self, exclude=None):
        return [uid for uid, p in self.players.items() if p['alive'] and uid != exclude]

    def get_players_by_role(self, role, alive_only=True):
        return [uid for uid, p in self.players.items() if p['role'] == role and (not alive_only or p['alive'])]

    # ========== НОЧНЫЕ ДЕЙСТВИЯ ==========
    def set_mafia_kill(self, target_id):
        self.night_actions['mafia_kill'] = target_id

    def set_don_check(self, target_id):
        self.night_actions['don_check'] = target_id

    def set_commissar_check(self, target_id):
        self.night_actions['commissar_check'] = target_id

    def set_doctor_heal(self, target_id):
        self.night_actions['doctor_heal'] = target_id

    def set_lover_block(self, target_id):
        self.night_actions['lover_block'] = target_id

    def set_maniac_kill(self, target_id):
        self.night_actions['maniac_kill'] = target_id

    def set_bodyguard(self, target_id):
        self.night_actions['bodyguard'] = target_id

    def set_frost_protect(self, target_id):
        self.night_actions['frost_protect'] = target_id

    def set_suicide_kill(self, target_id):
        self.night_actions['suicide_kill'] = target_id

    def set_hooker(self, target_id):
        self.night_actions['hooker'] = target_id

    def set_thief(self, target_id):
        self.night_actions['thief'] = target_id

    def set_werewolf_kill(self, target_id):
        self.night_actions['werewolf_kill'] = target_id

    # ========== РАЗРЕШЕНИЕ НОЧИ ==========
    def resolve_night(self):
        killed = set()
        blocked = set()
        healed = None

        if 'lover_block' in self.night_actions:
            blocked.add(self.night_actions['lover_block'])

        if 'doctor_heal' in self.night_actions:
            healed = self.night_actions['doctor_heal']

        bodyguard_id = None
        if 'bodyguard' in self.night_actions:
            bodyguard_target = self.night_actions['bodyguard']
            bodyguard_id = self.get_players_by_role('телохранитель', alive_only=True)
            if bodyguard_id:
                bodyguard_id = bodyguard_id[0]
                self.night_actions['bodyguard_protect'] = (bodyguard_id, bodyguard_target)

        frost_protected = self.night_actions.get('frost_protect')

        if 'maniac_kill' in self.night_actions:
            target = self.night_actions['maniac_kill']
            if target not in blocked:
                killed.add(target)

        if 'werewolf_kill' in self.night_actions:
            target = self.night_actions['werewolf_kill']
            if target not in blocked:
                killed.add(target)

        if 'suicide_kill' in self.night_actions:
            target = self.night_actions['suicide_kill']
            suicide_id = self.get_players_by_role('самоубийца', alive_only=True)
            if suicide_id and suicide_id[0] not in killed and suicide_id[0] not in blocked:
                killed.add(suicide_id[0])
                killed.add(target)

        if 'mafia_kill' in self.night_actions:
            target = self.night_actions['mafia_kill']
            if target not in blocked and self.players[target]['role'] != 'бомж':
                if 'bodyguard_protect' in self.night_actions:
                    bg_id, bg_target = self.night_actions['bodyguard_protect']
                    if target == bg_target:
                        killed.add(bg_id)
                    else:
                        killed.add(target)
                else:
                    killed.add(target)

        if healed and healed in killed:
            killed.remove(healed)

        immortal_id = self.get_players_by_role('бессмертный', alive_only=True)
        if immortal_id and immortal_id[0] in killed:
            killed.remove(immortal_id[0])
            self.immortal_alive = True

        return list(killed)

    def apply_deaths(self, killed_ids):
        dead_names = []
        for uid in killed_ids:
            if uid in self.players and self.players[uid]['alive']:
                self.players[uid]['alive'] = False
                # Если у убитого есть анонимность, не показываем роль
                if db.has_anonymity(uid):
                    dead_names.append(f"{self.players[uid]['name']} (роль скрыта)")
                else:
                    dead_names.append(f"{self.players[uid]['name']} ({self.players[uid]['role']})")
        return dead_names

    def check_winner(self):
        alive = self.get_alive_players()
        if not alive:
            return 'никто'

        mafia_count = 0
        don_count = 0
        maniac_count = 0
        werewolf_count = 0
        peaceful = 0
        for uid in alive:
            role = self.players[uid]['role']
            if role in ('мафия', 'дон'):
                mafia_count += 1
                if role == 'дон':
                    don_count += 1
            elif role == 'маньяк':
                maniac_count += 1
            elif role == 'оборотень':
                werewolf_count += 1
            else:
                peaceful += 1

        if mafia_count == 0 and maniac_count == 0 and werewolf_count == 0:
            return 'мирные'
        if peaceful == 0 and maniac_count == 0 and werewolf_count == 0:
            return 'мафия'
        if peaceful == 0 and mafia_count == 0 and werewolf_count == 0:
            return 'маньяк'
        if peaceful == 0 and mafia_count == 0 and maniac_count == 0:
            return 'оборотень'
        return None

# ================== СОСТОЯНИЯ FSM ==================
class MafiaStates(StatesGroup):
    night_action = State()
    day_vote = State()

# ================== ОБЩЕНИЕ МАФИИ ==================
@dp.message_handler(lambda message: message.chat.type == 'private', state='*')
async def mafia_chat(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text
    if not text.startswith('!м'):
        return

    for game in games.values():
        if user_id in game.players and game.players[user_id]['alive'] and game.players[user_id]['role'] in ('мафия', 'дон'):
            members = game.get_players_by_role('мафия', alive_only=True) + game.get_players_by_role('дон', alive_only=True)
            for uid in members:
                if uid != user_id:
                    try:
                        await bot.send_message(uid, f"💬 Мафия {game.players[user_id]['name']}: {text[2:].strip()}")
                    except:
                        pass
            break

# ================== КОМАНДЫ ==================
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для игры в Мафию (20 ролей).\n\n"
        "Команды:\n"
        "/game — создать новую игру в этом чате\n"
        "/join — присоединиться к игре\n"
        "/leave — покинуть игру\n"
        "/start_mafia — начать игру (только создатель)\n"
        "/stop — остановить игру (админ или создатель)\n"
        "/shop — магазин ролей\n"
        "/docs — документы и услуги\n"
        "/balance — мой баланс\n"
        "/transfer @user сумма — перевести кристаллы\n\n"
        "Во время игры мафия может общаться в личке с ботом, начиная сообщения с !м ."
    )

@dp.message_handler(commands=['game'])
async def cmd_new_game(message: types.Message):
    chat_id = message.chat.id
    if chat_id in games:
        await message.answer("В этом чате уже есть игра. Используйте /join чтобы присоединиться.")
        return
    games[chat_id] = MafiaGame(chat_id, message.from_user.id)
    games[chat_id].add_player(message.from_user.id, message.from_user.full_name)
    await message.answer(
        "🕵️ Новая игра в Мафию создана!\n"
        "Присоединяйтесь: /join\n"
        "Начать игру может создатель командой /start_mafia"
    )

@dp.message_handler(commands=['join'])
async def cmd_join(message: types.Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        await message.answer("В этом чате нет игры. Создайте: /game")
        return
    if game.phase != 'registration':
        await message.answer("Игра уже началась, присоединиться нельзя.")
        return
    # Инициализация в БД (если нет)
    db.get_balance(message.from_user.id)
    if game.add_player(message.from_user.id, message.from_user.full_name):
        await message.answer(f"{message.from_user.full_name} присоединился к игре. ({len(game.players)}/20)")
    else:
        await message.answer("Вы уже в игре или достигнут лимит.")

@dp.message_handler(commands=['leave'])
async def cmd_leave(message: types.Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        return
    if game.remove_player(message.from_user.id):
        await message.answer(f"{message.from_user.full_name} покинул игру.")
        if len(game.players) == 0:
            del games[chat_id]

@dp.message_handler(commands=['stop'])
async def cmd_stop(message: types.Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        await message.answer("Нет активной игры.")
        return
    if message.from_user.id != game.creator_id and message.from_user.id not in ADMINS:
        await message.answer("❌ Только создатель игры или администратор может остановить игру.")
        return
    del games[chat_id]
    await message.answer("Игра остановлена.")

@dp.message_handler(commands=['balance'])
async def cmd_balance(message: types.Message):
    user_id = message.from_user.id
    balance = db.get_balance(user_id)
    await message.answer(f"💰 Твой баланс: {balance} кристаллов.")

@dp.message_handler(commands=['transfer'])
async def cmd_transfer(message: types.Message):
    args = message.get_args().split()
    if len(args) != 2:
        await message.answer("Использование: /transfer @username сумма")
        return
    target_username = args[0].lstrip('@')
    try:
        amount = int(args[1])
    except:
        await message.answer("Сумма должна быть числом.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть положительной.")
        return
    sender_id = message.from_user.id
    # Ищем получателя по username (упрощённо, но в группах можно по упоминанию)
    # В реальности лучше использовать get_entity, но для простоты предположим, что username уникален
    # Здесь нужно добавить логику поиска user_id по username, но для простоты пропустим
    await message.answer("Функция перевода временно недоступна (нужен поиск по username).")

@dp.message_handler(commands=['shop'])
async def cmd_shop(message: types.Message):
    user_id = message.from_user.id
    balance = db.get_balance(user_id)
    text = f"🛒 Магазин ролей\nТвой баланс: {balance}💰\n\n"
    markup = InlineKeyboardMarkup(row_width=2)
    for role in SHOP_ROLES:
        price = ROLE_PRICES[role]
        text += f"• {role} — {price}💰\n"
        markup.insert(InlineKeyboardButton(f"{role}", callback_data=f"buy_role_{role}"))
    await message.answer(text, reply_markup=markup)

@dp.message_handler(commands=['docs'])
async def cmd_docs(message: types.Message):
    user_id = message.from_user.id
    balance = db.get_balance(user_id)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Скрыть роль при смерти - 200💰", callback_data="buy_anonymity"))
    markup.add(InlineKeyboardButton("Смена ника в игре - 150💰", callback_data="buy_rename"))
    await message.answer(f"📄 Документы и услуги\nБаланс: {balance}💰", reply_markup=markup)

# ================== ОБРАБОТКА ПОКУПОК ==================
@dp.callback_query_handler(lambda c: c.data.startswith('buy_role_'))
async def buy_role_callback(callback: types.CallbackQuery):
    role = callback.data.replace('buy_role_', '')
    user_id = callback.from_user.id
    price = ROLE_PRICES.get(role, 500)
    if db.spend(user_id, price):
        db.add_purchased_role(user_id, role)
        await callback.answer(f"✅ Ты купил роль {role}!")
        await callback.message.edit_text(
