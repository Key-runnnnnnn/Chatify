from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
import secrets
import datetime
import os
from functools import wraps
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-this')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'jwt-secret-key-change-this')
app.config['JWT_TOKEN_LOCATION'] = [os.getenv('JWT_TOKEN_LOCATION', 'cookies')]
app.config['JWT_ACCESS_COOKIE_PATH'] = os.getenv('JWT_ACCESS_COOKIE_PATH', '/')
app.config['JWT_COOKIE_CSRF_PROTECT'] = os.getenv('JWT_COOKIE_CSRF_PROTECT', 'False').lower() == 'true'
app.config['JWT_ACCESS_COOKIE_NAME'] = os.getenv('JWT_ACCESS_COOKIE_NAME', 'access_token_cookie')

# Initialize extensions
jwt = JWTManager(app)
socketio = SocketIO(app, cors_allowed_origins=os.getenv('CORS_ALLOWED_ORIGINS', "*"))

# MongoDB connection - Using MongoDB Atlas
try:
    # Connect to MongoDB Atlas
    atlas_uri = os.getenv('MONGODB_ATLAS_URI')
    if atlas_uri:
        client = MongoClient(atlas_uri, serverSelectionTimeoutMS=10000)
        client.admin.command('ping')  # Test connection
        print("✅ Connected to MongoDB Atlas")
    else:
        raise Exception("MongoDB Atlas URI not found in environment variables")
except Exception as atlas_error:
    print(f"❌ MongoDB Atlas connection failed: {atlas_error}")
    try:
        # Fallback to local MongoDB
        local_uri = os.getenv('MONGODB_LOCAL_URI', 'mongodb://localhost:27017/')
        client = MongoClient(local_uri, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')  # Test connection
        print("✅ Connected to local MongoDB")
    except Exception as local_error:
        print(f"❌ Local MongoDB not available: {local_error}")
        print("🔄 Running without database - using in-memory storage")
        client = None

db_name = os.getenv('DATABASE_NAME', 'chatify_db')
db = client[db_name] if client is not None else None
users_collection_name = os.getenv('USERS_COLLECTION', 'users')
rooms_collection_name = os.getenv('ROOMS_COLLECTION', 'rooms')
users_collection = db[users_collection_name] if db is not None else None
rooms_collection = db[rooms_collection_name] if db is not None else None

# Simple in-memory storage fallback
if client is None:
    users_storage = {}
    rooms_storage = {}
    print("⚠️ Using in-memory storage - data will be lost on restart")

# Helper functions for database operations


def find_user(query):
    print(f"🔍 find_user called with query: {query}")
    print(f"🔍 users_collection is: {users_collection}")
    if users_collection is not None:
        # Convert string _id to ObjectId if needed
        if '_id' in query and isinstance(query['_id'], str):
            try:
                query['_id'] = ObjectId(query['_id'])
                print(f"🔍 Converted string ID to ObjectId: {query['_id']}")
            except Exception as e:
                print(f"❌ Invalid ObjectId format: {e}")
                return None

        result = users_collection.find_one(query)
        print(f"🔍 MongoDB query result: {result}")
        return result
    else:
        print("🔍 Using in-memory storage fallback")
        # In-memory fallback
        for user_id, user in users_storage.items():
            if query.get('username') == user.get('username'):
                return user
            if query.get('email') == user.get('email'):
                return user
            if query.get('_id') and str(query['_id']) == user_id:
                return user
        return None


def create_user(user_data):
    print(f"🔍 create_user called with data: {user_data}")
    print(f"🔍 users_collection is: {users_collection}")
    if users_collection is not None:
        result = users_collection.insert_one(user_data)
        print(f"✅ User inserted with ID: {result.inserted_id}")
        return result
    else:
        print("🔍 Using in-memory storage fallback")
        # In-memory fallback
        import uuid
        user_id = str(uuid.uuid4())
        user_data['_id'] = user_id
        users_storage[user_id] = user_data

        class MockResult:
            def __init__(self, user_id):
                self.inserted_id = user_id
        return MockResult(user_id)


def update_user(user_id, update_data):
    if users_collection is not None:
        from bson.objectid import ObjectId
        return users_collection.update_one({'_id': ObjectId(user_id)}, {'$set': update_data})
    else:
        # In-memory fallback
        if user_id in users_storage:
            users_storage[user_id].update(update_data)
            return True
        return False


def find_rooms(query):
    if rooms_collection is not None:
        return list(rooms_collection.find(query))
    else:
        # In-memory fallback
        result = []
        for room in rooms_storage.values():
            if query.get('created_by') == room.get('created_by'):
                result.append(room)
        return result


def find_room(query):
    if rooms_collection is not None:
        return rooms_collection.find_one(query)
    else:
        # In-memory fallback
        for room in rooms_storage.values():
            if query.get('key') == room.get('key'):
                return room
        return None


def create_room_in_db(room_data):
    if rooms_collection is not None:
        return rooms_collection.insert_one(room_data)
    else:
        # In-memory fallback
        import uuid
        room_id = str(uuid.uuid4())
        room_data['_id'] = room_id
        rooms_storage[room_id] = room_data
        return True


def update_room(query, update_operation):
    if rooms_collection is not None:
        return rooms_collection.update_one(query, update_operation)
    else:
        # In-memory fallback
        for room in rooms_storage.values():
            if query.get('key') == room.get('key'):
                if '$push' in update_operation:
                    field, value = list(update_operation['$push'].items())[0]
                    if field not in room:
                        room[field] = []
                    if value not in room[field]:
                        room[field].append(value)
                elif '$pull' in update_operation:
                    field, value = list(update_operation['$pull'].items())[0]
                    if field in room and value in room[field]:
                        room[field].remove(value)
                return True
        return False


def delete_room(query):
    if rooms_collection is not None:
        return rooms_collection.delete_one(query)
    else:
        # In-memory fallback
        to_delete = None
        for room_id, room in rooms_storage.items():
            if query.get('key') == room.get('key'):
                to_delete = room_id
                break
        if to_delete:
            del rooms_storage[to_delete]
            return True
        return False

# Custom decorator for JWT with cookies


def jwt_required_cookie(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            print(f"🔍 JWT Cookie Check - Available cookies: {request.cookies}")
            verify_jwt_in_request(locations=['cookies'])
            print("✅ JWT verification successful")
            return f(*args, **kwargs)
        except Exception as e:
            print(f"❌ JWT verification failed: {e}")
            print(f"🔍 Redirecting to login")
            return redirect(url_for('login'))
    return decorated_function

# Routes


@app.route('/')
def index():
    try:
        verify_jwt_in_request(locations=['cookies'])
        return redirect(url_for('dashboard'))
    except:
        return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        print(f"🔍 Registration attempt - Username: {username}, Email: {email}")

        # Check if user already exists
        existing_user_by_username = find_user({'username': username})
        existing_user_by_email = find_user({'email': email})

        print(f"🔍 Existing user by username: {existing_user_by_username}")
        print(f"🔍 Existing user by email: {existing_user_by_email}")

        if existing_user_by_username or existing_user_by_email:
            print("❌ User already exists")
            return render_template('register.html', error='Username or email already exists')

        # Create new user
        hashed_password = generate_password_hash(password)
        user_data = {
            'username': username,
            'email': email,
            'password': hashed_password,
            'created_at': datetime.datetime.utcnow()
        }

        print(f"🔍 Creating user with data: {user_data}")

        try:
            result = create_user(user_data)
            print(f"✅ User created successfully: {result.inserted_id}")

            # Create JWT token
            access_token = create_access_token(
                identity=str(result.inserted_id))
            print(f"✅ JWT token created")

            # Create response and set cookie
            response = make_response(redirect(url_for('dashboard')))
            response.set_cookie('access_token_cookie',
                                access_token, httponly=True)
            print(f"✅ Redirecting to dashboard")

            return response
        except Exception as e:
            print(f"❌ Error creating user: {e}")
            return render_template('register.html', error=f'Error creating account: {str(e)}')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        print(f"🔍 Login attempt - Username: {username}")

        # Find user
        user = find_user({'username': username})
        print(f"🔍 Found user: {user}")

        if user and check_password_hash(user['password'], password):
            print("✅ Password verified successfully")
            # Create JWT token
            access_token = create_access_token(identity=str(user['_id']))
            print(f"✅ JWT token created for user ID: {user['_id']}")

            # Create response and set cookie
            response = make_response(redirect(url_for('dashboard')))
            response.set_cookie('access_token_cookie',
                                access_token, httponly=True)
            print("✅ Redirecting to dashboard")

            return response
        else:
            print("❌ Invalid credentials")
            return render_template('login.html', error='Invalid username or password')

    return render_template('login.html')


@app.route('/dashboard')
@jwt_required_cookie
def dashboard():
    user_id = get_jwt_identity()
    print(f"🔍 Dashboard - User ID from JWT: {user_id}")
    user = find_user({'_id': user_id})
    print(f"🔍 Dashboard - Found user: {user}")
    return render_template('dashboard.html', user=user)


@app.route('/update_profile', methods=['POST'])
@jwt_required_cookie
def update_profile():
    user_id = get_jwt_identity()
    field = request.form['field']
    value = request.form['value']

    update_data = {}

    if field == 'username':
        # Check if username already exists
        existing_user = find_user({'username': value})
        if existing_user and existing_user.get('_id') != user_id:
            return jsonify({'success': False, 'message': 'Username already exists'})
        update_data['username'] = value
    elif field == 'email':
        # Check if email already exists
        existing_user = find_user({'email': value})
        if existing_user and existing_user.get('_id') != user_id:
            return jsonify({'success': False, 'message': 'Email already exists'})
        update_data['email'] = value
    elif field == 'password':
        update_data['password'] = generate_password_hash(value)

    update_user(user_id, update_data)
    return jsonify({'success': True, 'message': 'Profile updated successfully'})


@app.route('/my_rooms')
@jwt_required_cookie
def my_rooms():
    user_id = get_jwt_identity()
    user = find_user({'_id': user_id})
    rooms = find_rooms({'created_by': user_id})
    return render_template('my_rooms.html', rooms=rooms, user=user)


@app.route('/create_room', methods=['POST'])
@jwt_required_cookie
def create_room():
    user_id = get_jwt_identity()
    room_name = request.form['room_name']

    # Generate unique room key
    room_key = secrets.token_urlsafe(8)

    room_data = {
        'name': room_name,
        'key': room_key,
        'created_by': user_id,
        'created_at': datetime.datetime.utcnow(),
        'members': [user_id]
    }

    create_room_in_db(room_data)
    return redirect(url_for('my_rooms'))


@app.route('/join_room', methods=['GET', 'POST'])
@jwt_required_cookie
def join_room_page():
    if request.method == 'POST':
        room_key = request.form['room_key']
        user_id = get_jwt_identity()

        room = find_room({'key': room_key})
        if room:
            # Add user to room if not already a member
            if user_id not in room.get('members', []):
                update_room({'key': room_key}, {'$push': {'members': user_id}})
            return redirect(url_for('chat_room', room_key=room_key))
        else:
            return render_template('join_room.html', error='Invalid room key')

    return render_template('join_room.html')


@app.route('/chat/<room_key>')
@jwt_required_cookie
def chat_room(room_key):
    user_id = get_jwt_identity()
    user = find_user({'_id': user_id})
    room = find_room({'key': room_key})

    if not room or user_id not in room.get('members', []):
        return redirect(url_for('join_room_page'))

    return render_template('chat.html', room=room, user=user)


@app.route('/leave_room/<room_key>')
@jwt_required_cookie
def leave_room_route(room_key):
    user_id = get_jwt_identity()
    update_room({'key': room_key}, {'$pull': {'members': user_id}})
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    response = make_response(redirect(url_for('login')))
    response.set_cookie('access_token_cookie', '', expires=0)
    return response


@app.route('/delete_room/<room_key>')
@jwt_required_cookie
def delete_room_route(room_key):
    user_id = get_jwt_identity()

    # Check if user is the room creator
    room = find_room({'key': room_key})
    if room and room.get('created_by') == user_id:
        # Delete the room
        delete_room({'key': room_key})

    return redirect(url_for('my_rooms'))

# Socket.IO events


@socketio.on('join')
def on_join(data):
    try:
        verify_jwt_in_request(locations=['cookies'])
        user_id = get_jwt_identity()
        user = find_user({'_id': user_id})
        room_key = data['room']

        join_room(room_key)
        emit('message', {
            'username': 'System',
            'message': f'{user["username"]} has joined the room',
            'timestamp': datetime.datetime.now().strftime('%H:%M')
        }, room=room_key)
    except:
        pass


@socketio.on('leave')
def on_leave(data):
    try:
        verify_jwt_in_request(locations=['cookies'])
        user_id = get_jwt_identity()
        user = find_user({'_id': user_id})
        room_key = data['room']

        leave_room(room_key)
        emit('message', {
            'username': 'System',
            'message': f'{user["username"]} has left the room',
            'timestamp': datetime.datetime.now().strftime('%H:%M')
        }, room=room_key)
    except:
        pass


@socketio.on('message')
def handle_message(data):
    try:
        verify_jwt_in_request(locations=['cookies'])
        user_id = get_jwt_identity()
        user = find_user({'_id': user_id})

        emit('message', {
            'username': user['username'],
            'message': data['message'],
            'timestamp': datetime.datetime.now().strftime('%H:%M'),
            'user_id': user_id
        }, room=data['room'])
    except:
        pass


@socketio.on('kick_user')
def handle_kick_user(data):
    try:
        verify_jwt_in_request(locations=['cookies'])
        admin_user_id = get_jwt_identity()
        room_key = data['room']
        target_user_id = data['target_user_id']

        # Check if current user is the room admin
        room = find_room({'key': room_key})
        if room and room.get('created_by') == admin_user_id:
            # Remove user from room members
            update_room({'key': room_key}, {
                        '$pull': {'members': target_user_id}})

            # Get target user info
            target_user = find_user({'_id': target_user_id})

            emit('user_kicked', {
                'kicked_user_id': target_user_id,
                'message': f'{target_user["username"]} has been kicked from the room'
            }, room=room_key)
    except:
        pass


if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    socketio.run(app, host=host, port=port, debug=debug)
