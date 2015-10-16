import requests
import time

from six.moves.urllib.parse import urlparse, urljoin

from fxa._utils import uniq


class Restmail(object):
    """A live email account that can be used for testing purposes.

    This is a simple interface to http://restmail.net that allows you to
    use a live email account for testing purposes.  Instantiated with no
    arguments, you will get a randomly-generated <something>@restmail.net
    address and the ability to read email delivered there via the following
    API:

        * email:     the string email address for this account
        * messages:  list of messages currently in the account, newest first
        * fetch():   update list of messages currently in the account
        * clear():   delete any messages stored in the account

    To customize the email address, pass a string as first argument.  It can
    include string-formatting placeholders for "{uniq}" and "{hostname}" if
    you want these to be filled in automatically.
    """

    DEFAULT_SERVER_URL = "http://restmail.net"

    def __init__(self, email=None, server_url=None):
        if server_url is None:
            server_url = self.DEFAULT_SERVER_URL
        if email is None:
            email = "test-{uniq}@{hostname}"
        hostname = urlparse(server_url).hostname
        self.email = email.format(uniq=uniq(), hostname=hostname)
        self.server_url = server_url
        if self.email.endswith("@" + hostname):
            userid = self.email.rsplit("@", 1)[0]
        else:
            userid = self.email
        self.user_url = urljoin(self.server_url, "/mail/" + userid)
        self.messages = []

    def fetch(self):
        resp = requests.get(self.user_url)
        resp.raise_for_status()
        self.messages[:] = resp.json()

    def clear(self):
        resp = requests.delete(self.user_url)
        resp.raise_for_status()
        self.messages[:] = []

    def find_email(self, callback=lambda: True):
        for m in self.messages:
            if callback(m):
                return m
        return None

    def wait_for_email(self, callback=lambda: True, timeout=30):
        start_time = time.time()
        while True:
            self.fetch()
            m = self.find_email(callback)
            if m is not None:
                return m
            if start_time + timeout < time.time():
                return None
