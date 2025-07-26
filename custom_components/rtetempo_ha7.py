"""
RTE Tempo pour Home Assistant 7.5 (rétrocompatible, sensors + calendrier)
A placer dans custom_components/rtetempo.py
"""
import datetime
import logging
import threading
import requests
from requests.auth import HTTPBasicAuth
from requests_oauthlib import OAuth2Session

import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant.helpers.entity import Entity
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET

_LOGGER = logging.getLogger(__name__)

DOMAIN = "rtetempo"
CONF_ADJUSTED_DAYS = "adjusted_days"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_CLIENT_ID): cv.string,
        vol.Required(CONF_CLIENT_SECRET): cv.string,
        vol.Optional(CONF_ADJUSTED_DAYS, default=False): cv.boolean,
    })
}, extra=vol.ALLOW_EXTRA)

API_TOKEN_ENDPOINT = "https://digital.iservices.rte-france.com/token/oauth/"
API_TEMPO_ENDPOINT = "https://digital.iservices.rte-france.com/open_api/tempo_like_supply_contract/v1/tempo_days"

class TempoDay:
    def __init__(self, start, end, value, updated):
        self.Start = start
        self.End = end
        self.Value = value
        self.Updated = updated

class APIWorker(threading.Thread):
    def __init__(self, client_id, client_secret, adjusted_days):
        self._stopevent = threading.Event()
        self._auth = HTTPBasicAuth(client_id, client_secret)
        self._oauth = OAuth2Session(client=client_id)
        self._tempo_days = []
        self.adjusted_days = adjusted_days
        super().__init__()

    def get_calendar_days(self):
        return self._tempo_days

    def run(self):
        while not self._stopevent.is_set():
            try:
                self._get_access_token()
                self._update_tempo_days()
            except Exception as e:
                _LOGGER.error("Erreur API Tempo: %s", e)
            self._stopevent.wait(3600)

    def _get_access_token(self):
        token = self._oauth.fetch_token(
            API_TOKEN_ENDPOINT,
            auth=self._auth,
            include_client_id=True
        )
        return token

    def _update_tempo_days(self):
        resp = self._oauth.get(API_TEMPO_ENDPOINT)
        data = resp.json()
        self._tempo_days = []
        for d in data.get("tempo_days", []):
            self._tempo_days.append(
                TempoDay(
                    start=datetime.datetime.strptime(d["start_date"], "%Y-%m-%dT%H:%M:%S%z"),
                    end=datetime.datetime.strptime(d["end_date"], "%Y-%m-%dT%H:%M:%S%z"),
                    value=d["value"],
                    updated=datetime.datetime.now()
                )
            )

    def stop(self):
        self._stopevent.set()

def setup(hass, config):
    conf = config[DOMAIN]
    client_id = conf[CONF_CLIENT_ID]
    client_secret = conf[CONF_CLIENT_SECRET]
    adjusted_days = conf.get(CONF_ADJUSTED_DAYS, False)
    worker = APIWorker(client_id, client_secret, adjusted_days)
    worker.start()
    hass.data[DOMAIN] = worker
    hass.helpers.discovery.load_platform("sensor", DOMAIN, {}, config)
    hass.helpers.discovery.load_platform("calendar", DOMAIN, {}, config)
    return True

# Sensor platform
from homeassistant.helpers.entity import Entity

def setup_platform(hass, config, add_entities, discovery_info=None):
    worker = hass.data[DOMAIN]
    add_entities([
        TempoColorSensor(worker),
        TempoDaysLeftSensor(worker, "BLUE"),
        TempoDaysLeftSensor(worker, "WHITE"),
        TempoDaysLeftSensor(worker, "RED"),
    ])

class TempoColorSensor(Entity):
    def __init__(self, worker):
        self._worker = worker
        self._state = None
    @property
    def name(self):
        return "Tempo Couleur du jour"
    @property
    def state(self):
        days = self._worker.get_calendar_days()
        if days:
            return days[0].Value
        return None

class TempoDaysLeftSensor(Entity):
    def __init__(self, worker, color):
        self._worker = worker
        self._color = color
        self._state = None
    @property
    def name(self):
        return f"Tempo Jours Restants {self._color}"
    @property
    def state(self):
        days = self._worker.get_calendar_days()
        return sum(1 for d in days if d.Value == self._color)

# Calendar platform
from homeassistant.components.calendar import CalendarEvent, CalendarEntity

def setup_platform_calendar(hass, config, add_entities, discovery_info=None):
    worker = hass.data[DOMAIN]
    add_entities([TempoCalendar(worker)])

class TempoCalendar(CalendarEntity):
    def __init__(self, worker):
        self._worker = worker
        self._event = None
    @property
    def name(self):
        return "Tempo Calendrier"
    def get_events(self, start_date, end_date):
        days = self._worker.get_calendar_days()
        events = []
        for d in days:
            if d.Start >= start_date and d.End <= end_date:
                events.append(CalendarEvent(d.Start, d.End, d.Value))
        return events
