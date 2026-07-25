import os
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from datetime import timedelta
from functools import wraps

app = Flask(__name__, template_folder='.', static_folder='.')
app.secret_key = '7f8a9e01b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9'
app.permanent_session_lifetime = timedelta(days=30)

client = MongoClient("mongodb+srv://seyzalel_db_user:q4dKhbwPQwBcmEFZ@dmtopmonitor.dnbpdnd.mongodb.net/?retryWrites=true&w=majority&appName=DMTopMonitor")
db = client.dmtopmonitor
users_db = db.users

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
        'password': hashed_password
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

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
