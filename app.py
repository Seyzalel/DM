import os
import requests
import qrcode
import io
import base64
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from datetime import timedelta
from functools import wraps
from bson.objectid import ObjectId

app = Flask(__name__, template_folder='.', static_folder='.')
app.secret_key = '7f8a9e01b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9'
app.permanent_session_lifetime = timedelta(days=30)

client = MongoClient("mongodb+srv://seyzalel_db_user:q4dKhbwPQwBcmEFZ@dmtopmonitor.dnbpdnd.mongodb.net/?retryWrites=true&w=majority&appName=DMTopMonitor")
db = client.dmtopmonitor
users_db = db.users

users_db.update_many(
    {"plan": {"$exists": False}},
    {"$set": {"plan": "standard"}}
)

PLUMIFY_API_TOKEN = "hXIVPQ9kPjSQERpJ7ljKkWT0f6qOet4tUgr7kP4LTer5b0SsRq7VaUalBdGg"
PLUMIFY_BASE_URL = "https://api.plumify.com.br/api/public/v1/transactions"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function

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
    username = session.get('username', 'Usuário')
    return render_template('dashboard.html', username=username)

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

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
