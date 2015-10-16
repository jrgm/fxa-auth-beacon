#!./bin/python

import hashlib
import httplib
import os
import random
import re
import requests
import time
from urlparse import urlparse

from fxa._utils import APIClient
from fxa.core import Client

from restmail import Restmail

# The tests need a public key for the server to sign, but we don't actually
# do anything with it.  It suffices to use a fixed dummy key throughout.
DUMMY_PUBLIC_KEY = {
    'algorithm': 'RS',
    'n': '475938596723561050357149433919674961454460669256778579'
         '095393476820271428065297309134131686299358278907987200'
         '7974809511698859885077002492642203267408776123',
    'e': '65537',
}

# used for request/response logging
HTTP_LOG_NAME = ('/tmp/fxa-auth-beacon-%s.log' %
                 time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
HTTP_LOG = open(HTTP_LOG_NAME, 'a')


def log_request(data):
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    HTTP_LOG.write('>>>> %s >>>>>>>>>>>>>>\r\n' % timestamp)
    HTTP_LOG.write(data)
    HTTP_LOG.write('\r\n\r\n')


def log_response(res):
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    HTTP_LOG.write('<<<< %s <<<<<<<<<<<<<<\r\n' % timestamp)
    HTTP_LOG.write('%s %s\r\n' % (res.status, res.reason))
    for k, v in res.getheaders():
        HTTP_LOG.write('%s: %s\r\n' % (k, v))
    HTTP_LOG.write('\r\n')


def uniq(size=32):
    """Generate a random hex string of a given length."""
    return os.urandom(size // 2 + 1).encode('hex')[:size]


class FxATiming(object):

    server_url = 'https://api-accounts.stage.mozaws.net/v1'

    def __init__(self, server_url=None):
        if server_url is None:
            server_url = self.server_url

        self.session = requests.Session()
        apiclient = APIClient(self.server_url, session=self.session)
        self.client = Client(apiclient)

        # setup to capture req/res timings
        self._patch_send()
        self._patch_getresponse()
        self.timing_data = {}
        self.current_uri = ()
        self.current_start = 0

    # hook into http request for timing
    def _patch_send(self):
        old_send = httplib.HTTPConnection.send

        def new_send(context, data):
            self.current_start = time.time()

            lines = data.split('\r\n')
            [method, path, proto] = re.split('\s+', lines.pop(0))
            path = urlparse(path).path

            headers = {}
            for line in lines:
                if len(line) == 0:
                    break
                [key, val] = line.split(': ')
                headers[key.lower()] = val

            request = (headers['host'], method, path)
            self.current_uri = request

            if self.current_uri not in self.timing_data:
                self.timing_data[self.current_uri] = {
                    'times': [],
                    'codes': []
                }

            log_request(data)
            req = old_send(context, data)

            return req

        httplib.HTTPConnection.send = new_send

    # hook into http response for timing
    def _patch_getresponse(self):
        old_getresponse = httplib.HTTPConnection.getresponse

        def new_getresponse(context):
            res = old_getresponse(context)
            elapsed = time.time() - self.current_start
            log_response(res)

            self.timing_data[self.current_uri]['times'].append(elapsed)
            self.timing_data[self.current_uri]['codes'].append(res.status)
            self.current_uri = ()
            self.current_start = 0

            return res

        httplib.HTTPConnection.getresponse = new_getresponse

    def _get_stretchpwd(self, email):
        return hashlib.sha256(email).hexdigest()

    def _get_user_email(self):
        uid = uniq()
        self.user_email = "fxa-timing-{}@restmail.net".format(uid)
        return self.user_email

    def _get_existing_user_email(self):
        uid = random.randint(1, 999)
        return "loads-fxa-{}-old@restmail.net".format(uid)

    def dump_requests(self):
        for k, v in self.timing_data.items():
            if k[0] == 'restmail.net':
                continue
            args = (k[0], k[1], k[2], v['codes'][0], v['times'][0])
            print "%s %-4s %-32s %3d %.4f" % args

    def run(self):
        self.login_session_flow()
        # self.password_reset_flow()
        self.dump_requests()

    def login_session_flow(self):
        """Do a full login-flow with cert signing etc."""
        # Login as a new user.
        session = self._authenticate_as_new_user()

        session.get_email_status()
        session.fetch_keys()
        session.check_session_status()
        session.get_random_bytes()
        session.sign_certificate(DUMMY_PUBLIC_KEY)

        base_url = self.server_url[:-3]
        self.session.get(base_url + "/.well-known/browserid")

        stretchpwd = self._get_stretchpwd(session.email)
        self.client.change_password(
            session.email,
            oldstretchpwd=stretchpwd,
            newstretchpwd=stretchpwd,
        )

        kwds = {
            "email": session.email,
            "stretchpwd": stretchpwd,
            "keys": True
        }
        session = self.client.login(**kwds)

        pftok = self.client.send_reset_code(session.email)
        pftok.get_status()

        # verify the password forgot code.
        acct = Restmail(email=session.email)
        mail = acct.wait_for_email(lambda m: "x-recovery-code" in m["headers"])
        if not mail:
            raise RuntimeError("Password reset email was not received")
        acct.clear()
        code = mail["headers"]["x-recovery-code"]

        # Now verify with the actual code, and reset the account.
        artok = pftok.verify_code(code)
        self.client.reset_account(
            email=session.email,
            token=artok,
            stretchpwd=stretchpwd
        )

        session = self.client.login(**kwds)
        session.destroy_session()
        self.client.destroy_account(email=session.email,
                                    stretchpwd=stretchpwd)

    def _authenticate_as_new_user(self):
        email = self._get_user_email()
        stretchpwd = self._get_stretchpwd(email)
        kwds = {
            "email": email,
            "stretchpwd": stretchpwd,
            "keys": True
        }

        session = self.client.create_account(**kwds)

        # resend the confirmation email.
        session.resend_email_code()

        # verify the confirmation code.
        acct = Restmail(email=email)
        mail = acct.wait_for_email(lambda m: "x-verify-code" in m["headers"])
        if not mail:
            raise RuntimeError("Verification email was not received")
        acct.clear()
        session.verify_email_code(mail["headers"]["x-verify-code"])

        return self.client.login(**kwds)


def main():
    FxATiming().run()

if __name__ == "__main__":
    main()
