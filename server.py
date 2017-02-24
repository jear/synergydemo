# -*- coding: utf-8 -*-


import os
import sys
import time
from flask import Flask
from flask import jsonify
from flask import request
from flask import redirect
from flask import send_from_directory
from flask_sockets import Sockets
import jinja2
from api_exception import InvalidUsage
from hpOneView.oneview_client import OneViewClient
from hpOneView.exceptions import HPOneViewException
import json


class Reservation(object):
    def __init__(self):
        self.file = 'reservation.json'
        self.data = None

        # read json file
        try:
            with open(self.file, 'r') as json_data:
                self.data = json.load(json_data)
                json_data.close()
        except IOError:
            self.data = {}
            self.save()

    def save(self):
        with open(self.file, 'w') as json_data:
            json_data.write(json.dumps(self.data))
            json_data.close()

    def reserve(self, uuid, owner):
        self.data.update({uuid: owner})
        self.save()

    def get(self, uuid):
        try:
            return self.data[uuid]
        except KeyError:
            return ""

app = Flask(__name__)
sockets = Sockets(app)

try:
    login = os.environ["OVLOGIN"]
    password = os.environ["OVPASSWD"]
except KeyError:
    print("Please set OVLOGIN and OVPASSWD environment variable")
    sys.exit(1)


config = {
    "ip": "10.3.87.10",
    "credentials": {
        "userName": login,
        "password": password
    }
}


oneview_client = OneViewClient(config)

# Get hardware
server_hardware_all = oneview_client.server_hardware.get_all()

# Get profiles
all_profiles = oneview_client.server_profiles.get_all()

# Initialize reservation
resa = Reservation()


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


@sockets.route('/reserve/<uuid>')
def reserve(ws, uuid):
    owner = ws.receive()
    resa.reserve(uuid, owner)
    ws.send(uuid)


@sockets.route('/bla')
def bla_socket(ws):
    while not ws.closed:
        message = ws.receive()
        ws.send(message + 'blabla')
        for i in range(5):
            time.sleep(1)
            ws.send(message + 'blabla')


@app.route('/')
@app.route('/available')
def available():
    html = render_template("available.html", server_hardware_all)
    return html


@app.route('/ready2deploy')
def ready2deploy():
    # Craft required data
    data2print = []
    for server in server_hardware_all:
        if server['serverProfileUri'] is not None:
            profile = oneview_client.server_profiles.get(
                    server['serverProfileUri'])
            if 'iPXE' in profile["name"]:
                macaddress = profile['connections'][0]['mac'].lower()
                macaddress = macaddress.replace(':', '')
                data2print.append({
                    'shortModel': server['shortModel'],
                    'name': server['name'],
                    'uuid': server['uuid'],
                    'macaddress': macaddress,
                    'powerState': server['powerState'],
                    'owner': resa.get(server['uuid'])
                    })
    html = render_template("ready2deploy.html", data2print)
    return html


@app.route('/deployed')
def deployed():
    html = render_template("deployed.html", server_hardware_all)
    return html


@app.route('/config/<ip>')
def configure(ip):
    # Not really great code...
    global config
    global oneview_client
    global server_hardware_all
    config["ip"] = ip
    oneview_client = OneViewClient(config)
    server_hardware_all = oneview_client.server_hardware.get_all()
    return redirect("available")


@app.route('/css/<path>')
def send_css(path):
    return send_from_directory('templates/css', path)


@app.route('/img/<path>')
def send_img(path):
    return send_from_directory('templates/img', path)


@app.route('/boot')
def boot():
    script = render_template("boot.template")
    return script


@app.route('/deploy/complete', methods=["POST"])
def deploy_complete():
    # Write a trace file
    try:
        macaddress = request.json['macaddress']
    except KeyError:
        raise InvalidUsage(
                'Invalid key provided should be macaddress', status_code=400)

    filename = "flags/" + macaddress
    with open(filename, 'w') as tracefile:
        tracefile.close()
        data = {"status": "ok"}
        resp = jsonify(data)
        resp.status_code = 200
        return resp


def render_template(template, values=None):
    # Initialize Template system (jinja2)
    templates_path = 'templates'
    jinja2_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_path))
    try:
        template = jinja2_env.get_template(template)
    except jinja2.exceptions.TemplateNotFound as e:
        print('Template "{}" not found in {}.'
              .format(e.message, jinja2_env.loader.searchpath[0]))

    if values is None:
        data = template.render()
    else:
        data = template.render(r=values)

    return data


if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 5000), app, handler_class=WebSocketHandler)
    server.serve_forever()
