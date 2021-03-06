from flask import Flask, render_template, request, url_for, Response, session
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from flask_mail import Mail, Message
from werkzeug.utils import redirect
from db import DatabaseManagement
from passlib.hash import sha256_crypt
from user import User
import os
import passwordValidator
import configparser
import random
import string

config = configparser.RawConfigParser()
configFilePath = './config.ini'
config.read(configFilePath)

app = Flask(__name__,
            static_url_path='',
            static_folder='static',
            template_folder='templates')

db_object = DatabaseManagement()
login_manager = LoginManager()
login_manager.init_app(app)

DEBUG_MODE = os.environ.get('DEBUG_MODE', False)
HASH_SALT = os.environ.get('HASH_SALT')
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
PASSWORDS_HISTORY = int(config.get('main', 'passwords_history'))
LOGIN_RETRY_THRESHOLD = int(config.get('main', 'login_retries'))
REDIRECT_SCHEME = 'http' if DEBUG_MODE else 'https'

app.config['MAIL_USERNAME'] = MAIL_USERNAME
app.config['MAIL_PASSWORD'] = MAIL_PASSWORD
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
mail_object = Mail(app)


@login_manager.user_loader
def load_user(uid):
    result = db_object.get_user_by_uid(uid)
    email = result[0][0]
    display_name = result[0][1]
    is_admin = result[0][2]
    is_active = True
    session['display_name'] = display_name
    session['is_active'] = is_active
    session['is_admin'] = is_admin
    return User(uid, email, display_name, is_active, is_admin)


@app.route('/', methods=['GET'])
def homepage():
    return render_template("index.html", customers=db_object.get_customers())


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:  # Prevent registration for logged in users
        return Response(status=403)

    if request.method == 'GET':
        return render_template("register.html", status_message=[])

    else:  # POST Method
        email = request.form.get('email')
        display_name = request.form.get('display_name')
        password = request.form.get('password')

        if email == "" or display_name == "" or password == "":
            return render_template('register.html', status_message=["Make sure to fill all fields."])

        validate_password_resp = passwordValidator.validate_password(password)
        if not validate_password_resp['status']:
            return render_template('register.html', status_message=validate_password_resp['info'])

        password_hashed = sha256_crypt.encrypt(password + HASH_SALT)
        previous_passwords_list = '{"%s"}' % password_hashed
        result = db_object.insert_user(email, display_name, password_hashed, previous_passwords_list)

        if result == 0:
            return render_template('register.html', status_message=["User {} registered successfully.".format(email)])
        else:
            return render_template('register.html', status_message=["Failed to register user {}.".format(email),
                                                                    "Error: {}".format(result)])


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:  # Prevent logging in for logged in users, need to logout first
        return Response(status=403)

    if request.method == 'GET':
        return render_template('login.html')

    else:  # POST Method
        email = request.form.get('email')
        password = request.form.get('password')

        if email == "" or password == "":
            return render_template('login.html', status_message=["Make sure to fill all fields."])

        try:
            result = db_object.get_user_by_email(email)

            if not result:
                return render_template('login.html',
                                       status_message=["User is not registered in the system."])

            user_id = result[0][0]
            stored_password = result[0][1]
            is_locked = result[0][2]
            reset_password_needed = result[0][3]
            is_admin = result[0][5]
            display_name = result[0][6]

            if is_locked:
                return render_template('login.html', status_message=["Your user is locked,"
                                                                     " please contact administrator."])

            if sha256_crypt.verify(password + HASH_SALT, stored_password):
                return successful_login(user_id, email, password, reset_password_needed, is_admin, display_name)
            else:
                return unsuccessful_login(email)

        except Exception as e:
            return render_template('login.html', status_message=["Login failed for user {}.".format(email),
                                                                 "error: {}".format(result),
                                                                 "{}".format(e)])


@app.route('/logout')
def logout():
    logout_user()
    session.clear()
    return render_template('logout.html')


@app.route('/add_customer', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'GET':
        return render_template("add_customer.html", status_message=[])

    else:  # POST Method
        name = request.form.get('customer_name')
        address = request.form.get('address')
        phone = request.form.get('phone')

        if name == "" or address == "" or phone == "":
            return render_template('add_customer.html', status_message=["Make sure to fill all fields."])

        result = db_object.insert_customer(name, address, phone)
        if result == 0:
            return render_template('add_customer.html', status_message=["Customer {} added successfully.".format(name)])
        else:
            return render_template('add_customer.html', status_message=["Failed to add customer {}.".format(name),
                                                                        "error: {}".format(result)])


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:  # Prevent forgot password for logged in users, need to logout first
        return Response(status=403)

    if request.method == 'GET':
        return render_template("forgot_password.html", status_message="")

    else:  # POST Method
        email = request.form.get('email')
        is_registered = db_object.get_user_by_email(email)

        if not is_registered:
            return render_template("forgot_password.html", status_message="User is not registered in the system.")

        random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=24))
        msg = Message('Reset password request', sender=MAIL_USERNAME, recipients=[email])
        msg.html = render_template('forgot_password_email.html', random_password=random_password)
        mail_object.send(msg)

        password_hashed = sha256_crypt.encrypt(random_password + HASH_SALT)
        result = db_object.update_user_forgot_password(email, password_hashed, 1)
        if result == 0:
            return render_template("forgot_password.html", status_message="Check your inbox for temporary password.")
        else:
            return render_template("forgot_password.html", status_message="Failed generating temporary password, "
                                                                          "please contact administrator.")


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password(status_message=""):
    if request.method == 'GET':
        return render_template('change_password.html', status_message=status_message)

    else:  # POST Method
        email = request.form.get('email')
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        repeat_new_password = request.form.get('repeat_new_password')

        if old_password == "" or new_password == "" or repeat_new_password == "":
            return render_template('change_password.html', status_message=["Make sure to fill all fields."])
        elif new_password != repeat_new_password:
            return render_template('change_password.html',
                                   status_message=["Repeat password differs from new password, please try again."])
        else:
            validate_password_resp = passwordValidator.validate_password(new_password)
            if not validate_password_resp['status']:
                return render_template('change_password.html', status_message=validate_password_resp['info'])

        try:
            result = db_object.get_user_by_email(email)

            if not result:
                return render_template("change_password.html", status_message=["User is not registered in the system."])

            stored_password = result[0][1]
            is_locked = result[0][2]
            previous_passwords_list = result[0][4]
        except Exception as e:
            return render_template('login.html', status_message=["Login to change password for user {}.".format(email),
                                                                 "error: {}".format(result),
                                                                 "{}".format(e)])

        if is_locked:
            return render_template('change_password.html',
                                   status_message=["Your user is locked, please contact administrator."])

        if not sha256_crypt.verify(old_password + HASH_SALT, stored_password):
            return render_template('change_password.html',
                                   status_message=["Cannot change password since current password is incorrect.",
                                                   "Please try again"])

        for prev_pass in previous_passwords_list:  # Iterating over previous passwords to prevent repeat
            if sha256_crypt.verify(new_password + HASH_SALT, prev_pass):
                return render_template('change_password.html', status_message=["Do not repeat one of your {} previous "
                                                                               "passwords.".format(PASSWORDS_HISTORY)])

        password_hashed = sha256_crypt.encrypt(new_password + HASH_SALT)
        previous_passwords_list = update_previous_passwords(previous_passwords_list, password_hashed)

        result = db_object.update_user(email, password_hashed, previous_passwords_list, 0)
        if result == 0:
            return render_template('change_password.html', status_message=["Password changed successfully."])
        else:
            return render_template('change_password.html', status_message=["Failed to change password.",
                                                                           "error: {}".format(result)])


@app.route('/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if not session['is_admin']:
        return Response(status=403)

    if request.method == 'GET':
        return render_template('manage_users.html', users=db_object.get_users())

    else:  # POST Method
        if 'email_unlock' in request.form:  # Means this is unlock request
            action = 'unlock'
            email = request.form.get('email_unlock')
            result = db_object.unlock_user(email)
        else:  # Means this is delete request
            action = 'delete'
            email = request.form.get('email_delete')
            result = db_object.delete_user(email)

        if result == 0:
            return render_template('manage_users.html', users=db_object.get_users(),
                                   status_message=["User {} {} successful".format(email, action)])
        else:
            return render_template('manage_users.html', users=db_object.get_users(),
                                   status_message=["Failed to {} user {}".format(email, action),
                                                   "error: {}".format(result)])


def successful_login(user_id, email, password, reset_password_needed, is_admin, display_name):
    login_user(User(user_id, email, display_name, password, is_admin))
    db_object.update_login_attempts(0, email)

    if not reset_password_needed:
        return redirect(url_for('homepage', _external=True, _scheme=REDIRECT_SCHEME))
    else:
        return redirect(url_for('change_password', _external=True, _scheme=REDIRECT_SCHEME))


def unsuccessful_login(email):
    login_retries = db_object.get_login_attempts(email)[0][0]

    if login_retries == LOGIN_RETRY_THRESHOLD - 1:  # User reached max login attempts
        result = db_object.lock_user(email)
        if result == 0:
            return render_template('login.html', status_message=["Your user is locked, please contact administrator."])
        else:
            return render_template('login.html', status_message=["Failed to lock user, please contact administrator."])

    else:  # Increasing login retries amount
        login_retries += 1
        result = db_object.update_login_attempts(login_retries, email)
        if result == 0:
            return render_template('login.html',
                                   status_message=["Login failed, {} retries left.".format
                                                   (LOGIN_RETRY_THRESHOLD - login_retries)])
        else:
            return render_template('login.html',
                                   status_message=["Failed to increase login retries, please contact administrator."])


def update_previous_passwords(previous_passwords_list, new_password):
    previous_passwords_list.insert(0, new_password)
    if len(previous_passwords_list) > PASSWORDS_HISTORY:  # Rotate previous passwords list if threshold reached
        previous_passwords_list.pop()

    temp_previous_passwords_str = '","'.join(previous_passwords_list)
    previous_passwords_str = '{"%s"}' % temp_previous_passwords_str

    return previous_passwords_str


if __name__ == "__main__":
    app.secret_key = os.urandom(12)
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=DEBUG_MODE)
