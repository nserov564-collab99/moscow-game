import eventlet
eventlet.monkey_patch(all=True)

import os
from flask import Flask, request
from flask_socketio import SocketIO, emit
import google.generativeai as genai
import random
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-moscow-key!'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

game_state = {
    "players": {},
    "turn_index": 0,
    "player_order": [],
    "board_size": 40
}

INITIAL_STATS = {"gold": 50, "army": 50, "influence": 50, "lands": 10}

@app.route('/')
def index():
    return "Сервер Монополии работает!"

@socketio.on('join_game')
def handle_join(data):
    team_name = data['team_name']
    player_id = request.sid
    
    if player_id not in game_state["players"]:
        game_state["players"][player_id] = {
            "name": team_name,
            "position": 0,
            "stats": INITIAL_STATS.copy(),
            "color": f"#{random.randint(0, 0xFFFFFF):06x}"
        }
        if player_id not in game_state["player_order"]:
            game_state["player_order"].append(player_id)
            
    emit('update_state', game_state, broadcast=True)

@socketio.on('roll_dice')
def handle_roll():
    player_id = request.sid
    if len(game_state["player_order"]) == 0 or game_state["player_order"][game_state["turn_index"]] != player_id:
        return

    dice_result = random.randint(1, 6)
    old_pos = game_state["players"][player_id]["position"]
    new_pos = (old_pos + dice_result) % game_state["board_size"]
    game_state["players"][player_id]["position"] = new_pos
    
    emit('update_state', game_state, broadcast=True)
    generate_event(player_id, new_pos)

def generate_event(player_id, position):
    cell_type = "вопрос"
    if position % 5 == 0 and position != 0: 
        cell_type = "кризис"
    elif position % 7 == 0 and position != 0: 
        cell_type = "шанс"
    
    # Пулл качественных резервных вариантов на случай задержки ИИ
    fallbacks = [
        {"type": "вопрос", "text": f"Клетка №{position}: Кто был первым уделом Московского княжества?", "options": ["Даниил Александрович", "Иван Калита", "Юрий Долгорукий", "Дмитрий Донской"], "correct_index": 0, "explanation": "Даниил Александрович стал основоположником московской ветви династии Рюриковичей.", "delta": {"gold": 10, "influence": 5}},
        {"type": "кризис", "text": f"Клетка №{position}: Набег ордынского отряда на приграничные земли. Ваши действия?", "options": ["Откупиться казной (-15 золота)", "Собрать ополчение (-10 дружины)"], "correct_index": 0, "explanation": "Дипломатия и выкуп позволили сохранить людей, но опустошили казну.", "delta": {"gold": -15, "army": -5}},
        {"type": "шанс", "text": f"Клетка №{position}: Удачный торговый караган прибыл в Москву с ярмарки.", "options": ["Принять дары"], "correct_index": 0, "explanation": "Казна пополнилась за счет пошлин.", "delta": {"gold": 20, "lands": 1}}
    ]
    event_data = random.choice([f for f in fallbacks if f["type"] == cell_type] or fallbacks)

    if api_key:
        prompt = f"""
        Ты генератор событий для исторической игры про Возвышение Москвы (XIII-XVI века). 
        Клетка игрока: {position}, Тип события: {cell_type}.
        Придумай УНИКАЛЬНОЕ историческое событие, кризис или вопрос, не повторяющийся с другими.
        Укажи изменение ресурсов (delta), например: {{"gold": 15, "army": -5, "influence": 10, "lands": 1}}.
        Верни ответ СТРОГО в формате JSON без markdown:
        {{"type": "{cell_type}", "text": "Текст события", "options": ["Вариант 1", "Вариант 2"], "correct_index": 0, "explanation": "Историческая справка", "delta": {{"gold": 10, "army": 0, "influence": 5, "lands": 0}}}}
        """
        try:
            response = model.generate_content(prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            event_data = json.loads(clean_text)
        except Exception as e:
            print("Ошибка ИИ, используем резерв:", e)
            
    emit('trigger_event', {"event": json.dumps(event_data), "player_id": player_id}, broadcast=True)

@socketio.on('submit_answer')
def handle_answer(data):
    player_id = request.sid
    delta = data.get('delta', {})
    
    if player_id in game_state["players"]:
        player = game_state["players"][player_id]
        for stat, val in delta.items():
            if stat in player["stats"]:
                player["stats"][stat] = max(0, player["stats"][stat] + val)
                
    emit('update_state', game_state, broadcast=True)

@socketio.on('end_turn')
def handle_end_turn():
    game_state["turn_index"] = (game_state["turn_index"] + 1) % len(game_state["player_order"])
    emit('update_state', game_state, broadcast=True)
