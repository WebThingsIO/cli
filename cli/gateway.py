'''Implements a module which queries the Mozilla IoT gateway.
'''

import getpass
import json
import logging
import os
import pathlib
import requests

class GatewayConfig:

    def __init__(self):
        self.filename = str(pathlib.Path.home() / '.moziot-cli.json')
        self.config = {}
        self.dirty = False
        if (os.path.isfile(self.filename)):
          try:
              with open(self.filename, 'r') as config_file:
                  self.config = json.load(config_file)
          except:
              pass
        if not 'gateways' in self.config:
            self.config['gateways'] = {}

    def get(self, key):
        if key in self.root:
            return self.root[key]
        return ''

    def print(self):
        print(self.config)

    def save(self):
        if self.dirty:
          tmp_filename = self.filename + '.tmp'
          with open(tmp_filename, 'w') as config_file:
              json.dump(self.config, config_file)
          os.rename(tmp_filename, self.filename)
          self.dirty = False

    def set_root(self, key, value):
        if value not in self.config[key]:
          self.config[key][value] = {}
        self.root = self.config[key][value]

    def set(self, key, value):
        self.dirty = True
        self.root[key] = value


class Gateway:

    def __init__(self, gateway_url, config, log=None):
        self.gateway_url = gateway_url
        self.config = config
        self.log = log or logging.getLogger(__name__)
        self.headers = {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
        jwt = config.get('jwt')
        if jwt:
            self.set_jwt(jwt)

    def bind(self, deviceId, endpointNum, clusterId):
        url = '/debug/device/{}/cmd/bind'.format(deviceId)
        params = {
          'srcEndpoint': endpointNum,
          'clusterId': clusterId,
        }
        self.put(url, data=params)

    def bindings(self, deviceId):
        url = '/debug/device/{}/cmd/bindings'.format(deviceId)
        self.put(url, data={})

    def debugCmd(self, deviceId, cmd, params):
        url = '/debug/device/{}/cmd/{}'.format(deviceId, cmd)
        r = self.put(url, data=params)
        print('r.status_code =', r.status_code)
        print('r.text =', r.text)

    def device(self, name):
        r = self.get('/debug/device/' + name)
        if r is None:
            return
        return r.json()

    def devices(self):
        r = self.get('/debug/devices')
        if r is None:
            return
        # returns an array of objects. We just want the ids
        return [device['id'] for device in r.json()]

    def discoverAttr(self, deviceId, endpointNum, clusterId):
        url = '/debug/device/{}/cmd/discoverAttr'.format(deviceId)
        params = {}
        if endpointNum:
          params['endpoint'] = endpointNum
        if clusterId:
          params['clusterId'] = clusterId
        r = self.put(url, data=params)
        print('r.status_code =', r.status_code)
        print('r.text =', r.text)

    def get(self, path):
        while True:
          try:
              url = self.url(path)
              r = requests.get(url,
                              verify=False,
                              headers=self.headers)
          except requests.exceptions.ConnectionError:
              self.log.error('Unable to connect to server: %s', url)
              return
          if r.status_code == 200:
              return r
          if r.status_code == 404:
              return
          if r.status_code != 401:
              self.log.error('GET failed: %s - %s', r.status_code, r.text)
              return
          # Unauthorized - need to get a valid JWT
          self.login()

    def login(self):
        while True:
          try:
            email = input('Enter    email: ')
          except EOFError: # Control-D
            print('')
            return
          try:
            password = getpass.getpass(prompt='Enter password: ')
          except EOFError: # Control-D
            print('')
            return
          try:
              url = self.url('/login')
              r = requests.post(url,
                                verify=False,
                                headers=self.headers,
                                data=json.dumps({
                                  'email': email,
                                  'password': password}))
          except requests.exceptions.ConnectionError:
              self.log.error('Unable to connect to server: %s', url)
              return
          if r.status_code == 200:
            jwt = r.json()['jwt']
            self.set_jwt(jwt)
            return jwt
          self.log.error('Login failed: %s', r.text)

    def properties(self, id):
        url = '/things/{}/properties'.format(id)
        r = self.get(url)
        if r is None:
            return
        return r.json()

    def property(self, id, propertyName):
        url = '/things/{}/properties/{}'.format(id, propertyName)
        r = self.get(url)
        if r is None:
            return
        return r.json()

    def put(self, path, data=None):
        while True:
          try:
              url = self.url(path)

              r = requests.put(url,
                              verify=False,
                              headers=self.headers,
                              data=json.dumps(data))
          except requests.exceptions.ConnectionError:
              self.log.error('Unable to connect to server: %s', url)
              return
          if r.status_code == 200:
              return r
          if r.status_code == 404:
              return
          if r.status_code != 401:
              self.log.error('GET failed: %s - %s', r.status_code, r.text)
              return
          # Unauthorized - need to get a valid JWT
          self.login()

    def readAttr(self, deviceId, endpointNum, profileId, clusterId, attrIds):
        url = '/debug/device/{}/cmd/readAttr'.format(deviceId)
        params = {
          'endpoint': endpointNum,
          'profileId': profileId,
          'clusterId': clusterId,
          'attrId': attrIds
        }
        print('url =', url)
        print('params =', params)
        print('json.dumps(params) =', json.dumps(params))
        r = self.put(url, data=params)
        print('r.status_code =', r.status_code)
        print('r.text =', r.text)

    def set_jwt(self, jwt):
        self.config.set('jwt', jwt)
        self.headers['Authorization'] = 'Bearer ' + jwt

    def thing(self, id):
        r = self.get('/things/' + id)
        if r is None:
            return
        return r.json()

    def things(self, info=False):
        r = self.get('/things')
        if r is None:
            return
        # returns an array of objects. We just want the names
        if info:
          return r.json()
        return [os.path.basename(thing['href']) for thing in r.json()]

    def url(self, path=''):
        return self.gateway_url + path


requests.packages.urllib3.disable_warnings()
