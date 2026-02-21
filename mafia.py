#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import random
import asyncio
import traceback
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Ошибка: переменная окружения BOT_TOKEN не задана!", file=sys.stderr)
    sys.exit(1)

ADMIN_IDS = [123456789]  # Замените на свои ID (можно узнать у @userinfobot)
# =====================

logging.basicConfig(level=logging.INFO, stream=sys.stderr)

print("✅ Бот: импорты выполнены, токен получен", file=sys.stderr)

try:
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    print("✅ Бот: объекты Bot и Dispatcher созданы", file=sys.stderr)
except Exception as e:
    print(f"❌ Ошибка при создании бота: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

games = {}

ALL_ROLES = [
    'мафия', 'дон', 'комиссар', 'доктор', 'любовница', 'маньяк',
    'адвокат', 'шериф', 'якудза', 'путана', 'вор', 'бомж',
    'дед мороз', 'самоубийца', 'телохранитель', 'снайпер',
    'журналист', 'бессмертный', 'оборотень', 'мирный'
]

NIGHT_ROLES = [
    'мафия', 'дон', 'комиссар', 'доктор', 'любовница', 'маньяк',
    'путана', 'вор', 'дед мороз', 'самоубийца', 'телохранитель',
    'снайпер', 'журналист', 'оборотень'
]

class MafiaGame:
    def __init__(self, chat_id, creator_id):
        self.chat_id = chat_id
        self.creator_id = creator_id
        self.players = {}
        self.phase = 'registration'
        self.night_actions = {}
        self.day_votes = {}
        self.sniper_used = False
        self.immortal_alive = True
        self.yakuza_avenged = False

    def add_player(self, user_id, name):
        if user_id not in self.players and len(self.players) < 20:
            self.players[user_id] = {'name': name, 'role': None, 'alive': True}
            return True
        return False

    def remove_player(self, user_id):
        if user_id in self.players:
            del self.players[user_id]
            return True
        return False

    def start_game(self):
        if len(self.players) < 4:
            return False
        players_list = list(self.players.keys())
        random.shuffle(players_list)
        num = len(players_list)
        num_mafia = max(1, num // 3)

        roles_pool = []
        for i in range(num_mafia):
            roles_pool.append('дон' if i == 0 else 'мафия')
        unique_roles = [r for r in ALL_ROLES if r not in ('мафия', 'дон', 'мирный')]
        random.shuffle(unique_roles)
        for r in unique_roles:
            if len(roles_pool) < num:
                roles_pool.append(r)
        while len(roles_pool) < num:
            roles_pool.append('мирный')
        random.shuffle(roles_pool)

        for uid, role in zip(players_list, roles_pool):
            self.players[uid]['role'] = role
        self.phase = 'night'
        return True

    def alive_players(self, exclude=None):
        return [uid for uid, p in self.players.items() if p['alive'] and uid != exclude]

    def get_players_by_role(self, role, alive_only=True):
        return [uid for uid, p in self.players.items() if p['role'] == role and (not alive_only or p['alive'])]

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

    def set_hooker(self, target_id):
        self.night_actions['hooker'] = target_id

    def set_thief(self, target_id):
        self.night_actions['thief'] = target_id

    def set_frost_protect(self, target_id):
        self.night_actions['frost_protect'] = target_id

    def set_suicide_kill(self, target_id):
        self.night_actions['suicide_kill'] = target_id

    def set_bodyguard(self, target_id):
        self.night_actions['bodyguard'] = target_id

    def set_werewolf_kill(self, target_id):
        self.night_actions['werewolf_kill'] = target_id

    def resolve_night(self):
        killed = set()
        blocked = set()
        healed = None

        if 'lover_block' in self.night_actions:
            blocked.add(self.night_actions['lover_block'])
        if 'doctor_heal' in self.night_actions:
            healed = self.night_actions['doctor_heal']
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
                killed.add(target)
        if healed and healed in killed:
            killed.remove(healed)
        immortal_id = self.get_players_by_role('бессмертный', alive_only=True)
        if immortal_id and immortal_id[0] in killed:
            killed.remove(immortal_id[0])
            self.immortal_alive = True
        for uid in list(killed):
            if self.players[uid]['role'] == 'якудза' and not self.yakuza_avenged:
                mafia_list = self.get_players_by_role('мафия', alive_only=True) + self.get_players_by_role('дон', alive_only=True)
                if mafia_list:
                    avenger = random.choice(mafia_list)
                    killed.add(avenger)
                self.yakuza_avenged = True
        return list(killed)

    def apply_deaths(self, killed_ids):
        dead_names = []
        for uid in killed_ids:
            if uid in self.players and self.players[uid]['alive']:
                self.players[uid]['alive'] = False
                dead_names.append(self.players[uid]['name'])
        return dead_names

    def check_winner(self):
        alive = self.alive_players()
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

@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    print(f"🔥 Команда /start от {message.from_user.id}", file=sys.stderr)
    await message.answer(
        "👋 Привет! Я бот для игры в Мафию (20 ролей).\n\n"
        "Команды:\n"
        "/game — создать новую игру в этом чате\n"
        "/join — присоединиться к игре\n"
        "/leave — покинуть игру\n"
        "/start_mafia — начать игру (только создатель)\n"
        "/stop — остановить игру (админ или создатель)\n"
        "/players — список игроков\n\n"
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

@dp.message_handler(commands=['players'])
async def cmd_players(message: types.Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        await message.answer("Нет активной игры.")
        return
    if game.phase == 'registration':
        players_list = "\n".join([p['name'] for p in game.players.values()])
        await message.answer(f"Игроки ({len(game.players)}/20):\n{players_list}")
    else:
        alive = [p['name'] for p in game.players.values() if p['alive']]
        dead = [p['name'] for p in game.players.values() if not p['alive']]
        text = f"Живы ({len(alive)}): {', '.join(alive)}\n"
        if dead:
            text += f"Мертвы: {', '.join(dead)}"
        await message.answer(text)

@dp.message_handler(commands=['stop'])
async def cmd_stop(message: types.Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        await message.answer("Нет активной игры.")
        return
    if message.from_user.id != game.creator_id and message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только создатель игры или администратор может остановить игру.")
        return
    del games[chat_id]
    await message.answer("Игра остановлена.")

@dp.message_handler(commands=['start_mafia'])
async def cmd_start_mafia(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        await message.answer("Нет игры.")
        return
    if message.from_user.id != game.creator_id:
        await message.answer("Только создатель может начать игру.")
        return
    if game.phase != 'registration':
        await message.answer("Игра уже начата.")
        return
    if not game.start_game():
        await message.answer("Недостаточно игроков (нужно минимум 4).")
        return

    for uid, p in game.players.items():
        try:
            await bot.send_message(uid, f"🃏 Твоя роль: *{p['role']}*", parse_mode='Markdown')
        except:
            await message.answer(f"Не удалось отправить личное сообщение игроку {p['name']}.")
    await message.answer("🌙 Наступает ночь. Игроки с активными ролями, проверьте личные сообщения.")
    await start_night_cycle(message, game, state)

async def start_night_cycle(message: types.Message, game: MafiaGame, state: FSMContext):
    chat_id = message.chat.id
    game.night_actions = {}
    for role in NIGHT_ROLES:
        players_with_role = game.get_players_by_role(role, alive_only=True)
        if not players_with_role:
            continue
        for uid in players_with_role:
            targets = game.alive_players(exclude=uid)
            if not targets:
                continue
            markup = InlineKeyboardMarkup(row_width=2)
            for target_uid in targets:
                name = game.players[target_uid]['name'][:15]
                markup.insert(InlineKeyboardButton(name, callback_data=f"night_{role}_{target_uid}"))
            try:
                await bot.send_message(uid, f"🌙 Ночь. Ты — *{role}*. Выбери цель:", reply_markup=markup, parse_mode='Markdown')
            except:
                pass
    await asyncio.sleep(60)
    killed_ids = game.resolve_night()
    dead_names = game.apply_deaths(killed_ids)
    if dead_names:
        await bot.send_message(chat_id, f"☠️ Утром обнаружены тела:\n" + "\n".join(dead_names))
    else:
        await bot.send_message(chat_id, "☀️ Утро наступило, все живы.")
    winner = game.check_winner()
    if winner:
        await bot.send_message(chat_id, f"🏆 Игра окончена! Победили: {winner}!")
        del games[chat_id]
        return
    game.phase = 'day'
    await start_day_vote(message, game, state)

async def start_day_vote(message: types.Message, game: MafiaGame, state: FSMContext):
    chat_id = message.chat.id
    game.day_votes = {}
    alive = game.alive_players()
    if not alive:
        await bot.send_message(chat_id, "❓ Нет живых игроков. Игра завершена.")
        del games[chat_id]
        return
    markup = InlineKeyboardMarkup(row_width=2)
    for uid in alive:
        name = game.players[uid]['name'][:15]
        markup.insert(InlineKeyboardButton(name, callback_data=f"vote_{uid}"))
    await bot.send_message(chat_id, "🗳️ День. Голосуйте за исключение игрока (таймер 60 секунд):", reply_markup=markup)
    await asyncio.sleep(60)
    votes = game.day_votes
    if not votes:
        await bot.send_message(chat_id, "Никто не голосовал. Никого не исключили.")
    else:
        counter = {}
        for target in votes.values():
            counter[target] = counter.get(target, 0) + 1
        max_votes = max(counter.values())
        candidates = [uid for uid, c in counter.items() if c == max_votes]
        if len(candidates) == 1:
            executed = candidates[0]
            game.players[executed]['alive'] = False
            await bot.send_message(chat_id, f"☠️ По результатам голосования исключён {game.players[executed]['name']} (роль: {game.players[executed]['role']}).")
        else:
            await bot.send_message(chat_id, "Голоса разделились – никто не исключён.")
    winner = game.check_winner()
    if winner:
        await bot.send_message(chat_id, f"🏆 Игра окончена! Победили: {winner}!")
        del games[chat_id]
        return
    game.phase = 'night'
    await start_night_cycle(message, game, state)

@dp.callback_query_handler(lambda c: c.data.startswith('night_'))
async def night_callback(callback: types.CallbackQuery):
    _, role, target_id = callback.data.split('_')
    target_id = int(target_id)
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    game = games.get(chat_id)
    if not game:
        await callback.answer("Игра не найдена.")
        return
    if user_id not in game.players or not game.players[user_id]['alive'] or game.players[user_id]['role'] != role:
        await callback.answer("Вы не можете выполнить это действие.")
        return
    if role == 'мафия':
        game.set_mafia_kill(target_id)
    elif role == 'дон':
        game.set_don_check(target_id)
    elif role == 'комиссар':
        game.set_commissar_check(target_id)
    elif role == 'доктор':
        game.set_doctor_heal(target_id)
    elif role == 'любовница':
        game.set_lover_block(target_id)
    elif role == 'маньяк':
        game.set_maniac_kill(target_id)
    elif role == 'путана':
        game.set_hooker(target_id)
    elif role == 'вор':
        game.set_thief(target_id)
    elif role == 'дед мороз':
        game.set_frost_protect(target_id)
    elif role == 'самоубийца':
        game.set_suicide_kill(target_id)
    elif role == 'телохранитель':
        game.set_bodyguard(target_id)
    elif role == 'снайпер':
        if not game.sniper_used:
            game.sniper_used = True
            game.night_actions['sniper_kill'] = target_id
    elif role == 'оборотень':
        game.set_werewolf_kill(target_id)
    await callback.answer("Действие принято.")
    await callback.message.edit_text(f"✅ Ты выбрал цель. Жди результатов.")

@dp.callback_query_handler(lambda c: c.data.startswith('vote_'))
async def vote_callback(callback: types.CallbackQuery):
    _, target_id = callback.data.split('_')
    target_id = int(target_id)
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    game = games.get(chat_id)
    if not game or game.phase != 'day':
        await callback.answer("Сейчас не время для голосования.")
        return
    if user_id not in game.players or not game.players[user_id]['alive']:
        await callback.answer("Вы не можете голосовать.")
        return
    game.day_votes[user_id] = target_id
    await callback.answer("Голос учтён.")
    await callback.message.edit_text(f"✅ Ты проголосовал за {game.players[target_id]['name']}.")

@dp.message_handler()
async def debug_handler(message: types.Message):
    print(f"📩 Получено сообщение: {message.text} от {message.from_user.id}", file=sys.stderr)

async def on_startup(dp):
    try:
        await bot.delete_webhook()
        print("✅ Webhook удалён, запускаем polling...", file=sys.stderr)
    except Exception as e:
        print(f"❌ Ошибка при удалении webhook: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

if __name__ == '__main__':
    print("✅ Бот запускается...", file=sys.stderr)
    try:
        executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка в polling: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
