import os
import requests
import qrcode
import io
import base64
import instaloader
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, join_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from datetime import datetime, timedelta
from functools import wraps
from bson.objectid import ObjectId

app = Flask(__name__, template_folder='.', static_folder='.')
app.secret_key = '7f8a9e01b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9'
app.permanent_session_lifetime = timedelta(days=30)

# Configuração SocketIO para tempo real (WebSockets)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuração do Banco de Dados
client = MongoClient("mongodb+srv://seyzalel_db_user:q4dKhbwPQwBcmEFZ@dmtopmonitor.dnbpdnd.mongodb.net/?retryWrites=true&w=majority&appName=DMTopMonitor")
db = client.dmtopmonitor
users_db = db.users
engineering_db = db.engineering # Nova coleção para as configurações customizadas (Engineering)

users_db.update_many(
    {"plan": {"$exists": False}},
    {"$set": {"plan": "standard"}}
)

# Constantes de Pagamento
PLUMIFY_API_TOKEN = "hXIVPQ9kPjSQERpJ7ljKkWT0f6qOet4tUgr7kP4LTer5b0SsRq7VaUalBdGg"
PLUMIFY_BASE_URL = "https://api.plumify.com.br/api/public/v1/transactions"

# -------------------------------------------------------------------
# CONFIGURAÇÃO DO INSTALOADER (Otimizado para velocidade e sem downloads)
# -------------------------------------------------------------------
insta = instaloader.Instaloader(
    download_pictures=False,
    download_video_thumbnails=False,
    download_videos=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False
)

# Cache em memória para buscas instantâneas e evitar bloqueios do Instagram (Rate Limit)
profile_cache = {}
# -------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function

# -------------------------------------------------------------------
# EVENTOS SOCKET.IO (EM TEMPO REAL)
# -------------------------------------------------------------------
@socketio.on('join')
def on_join(data):
    """Quando o frontend conecta, ele entra na sala com seu user_id exclusivo"""
    user_id = data.get('user_id')
    if user_id:
        join_room(user_id)

@app.route('/')
def index():
    return render_template('landing.html')

@app.route('/auth', methods=['GET'])
def auth():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('auth.html')

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not username or not email or not password:
        return jsonify({'success': False, 'message': 'Preencha todos os campos.'}), 400
        
    if users_db.find_one({'$or': [{'username': username}, {'email': email}]}):
        return jsonify({'success': False, 'message': 'Usuário ou e-mail já em uso.'}), 409
        
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    
    user_id = users_db.insert_one({
        'username': username,
        'email': email,
        'password': hashed_password,
        'plan': 'standard'
    }).inserted_id
    
    session.permanent = True
    session['user_id'] = str(user_id)
    session['username'] = username
    
    return jsonify({'success': True, 'redirect': url_for('dashboard')}), 201

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    identifier = data.get('identifier')
    password = data.get('password')
    
    if not identifier or not password:
        return jsonify({'success': False, 'message': 'Preencha todos os campos.'}), 400
        
    user = users_db.find_one({'$or': [{'username': identifier}, {'email': identifier}]})
    
    if user and check_password_hash(user['password'], password):
        session.permanent = True
        session['user_id'] = str(user['_id'])
        session['username'] = user['username']
        return jsonify({'success': True, 'redirect': url_for('dashboard')}), 200
        
    return jsonify({'success': False, 'message': 'Credenciais inválidas.'}), 401

@app.route('/dashboard')
@login_required
def dashboard():
    user = users_db.find_one({"_id": ObjectId(session['user_id'])})
    plan = user.get('plan', 'standard') if user else 'standard'
    username = user.get('username', session.get('username', 'Usuário')) if user else 'Usuário'
    return render_template('dashboard.html', username=username, plan=plan, user_id=str(session['user_id']))

@app.route('/plans')
@login_required
def plans():
    return render_template('plans.html')

@app.route('/checkout')
@login_required
def checkout():
    return render_template('pixCheckout.html')

@app.route('/api/generate_pix', methods=['POST'])
@login_required
def generate_pix():
    user = users_db.find_one({"_id": ObjectId(session['user_id'])})
    
    url = f"{PLUMIFY_BASE_URL}?api_token={PLUMIFY_API_TOKEN}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    data = {
        'amount': 5500,
        'offer_hash': 'taebbjxtkr',
        'payment_method': 'pix',
        'customer': {
            'name': user.get('username', 'João Silva'),
            'email': user.get('email', 'joao@email.com'),
            'phone_number': '21999999999',
            'document': '09115751031'
        },
        'cart': [
            {
                'product_hash': '56aujwvfng',
                'title': 'Plano Unlimited',
                'price': 5500,
                'quantity': 1,
                'operation_type': 1,
                'tangible': False
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        
        pix_string = result.get('pix', {}).get('pix_qr_code', '')
        tx_hash = result.get('hash', '')
        
        if not pix_string:
            return jsonify({'success': False, 'message': 'Erro ao gerar PIX.'}), 500
            
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(pix_string)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        return jsonify({
            'success': True,
            'qr_code_base64': qr_base64,
            'pix_string': pix_string,
            'transaction_hash': tx_hash
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/check_status/<tx_hash>', methods=['GET'])
@login_required
def check_status(tx_hash):
    url = f"{PLUMIFY_BASE_URL}/{tx_hash}?api_token={PLUMIFY_API_TOKEN}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        status = result.get('payment_status')
        
        if status == 'paid':
            users_db.update_one(
                {"_id": ObjectId(session['user_id'])},
                {"$set": {"plan": "unlimited"}}
            )
            return jsonify({'success': True, 'status': 'paid'})
            
        return jsonify({'success': True, 'status': status})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/get_instagram_profile/<username>', methods=['GET'])
@login_required
def get_instagram_profile(username):
    user = users_db.find_one({"_id": ObjectId(session['user_id'])})
    
    if not user or user.get('plan') != 'unlimited':
        return jsonify({'success': False, 'message': 'Acesso negado. Plano incompatível.'}), 403

    clean_username = username.replace('@', '').strip().lower()
    
    if not clean_username:
        return jsonify({'success': False, 'message': 'Usuário inválido.'}), 400

    if clean_username in profile_cache:
        return jsonify({'success': True, 'data': profile_cache[clean_username]})

    try:
        profile = instaloader.Profile.from_username(insta.context, clean_username)
        
        profile_data = {
            'username': profile.username,
            'full_name': profile.full_name,
            'followers': profile.followers,
            'profile_pic_url': profile.profile_pic_url
        }
        
        profile_cache[clean_username] = profile_data
        
        return jsonify({'success': True, 'data': profile_data})
        
    except instaloader.exceptions.ProfileNotExistsException:
        return jsonify({'success': False, 'message': 'Perfil não encontrado.'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': 'Erro ao buscar dados do Instagram.'}), 500


# -------------------------------------------------------------------
# ROTAS ENGINEERING (MANIPULAÇÃO DA DM)
# -------------------------------------------------------------------
@app.route('/engineering')
@login_required
def engineering():
    user = users_db.find_one({"_id": ObjectId(session['user_id'])})
    plan = user.get('plan', 'standard') if user else 'standard'
    username = user.get('username', session.get('username', 'Usuário')) if user else 'Usuário'
    
    # Redireciona usuários standard se quiser bloquear a configuração, 
    # mas mantido aberto caso você queira permitir o setup antes de pagar.
    if plan != 'unlimited':
        pass 
        
    return render_template('engi.html', username=username, plan=plan)

@app.route('/api/engineering/config', methods=['GET', 'POST'])
@login_required
def engineering_config():
    user_id = str(session['user_id'])
    
    if request.method == 'GET':
        config = engineering_db.find_one({"user_id": user_id})
        if not config:
            return jsonify({'success': True, 'data': []})
            
        config['_id'] = str(config['_id'])
        return jsonify({'success': True, 'data': config.get('dms', [])})
        
    if request.method == 'POST':
        data = request.get_json()
        dms = data.get('dms', [])
        
        # Garante que os dados sejam salvos ordenados corretamente no BD
        engineering_db.update_one(
            {"user_id": user_id},
            {"$set": {"dms": dms, "updated_at": datetime.utcnow()}},
            upsert=True
        )
        
        # Dispara evento em TEMPO REAL para o dashboard deste usuário específico
        socketio.emit('engineering_update', {'dms': dms}, room=user_id)
        
        return jsonify({'success': True, 'message': 'Configurações sincronizadas com sucesso!'})


@app.route('/api/get_ranking', methods=['POST'])
@login_required
def get_ranking():
    user = users_db.find_one({"_id": ObjectId(session['user_id'])})
    
    if not user or user.get('plan') != 'unlimited':
        return jsonify({'success': False, 'message': 'Acesso negado. Plano incompatível.'}), 403
        
    data = request.get_json()
    count = data.get('count', 10)
    user_id = str(session['user_id'])
    
    try:
        count_int = int(count)
    except ValueError:
        return jsonify({'success': False, 'message': 'Quantidade inválida.'}), 400

    # Busca a configuração customizada do usuário no Engineering
    eng_config = engineering_db.find_one({"user_id": user_id})
    
    if eng_config and eng_config.get('dms') and len(eng_config['dms']) > 0:
        # Puxa DMs criadas em engineering.
        custom_dms = eng_config['dms']
        selected_dms = custom_dms[:count_int]
        return jsonify({'success': True, 'data': selected_dms, 'source': 'engineering'})
    else:
        # Fallback (caso o usuário ainda não tenha configurado nada no Engineering)
        dummy_dm_list = [
            {"username": "@sofia.martins", "preview": "Visualizado há 5m", "avatarBg": "#E57399"},
            {"username": "@lucas_oliveira", "preview": "Mensagem enviada...", "avatarBg": "#64B5F6"},
            {"username": "@ana.beatriz", "preview": "Áudio (0:15)", "avatarBg": "#81C784"},
            {"username": "@pedro_henrique22", "preview": "Você viu a nova atualização?", "avatarBg": "#FFB74D"},
            {"username": "@marina_costa", "preview": "Quando nos encontramos?", "avatarBg": "#BA68C8"},
            {"username": "@gabriel.santos", "preview": "Reunião amanhã às 10h", "avatarBg": "#4DB6AC"},
            {"username": "@julia_fernandes", "preview": "Amei a foto nova!", "avatarBg": "#E0A0A0"},
            {"username": "@rafael.almeida", "preview": "Preciso falar com você urgente", "avatarBg": "#90A4AE"},
            {"username": "@camila_rodrigues", "preview": "Obrigada pelo apoio!", "avatarBg": "#F48FB1"},
            {"username": "@thiago_silva", "preview": "Bora treinar hoje?", "avatarBg": "#A1887F"},
            {"username": "@isabela_lima", "preview": "Saudades!", "avatarBg": "#CE93D8"},
            {"username": "@bruno_carvalho", "preview": "Manda o áudio que eu explico", "avatarBg": "#FF8A65"},
            {"username": "@larissa_souza", "preview": "Confirma presença no evento?", "avatarBg": "#4FC3F7"},
            {"username": "@felipe_azevedo", "preview": "O contrato está pronto", "avatarBg": "#AED581"},
            {"username": "@amanda_rocha", "preview": "Vamos no cinema sábado?", "avatarBg": "#FFD54F"},
            {"username": "@ricardo_melo", "preview": "Dá uma olhada nesse link", "avatarBg": "#7986CB"},
            {"username": "@patricia_nunes", "preview": "Parabéns pelo seu dia!", "avatarBg": "#E57373"},
            {"username": "@diego_oliver", "preview": "Tô te esperando", "avatarBg": "#4DD0E1"},
            {"username": "@vanessa_costa", "preview": "Adorei a receita", "avatarBg": "#F06292"},
            {"username": "@marcos_paulo", "preview": "Me liga quando der", "avatarBg": "#81D4FA"},
            {"username": "@beatriz_carvalho", "preview": "Você está bem?", "avatarBg": "#FFF176"},
            {"username": "@leandro_dias", "preview": "Amanhã tem reunião", "avatarBg": "#B0BEC5"},
            {"username": "@tamires_gomes", "preview": "Olha o que eu achei", "avatarBg": "#FFAB91"},
            {"username": "@everton_ribeiro", "preview": "E aí, beleza?", "avatarBg": "#69F0AE"},
            {"username": "@priscila_mendes", "preview": "Saudades de você", "avatarBg": "#EA80FC"},
            {"username": "@henrique_barbosa", "preview": "Manda o endereço", "avatarBg": "#8C9EFF"},
            {"username": "@carolina_freitas", "preview": "Que foto linda!", "avatarBg": "#FF80AB"},
            {"username": "@vinicius_campos", "preview": "Vamos jogar online?", "avatarBg": "#B388FF"},
            {"username": "@alice_nascimento", "preview": "Te mandei um e-mail", "avatarBg": "#82B1FF"},
            {"username": "@roberto_teixeira", "preview": "Fechou o negócio?", "avatarBg": "#FF9E80"}
        ]
        selected_dms = dummy_dm_list[:count_int]
        return jsonify({'success': True, 'data': selected_dms, 'source': 'fallback'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

if __name__ == '__main__':
    # Inicialização pelo SocketIO para suportar WebSockets e Real-Time!
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
