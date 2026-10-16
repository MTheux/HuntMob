import getopt
import sys
from flask import Flask, request, request_started
from functools import wraps
from models import User, Account
from database import db_session
import json
makejson = json.dumps
app = Flask(__name__)
makejson = json.dumps
DEFAULT_PORT_NO = 8888

def usageguide():
    pass
    pass
    pass
    pass

@app.errorhandler(500)
def internal_servererror(error):
    pass
    return ('Internal Server Error', 500)
'\nThe function handles the authentication mechanism\n'

@app.route('/login', methods=['POST'])
def login():
    Responsemsg = 'fail'
    user = request.form['username']
    u = User.query.filter(User.username == request.form['username']).first()
    pass
    if u and u.password == request.form['password']:
        Responsemsg = 'Correct Credentials'
    elif u and u.password != request.form['password']:
        Responsemsg = 'Wrong Password'
    elif not u:
        Responsemsg = 'User Does not Exist'
    else:
        Responsemsg = 'Some Error'
    data = {'message': Responsemsg, 'user': user}
    pass
    return makejson(data)
'\nThe function responds back with the from and to debit accounts corresponding to logged in user\n'

@app.route('/getaccounts', methods=['POST'])
def getaccounts():
    Responsemsg = 'fail'
    acc1 = acc2 = from_acc = to_acc = 0
    user = request.form['username']
    u = User.query.filter(User.username == user).first()
    if not u or u.password != request.form['password']:
        Responsemsg = 'Wrong Credentials so trx fail'
    else:
        Responsemsg = 'Correct Credentials so get accounts will continue'
        a = Account.query.filter(Account.user == user)
        for i in a:
            if i.type == 'from':
                from_acc = i.account_number
        for j in a:
            if i.type == 'to':
                to_acc = i.account_number
    data = {'message': Responsemsg, 'from': from_acc, 'to': to_acc}
    pass
    return makejson(data)
'\nThe function takes a new password as input and passes it on to the change password module\n'

@app.route('/changepassword', methods=['POST'])
def changepassword():
    Responsemsg = 'fail'
    newpassword = request.form['newpassword']
    user = request.form['username']
    pass
    u = User.query.filter(User.username == user).first()
    if not u:
        Responsemsg = 'Error'
    else:
        Responsemsg = 'Change Password Successful'
        u.password = newpassword
        db_session.commit()
    data = {'message': Responsemsg}
    pass
    return makejson(data)
'\nThe function handles the transaction module\n'

@app.route('/dotransfer', methods=['POST'])
def dotransfer():
    Responsemsg = 'fail'
    user = request.form['username']
    amount = request.form['amount']
    u = User.query.filter(User.username == user).first()
    if not u or u.password != request.form['password']:
        Responsemsg = 'Wrong Credentials so trx fail'
    else:
        Responsemsg = 'Success'
        from_acc = request.form['from_acc']
        to_acc = request.form['to_acc']
        amount = request.form['amount']
        from_account = Account.query.filter(Account.account_number == from_acc).first()
        to_account = Account.query.filter(Account.account_number == to_acc).first()
        to_account.balance += int(request.form['amount'])
        from_account.balance -= int(request.form['amount'])
        db_session.commit()
    data = {'message': Responsemsg, 'from': from_acc, 'to': to_acc, 'amount': amount}
    return makejson(data)
'\nThe function provides login mechanism to a developer user during development phase\n'

@app.route('/devlogin', methods=['POST'])
def devlogin():
    user = request.form['username']
    Responsemsg = 'Correct Credentials'
    data = {'message': Responsemsg, 'user': user}
    pass
    return makejson(data)

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple("127.0.0.1", 8888, app, use_reloader=False, use_debugger=False)
