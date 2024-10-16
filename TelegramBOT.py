from datetime import datetime, timedelta
from threading import Thread
import requests
import json
import time
import sqlite3
import re
import telebot
from telebot import types
from private import bot

'''
This telegram bot can check the price of games that you add to the list.
You can send ID of game or link to the Steam.
By default it check price every day at 21 UTC+2.
'''

# flags thar needed for message_handler
running_flag = True
user_states = {'state': None}

# bot initialization with user telegram token
bot = telebot.TeleBot(token=bot())

# add keyboard
keyboard_markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)

'''

Buttons:
Get List - return all games that you add to your list one by one.
Add Game - add new game to the your list, you can send an ID of game or a link to the Steam.
Delete game - delete game from your list, can get only IDs.

'''
btn_get = types.KeyboardButton('Get List')
btn_add = types.KeyboardButton('Add Game')
btn_del = types.KeyboardButton('Delete Game')

# show this keyboard with buttons
keyboard_markup.add(btn_add, btn_del, btn_get)


def create_inline_button_del(game_id, game_name):
    inline_button_del = types.InlineKeyboardButton(
        f'❌❌❌ Delete Game "{game_name}" From The List ❌❌❌',
        callback_data=f'Delete Game {game_name} {game_id}'
    )
    return inline_button_del


print('Bot is running')

'''

#####################################################################
# manipulating DB command for create DB and tests

connection_to_db = sqlite3.connect('database.db')
cursor_db = connection_to_db.cursor()

cursor_db.execute('CREATE TABLE watching_list (id NOT NULL, game_name, price_now, full_price, timer DEFAULT 21600, tlg_id, chat_id)')

cursor_db.execute('ALTER TABLE watching_list ALTER COLUMN ID DEFAULT 21600')
cursor_db.execute('ALTER TABLE watching_list DROP column chat_id')
connection_to_db.commit()

#####################################################################

'''


# REST Request to Steam
def get_data(some_id):
    parameters = {'appids': some_id, 'cc': 'ua'}
    request_to_steam = requests.get('http://store.steampowered.com/api/appdetails', params=parameters)
    json_body = request_to_steam.content.decode()
    unwrap = json.loads(json_body)
    curr_price = (unwrap[str(some_id)]['data']['price_overview']['final']/100)
    price_full = (unwrap[str(some_id)]['data']['price_overview']['initial']/100)
    g_name = unwrap[str(some_id)]['data']['name']
    sale_is = 100 - round(curr_price / price_full * 100)
    # return needed information
    return [some_id, g_name, price_full, curr_price, sale_is]


# Add game to user list
def add_game(message, id_game):
    # create connection to DB file
    connection_to_db = sqlite3.connect('database.db')
    # create manipulating cursor
    cursor_db = connection_to_db.cursor()
    x = get_data(id_game)
    cursor_db.execute(f'SELECT id FROM watching_list WHERE id = ? AND tlg_id = ?', (id_game, message.from_user.id))
    if not cursor_db.fetchall():
        # dont use f strings for execute DB
        cursor_db.execute(
            f'INSERT INTO watching_list (id, game_name, full_price, price_now, tlg_id) VALUES (?,?,?,?,?)',
            (x[0], x[1], x[2], x[3], message.from_user.id))
        # save changes in DB
        connection_to_db.commit()
        return x[1]
    else:
        return 2


# Delete game from user list
def delete_game(message, id_game):
    # create connection to DB file
    connection_to_db = sqlite3.connect('database.db')
    # create manipulating cursor
    cursor_db = connection_to_db.cursor()
    cursor_db.execute(f'SELECT id FROM watching_list WHERE id = ? AND tlg_id = ?', (id_game, message.from_user.id))
    x = cursor_db.fetchone()
    if x:
        cursor_db.execute(
            f"SELECT game_name FROM watching_list WHERE id = ?", (id_game,))
        unsw = cursor_db.fetchone()
        cursor_db.execute('DELETE from watching_list WHERE id = ? AND tlg_id =  ?', (id_game, message.from_user.id))
        connection_to_db.commit()
        return unsw[0]
    else:
        return 0


# update games prices
def update_data():
    connection_to_db = sqlite3.connect('database.db')
    cursor_db = connection_to_db.cursor()
    cursor_db.execute(f'SELECT DISTINCT(id) FROM watching_list')
    x = cursor_db.fetchall()
    for some_id in x:
        # id, Name, Full Price, Current Price
        metadata_game = get_data(some_id[0])
        cursor_db.execute(
            f'UPDATE watching_list SET full_price=?, price_now=? WHERE id = ?',
            (metadata_game[2], metadata_game[3], some_id[0]))
        # save changes in DB
        connection_to_db.commit()
    cursor_db.close()
    connection_to_db.close()


# Handler ADD_GAME button
@bot.message_handler(func=lambda message: user_states.get(message.chat.id, {}).get('state') == 'waiting')
def handle_waiting_input(message):
    user_input = message.text
    # parse links
    try:
        int(user_input)
    except Exception:
        if re.search("/app/[0-9]*/*", user_input):
            parsed_code = (re.search("/app/[0-9]*/*", user_input)).group()
            print(parsed_code[5:-1])
            user_input = parsed_code[5:-1]
    try:
        x = add_game(message, user_input)
        if type(x) == str:
            bot.send_message(message.chat.id, f"You added: {user_input}\n"
                                              f"Name: {x}\nhttps://store.steampowered.com/app/{user_input}")
        elif x == 2:
            bot.send_message(message.chat.id, f"{user_input} already in list")
        else:
            raise Exception
    except Exception:
        bot.send_message(message.chat.id, f"Can`t find ID: {user_input}")
    # Reset the user state
    user_states[message.chat.id] = {}


#  Handler DELETE_GAME button
@bot.message_handler(func=lambda message: user_states.get(message.chat.id, {}).get('state') == 'deleting')
def deleting_input(message):
    user_input = message.text
    try:
        x = delete_game(message, user_input)
        if x != 0:
            bot.send_message(message.chat.id, f"You deleted: {user_input}\nName: {x}")
        else:
            raise Exception
    except Exception:
        bot.send_message(message.chat.id, f"Can`t find ID: {user_input} in list")
    # Reset the user state
    user_states[message.chat.id] = {}


# callback handler
@bot.callback_query_handler(func=lambda call: call.data.startswith('Delete Game'))
def delete_game_callback_handler(call):
    # Extract the game ID and game name from the callback data
    game_id = call.data.split(' ')[-1]
    game_name = call.data.split(' ')[-2]

    try:
        x = delete_game(call, game_id)
        if x != 0:
            bot.answer_callback_query(call.id, text=f'Game {game_name} was deleted')
        else:
            raise Exception
    except Exception:
        bot.answer_callback_query(call.id, text=f'Can`t find the game {game_name} in your list')


# Handler buttons click
@bot.message_handler(func=lambda message: True)
def get_text_messages(message):
    global running_flag

    # Get list of all games in your wishlist
    match message.text:
        case "Get List":
            bot.send_message(message.from_user.id, 'So today prices:\n')
            # create connection to DB file
            connection_to_db = sqlite3.connect('database.db')
            # create manipulating cursor
            cursor_db = connection_to_db.cursor()
            cursor_db.execute('SELECT * FROM watching_list WHERE id <> "" AND tlg_id = ?  ORDER BY game_name',
                              (message.from_user.id,))
            x = cursor_db.fetchall()
            for row in x:
                one_game = get_data(row[0])
                inline_keyboard = types.InlineKeyboardMarkup()
                inline_keyboard.add(create_inline_button_del(one_game[0], one_game[1]))
                try:
                    if one_game[2] == one_game[3]:
                        bot.send_message(message.from_user.id,
                                         f"ID: {one_game[0]}\n"
                                         f"Name: {one_game[1]}\n"
                                         f"Full Price: {one_game[2]} UAH\n"
                                         f"Price Now: {one_game[3]} UAH\n"
                                         f"\n"
                                         f"https://store.steampowered.com/app/{one_game[0]}",
                                         reply_markup=inline_keyboard)
                    else:
                        bot.send_message(message.from_user.id,
                                         f"ID: {one_game[0]}\n"
                                         f"Name: {one_game[1]}\n"
                                         f"Full Price: {one_game[2]} UAH\n"
                                         f"Price Now: {one_game[3]} UAH\n"
                                         f"\n"
                                         f"Sale is {one_game[4]}%\n"
                                         f"https://store.steampowered.com/app/{one_game[0]}",
                                         reply_markup=inline_keyboard)
                except BaseException:
                    # case if user block the bot
                    print("User block the bot")

            connection_to_db.close()

        # add game command abd get ID or URL
        case "Add Game":
            bot.send_message(message.from_user.id, 'Please write the game ID that you want to add:\n')
            user_states[message.chat.id] = {'state': 'waiting'}
        # delete game command and get ID
        case "Delete Game":
            bot.send_message(message.from_user.id, 'Please write the game ID that you want to delete:\n')
            user_states[message.chat.id] = {'state': 'deleting'}
        # command about bot
        case"/info":
            bot.send_message(message.from_user.id, 'This telegram bot can check'
                                                   ' the price of games that you add to the list.\n '
                                                   'You can send ID of game or link to the Steam.\n'
                                                   'By default it check price every day at 21:00 UTC+2.\n\n'
                                                   'Buttons:\n'
                                                   'Get List - return all games that you add to your list one by one.\n'
                                                   'Add Game - add new game to the your list, '
                                                   'you can send an ID of game or a link to the Steam.\n'
                                                   'Delete Game - delete game from your list, can get only IDs.')
        # if command is not exist
        case _:
            bot.send_message(message.from_user.id, "Hello! You want to check game price"
                                                   " in Steam? Tap the button below.", reply_markup=keyboard_markup)


# scheduled check of game prices
def main_check():
    update_data()
    connection_to_db = sqlite3.connect('database.db')
    cursor_db = connection_to_db.cursor()
    cursor_db.execute('SELECT DISTINCT(tlg_id) from watching_list')
    ids = cursor_db.fetchall()

    for one_id in ids:
        try:
            cursor_db.execute('select id from watching_list WHERE tlg_id = ?', (one_id[0],))
            x = cursor_db.fetchall()
            sale_true = False
            for row in x:
                one_game = get_data(row[0])

                if one_game[2] > one_game[3]:

                    # ['1054490', 'Wingspan', 39900, 39900]
                    bot.send_message(one_id[0],
                                     f"GAME ON SALE!\n"
                                     "\n"
                                     f"https://store.steampowered.com/app/{one_game[0]}\n"
                                     "\n"
                                     f"ID: {one_game[0]}\n"
                                     f"Name: {one_game[1]}\n\n"
                                     f"Full Price: {one_game[2]} UAH\n\n"
                                     f"Price Now: {one_game[3]} UAH\n"
                                     "\n"
                                     f"Sale is {one_game[4]}%\n")
                    sale_true = True

                else:
                    pass

            # if not sale_true:
            #     bot.send_message(one_id[0], f"Unfortunately, today is no sale on games from your wishlist.")
        except BaseException:
            print(f"User {one_id[0]} block the bot")
    connection_to_db.close()


# infinity bot work
def bot_poll():
    try:
        bot.polling(none_stop=True)
    except Exception:
        time.sleep(15)


if __name__ == "__main__":
    # run poll on different tread to not block time check
    Thread(target=bot_poll).start()

    # check time
    while True:
        print(f'Check {datetime.now()}')
        # for tests
        # if datetime.now().strftime("%H") == "13":
        #     main_check()
        # time.sleep(60)

        if datetime.now().strftime("%H") == "21":
            main_check()
        time.sleep(3600)
