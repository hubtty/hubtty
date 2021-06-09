# Copyright 2020 Martin André <martin.andre@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import requests
import sys
import time

CLIENT_ID = '945afaeb8ba1cd489eab'


def requestOneTimeCode(url):
    header = {'Accept': 'application/json'}
    data = {
        'client_id': CLIENT_ID,
        # NOTE: user needs to grant access to organizations individually
        'scope': 'repo,read:org'
    }
    r = requests.post(url, headers=header, json=data)

    if 'error' in r.json():
        sys.exit("Failed to request device code %s: %s" % (r.json()['error'], r.json()['error_description']))
    return r.json()


def printUserCode(code, url):
    print("Hubtty needs to access your github account.")
    print("Copy the code %s and paste it at %s" % (code, url))


def poll(url, one_time_code):
    header = {'Accept': 'application/json'}
    data={
        'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
        'device_code': one_time_code['device_code'],
        'client_id': CLIENT_ID
    }

    timeout = one_time_code['expires_in']
    interval = one_time_code['interval']
    while True:
        time.sleep(interval)
        timeout -= interval

        r = requests.post(url, headers=header, data=data)

        if 'error' in r.json():
            if r.json()['error'] == 'authorization_pending':
                pass
            elif r.json()['error'] == 'slow_down':
                interval += 5
                pass
            else:
                sys.exit("Failed to get auth token %s: %s" % (r.json()['error'], r.json()['error_description']))
        else:
            break

        if timeout < 0:
            sys.exit("One-time code timed out")

    return r.json()


def getToken(base_url):
    one_time_code = requestOneTimeCode(base_url + 'login/device/code')
    printUserCode(one_time_code['user_code'], one_time_code['verification_uri'])
    token = poll(base_url + 'login/oauth/access_token', one_time_code)

    return token['access_token']
