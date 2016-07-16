# -*- coding: utf-8 -*-
from future import standard_library
standard_library.install_aliases()
from builtins import object
import re
from requests import Session
import requests
import urllib.request, urllib.parse, urllib.error
from sqlalchemy import Column, Integer, String, ForeignKey
from monitorrent.db import Base, DBSession
from monitorrent.plugins import Topic
from monitorrent.plugin_managers import register_plugin
from monitorrent.utils.soup import get_soup
from monitorrent.utils.bittorrent import Torrent
from monitorrent.plugins.trackers import TrackerPluginBase, WithCredentialsMixin, ExecuteWithHashChangeMixin, LoginResult
from urlparse import urlparse
from urllib2 import unquote
from phpserialize import loads

PLUGIN_NAME = 'nnmclub.to'


class NnmClubCredentials(Base):
    __tablename__ = "nnmclub_credentials"

    username = Column(String, primary_key=True)
    password = Column(String, primary_key=True)
    user_id = Column(String, nullable=True)
    sid = Column(String, nullable=True)


class NnmClubTopic(Topic):
    __tablename__ = "nnmclub_topics"

    id = Column(Integer, ForeignKey('topics.id'), primary_key=True)
    download_id = Column(String, nullable=False)
    hash = Column(String, nullable=True)

    __mapper_args__ = {
        'polymorphic_identity': PLUGIN_NAME
    }


class NnmClubLoginFailedException(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message


class NnmClubTracker(object):
    tracker_settings = None
    tracker_domains = ['nnmclub.to', 'nnm-club.me']
    title_headers = ['torrent :: nnm-club']
    _login_url = 'http://nnm-club.me/forum/login.php'
    _profile_page = "http://nnmclub.to/forum/profile.php?mode=viewprofile&u={}"

    def __init__(self, user_id=None, sid=None):
        self.user_id = user_id
        self.sid = sid

    def setup(self, user_id=None, sid=None):
        self.user_id = user_id
        self.sid = sid

    def can_parse_url(self, url):
        parsed_url = urlparse(url)
        return any([parsed_url.netloc == tracker_domain for tracker_domain in self.tracker_domains])

    def parse_url(self, url):
        url = self.get_url(url)
        if not url or not self.can_parse_url(url):
            return None
        parsed_url = urlparse(url)
        if not parsed_url.path == '/forum/viewtopic.php':
            return None

        r = requests.get(url, allow_redirects=False, timeout=self.tracker_settings.requests_timeout)
        if r.status_code != 200:
            return None
        soup = get_soup(r.text)
        title = soup.title.string.strip()
        for title_header in self.title_headers:
            if title.lower().endswith(title_header):
                title = title[:-len(title_header)].strip()
                break

        return self._get_title(title)

    def login(self, username, password):
        s = Session()
        data = {"username": username, "password": password, "autologin": "on", "login": "%C2%F5%EE%E4"}
        login_result = s.post(self._login_url, data, timeout=self.tracker_settings.requests_timeout)
        if login_result.url.startswith(self._login_url):
            # TODO get error info (although it shouldn't contain anything useful
            raise NnmClubLoginFailedException(1, "Invalid login or password")
        else:
            sid = s.cookies['phpbb2mysql_4_sid']
            data = s.cookies['phpbb2mysql_4_data']
            parsed_data = loads(unquote(data))
            self.user_id = parsed_data['userid']
            self.sid = sid

    def verify(self):
        cookies = self.get_cookies()
        if not cookies:
            return False
        profile_page_url = self._profile_page.format(self.user_id)
        profile_page_result = requests.get(profile_page_url, cookies=cookies,
                                           timeout=self.tracker_settings.requests_timeout)
        return profile_page_result.url == profile_page_url

    def get_cookies(self):
        if not self.sid:
            return False
        return {'phpbb2mysql_4_sid': self.sid}

    def get_download_url(self, url):
        cookies = self.get_cookies()
        page = requests.get(url, cookies=cookies, timeout=self.tracker_settings.requests_timeout)
        page_soup = get_soup(page.text)
        anchors = page_soup.find_all("a")
        da = filter(lambda tag: tag.has_attr('href') and tag.attrs['href'].startswith("download.php?id="), anchors)
        # not a free torrent
        if len(da) == 0:
            return None
        download_url = 'http://' + self.tracker_domains[0] + '/forum/' + da[0].attrs['href']
        return download_url

    def get_url(self, url):
        if not self.can_parse_url(url):
            return False
        parsed_url = urlparse(url)
        parsed_url = parsed_url._replace(netloc=self.tracker_domains[0])
        return parsed_url.geturl()

    @staticmethod
    def _get_title(title):
        return {'original_name': title}
