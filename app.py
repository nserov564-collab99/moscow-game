import eventlet
eventlet.monkey_patch()

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
    if position % 5 == 0 and position != 0: cell_type = "кризис"
    elif position % 7 == 0 and position != 0: cell_type = "шанс"
        
    event_data = {
        "type": cell_type,
        "text": "В каком году Москва впервые упоминается в летописях?",
        "options": ["1147 год", "1237 год", "1380 год", "1480 год"],
        "correct_index": 0,
        "explanation": "Москва впервые упоминается в Ипатьевской летописи под 1147 годом."
    }

    if api_key:
        prompt = f"""
        Тема: Возвышение Москвы (XIII - XVI века). Тип: {cell_type}.
        Дай исторический вопрос, 4 варианта ответа (один правильный) и объяснение.
        Верни ответ СТРОГО в формате JSON без markdown:
        {{"type": "{cell_type}", "text": "Текст", "options": ["Вариант 1", "Вариант 2", "Вариант 3", "Вариант 4"], "correct_index": 0, "explanation": "Объяснение"}}
        """
        try:
            response = model.generate_content(prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            event_data = json.loads(clean_text)
        except Exception as e:
            print("Ошибка ИИ, используем резервный вопрос:", e)
            
    emit('trigger_event', {"event": json.dumps(event_data), "player_id": player_id}, broadcast=True)

@socketio.on('end_turn')
def handle_end_turn():
    game_state["turn_index"] = (game_state["turn_index"] + 1) % len(game_state["player_order"])
    emit('update_state', game_state, broadcast=True)
